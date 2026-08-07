from __future__ import annotations

import hashlib
import json
import math
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Batch,
    FlightGroup,
    FlightPlan,
    GroupNode,
    RecoveryAttempt,
    RecoveryDelivery,
    RecoveryNodeDisposition,
    RecoveryPolicy,
    RecoveryResolution,
    SimulationRun,
    utcnow,
)
from app.gateways import (
    FlightPlanRecoveryGateway,
    OutboundGateway,
    PreviewOnlyFlightPlanRecoveryGateway,
    PreviewOnlyOutboundGateway,
)


DEFAULT_RECOVERY_CONFIG: dict[str, Any] = {
    "temporary_group_send_enabled": False,
    "flight_recovery_enabled": True,
    "max_attempts": 3,
    "request_window_before_minutes": 120,
    "request_window_after_minutes": 120,
    "recovery_deadline_minutes": 120,
    "terminal_scan_interval_seconds": 60,
    "outbox_max_wait_seconds": 300,
    "max_unassigned_rate": 0.3,
    "max_data_error_rate": 0.01,
    "recovery_exhausted_disposition": "UNASSIGNED_FINAL",
    "data_error_recovery_enabled": False,
    "destination_capability": "UNSUPPORTED",
}


async def effective_policy(
    db: AsyncSession,
    airport_code: str = "XIY",
    tenant_code: str = "default",
    destination: str | None = None,
) -> RecoveryPolicy:
    resolved_destination = destination or ("xian_bus" if airport_code == "XIY" else "default_bus")
    policy = (
        await db.execute(
            select(RecoveryPolicy)
            .where(
                RecoveryPolicy.airport_code == airport_code,
                RecoveryPolicy.tenant_code == tenant_code,
                RecoveryPolicy.destination == resolved_destination,
                RecoveryPolicy.status == "published",
            )
            .order_by(RecoveryPolicy.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if policy:
        return policy
    policy = RecoveryPolicy(
        airport_code=airport_code,
        tenant_code=tenant_code,
        destination=resolved_destination,
        version=1,
        status="published",
        config=DEFAULT_RECOVERY_CONFIG.copy(),
        idempotency_key=f"bootstrap-{airport_code}-{tenant_code}-{resolved_destination}-v1",
        approved_at=utcnow(),
        published_at=utcnow(),
    )
    db.add(policy)
    await db.flush()
    return policy


def machine_state(group: FlightGroup, config: dict[str, Any]) -> tuple[str, str]:
    tags = set(group.issue_tags or [])
    if group.assignment_status == "DATA_ERROR":
        return "DATA_ERROR", "RAW_NODE_UNRECOVERABLE"
    if group.assignment_status == "MATCHED_RECOVERED" and group.assigned_flight_id is not None:
        return "MATCHED_RECOVERED", "PLAN_RECOVERED"
    if group.assignment_status == "MATCHED_REFERENCE_NO_PLAN" or "ACDM_PLAN_MISSING" in tags:
        return (
            ("RECOVERY_PENDING", "PLAN_MISSING")
            if config.get("flight_recovery_enabled", True)
            else ("UNASSIGNED_FINAL", "RECOVERY_DISABLED")
        )
    if group.assignment_status.startswith("MATCHED") and group.assigned_flight_id is not None:
        return "MATCHED", "MATCH_CONFIRMED"
    if "MISSING_PLAN" in tags and group.assignment_status != "UNASSIGNED_FINAL":
        return (
            ("RECOVERY_PENDING", "PLAN_MISSING")
            if config.get("flight_recovery_enabled", True)
            else ("UNASSIGNED_FINAL", "RECOVERY_DISABLED")
        )
    if "AMBIGUOUS_MATCH" in tags:
        return "UNASSIGNED_FINAL", "CANDIDATE_AMBIGUOUS"
    if "INCOMPLETE_FRAGMENT" in tags or "DEGRADED" in tags:
        return "UNASSIGNED_FINAL", "INCOMPLETE_FRAGMENT"
    return "UNASSIGNED_FINAL", "NO_RELIABLE_CANDIDATE"


def outbound_state(
    machine_status: str,
    temporary_send_enabled: bool,
    *,
    already_sent: bool = False,
) -> tuple[str, str]:
    if already_sent:
        return "NOOP_ALREADY_SENT", "ALREADY_SENT"
    if machine_status == "RECOVERY_PENDING":
        return "WAIT_FOR_RECOVERY", "NOT_CREATED"
    if machine_status == "DATA_ERROR":
        return "NOT_APPLICABLE", "NOT_CREATED"
    if machine_status == "UNASSIGNED_FINAL":
        return (
            ("SEND_TEMPORARY_GROUP", "PENDING")
            if temporary_send_enabled
            else ("SUPPRESS_TEMPORARY_GROUP", "SUPPRESSED_BY_POLICY")
        )
    return "SEND_MATCHED_ONLY", "PENDING"


def _member_hash(group: FlightGroup) -> str:
    ids = [item.node_id for item in sorted(group.nodes, key=lambda row: row.order_index)]
    return hashlib.sha256(",".join(map(str, ids)).encode()).hexdigest()


async def _replace_terminal_records(
    db: AsyncSession,
    items: list[tuple[RecoveryResolution, FlightGroup]],
) -> None:
    if not items:
        return
    group_ids = [group.id for _, group in items]
    await db.execute(
        delete(RecoveryNodeDisposition).where(RecoveryNodeDisposition.group_id.in_(group_ids))
    )
    await db.execute(delete(RecoveryDelivery).where(RecoveryDelivery.group_id.in_(group_ids)))
    dispositions: list[dict[str, Any]] = []
    deliveries: list[dict[str, Any]] = []
    for resolution, group in items:
        if resolution.machine_status == "RECOVERY_PENDING":
            continue
        disposition = {
            "MATCHED": "ASSIGNED",
            "MATCHED_RECOVERED": "ASSIGNED",
            "UNASSIGNED_FINAL": "UNASSIGNED_FINAL",
            "DATA_ERROR": "QUARANTINED",
        }[resolution.machine_status]
        dispositions.extend(
            {
                "resolution_id": resolution.id,
                "group_id": group.id,
                "node_id": member.node_id,
                "disposition": disposition,
                "reason_code": resolution.reason_code,
                "created_at": utcnow(),
            }
            for member in group.nodes
        )
        payload = None
        suppression_reason = None
        if resolution.outbox_status == "PENDING" and group.assigned_flight_id is not None:
            payload = {
                "temporary_group_id": group.temporary_code,
                "flight_plan_id": group.assigned_flight_id,
                "stand": group.stand,
                "node_ids": [member.node_id for member in group.nodes],
            }
        elif (
            resolution.outbox_status == "PENDING"
            and resolution.outbound_policy == "SEND_TEMPORARY_GROUP"
        ):
            payload = {
                "temporary_group_id": group.temporary_code,
                "flight_no": None,
                "safeguard_code": None,
                "stand": group.stand,
                "observed_start": group.observed_start.isoformat(),
                "observed_end": group.observed_end.isoformat(),
                "node_ids": [member.node_id for member in group.nodes],
            }
        elif resolution.outbox_status == "SUPPRESSED_BY_POLICY":
            suppression_reason = "XIY_BUS_REJECTS_TEMPORARY_GROUP"
        elif resolution.outbox_status == "ALREADY_SENT":
            suppression_reason = "SOURCE_NODES_ALREADY_SENT"
        deliveries.append(
            {
                "resolution_id": resolution.id,
                "group_id": group.id,
                "policy_action": resolution.outbound_policy,
                "outbox_status": resolution.outbox_status,
                "payload": payload,
                "suppression_reason": suppression_reason,
                "created_at": utcnow(),
            }
        )
    if dispositions:
        await db.execute(insert(RecoveryNodeDisposition), dispositions)
    if deliveries:
        await db.execute(insert(RecoveryDelivery), deliveries)


async def _remove_superseded_recovery_records(db: AsyncSession, run_id: int) -> None:
    superseded_group_ids = list(
        (
            await db.execute(
                select(FlightGroup.id).where(
                    FlightGroup.run_id == run_id,
                    FlightGroup.assignment_status == "SUPERSEDED",
                )
            )
        ).scalars()
    )
    if not superseded_group_ids:
        return
    resolution_ids = list(
        (
            await db.execute(
                select(RecoveryResolution.id).where(
                    RecoveryResolution.group_id.in_(superseded_group_ids)
                )
            )
        ).scalars()
    )
    if resolution_ids:
        await db.execute(
            delete(RecoveryAttempt).where(RecoveryAttempt.resolution_id.in_(resolution_ids))
        )
    await db.execute(
        delete(RecoveryNodeDisposition).where(
            RecoveryNodeDisposition.group_id.in_(superseded_group_ids)
        )
    )
    await db.execute(
        delete(RecoveryDelivery).where(RecoveryDelivery.group_id.in_(superseded_group_ids))
    )
    await db.execute(
        delete(RecoveryResolution).where(RecoveryResolution.group_id.in_(superseded_group_ids))
    )


async def ensure_run_resolutions(
    db: AsyncSession,
    run_id: int | None = None,
    *,
    commit: bool = True,
) -> tuple[SimulationRun, Batch, RecoveryPolicy, list[RecoveryResolution]]:
    run = (
        await db.get(SimulationRun, run_id)
        if run_id
        else (
            await db.execute(select(SimulationRun).order_by(SimulationRun.id.desc()).limit(1))
        ).scalar_one_or_none()
    )
    if not run:
        raise LookupError("运行不存在")
    batch = await db.get(Batch, run.batch_id)
    if not batch:
        raise LookupError("批次不存在")
    policy = await effective_policy(db, batch.airport_code)
    config = DEFAULT_RECOVERY_CONFIG | dict(policy.config or {})
    await _remove_superseded_recovery_records(db, run.id)
    groups = list(
        (
            await db.execute(
                select(FlightGroup)
                .where(
                    FlightGroup.run_id == run.id,
                    FlightGroup.assignment_status != "SUPERSEDED",
                )
                .options(
                    selectinload(FlightGroup.nodes).selectinload(GroupNode.node),
                    selectinload(FlightGroup.candidates),
                )
                .order_by(FlightGroup.observed_start)
            )
        ).scalars()
    )
    existing = {
        row.group_id: row
        for row in (
            await db.execute(
                select(RecoveryResolution).where(
                    RecoveryResolution.group_id.in_([group.id for group in groups] or [-1])
                )
            )
        ).scalars()
    }
    delivery_group_ids = set(
        (
            await db.execute(
                select(RecoveryDelivery.group_id).where(
                    RecoveryDelivery.group_id.in_([group.id for group in groups] or [-1])
                )
            )
        ).scalars()
    )
    now = utcnow()
    changed: list[tuple[RecoveryResolution, FlightGroup]] = []
    for group in groups:
        member_hash = _member_hash(group)
        current = existing.get(group.id)
        immutable_sent = current is not None and current.outbox_status in {
            "SENT",
            "ALREADY_SENT",
        }
        if immutable_sent:
            continue
        derived_status, reason = machine_state(group, config)
        if (
            current
            and current.member_hash == member_hash
            and current.config_version == policy.version
        ):
            if current.machine_status != "RECOVERY_PENDING" and group.id not in delivery_group_ids:
                changed.append((current, group))
            continue
        previous_attempt_count = current.attempt_count if current else 0
        member_changed = current is not None and current.member_hash != member_hash
        if member_changed:
            await db.execute(
                delete(RecoveryAttempt).where(RecoveryAttempt.resolution_id == current.id)
            )
        version = (current.group_version + 1) if current else 1
        resolution = current or RecoveryResolution(group_id=group.id)
        if not current:
            db.add(resolution)
            existing[group.id] = resolution
        resolution.group_version = version
        resolution.member_hash = member_hash
        resolution.machine_status = derived_status
        resolution.reason_code = reason
        resolution.attempt_count = 0 if member_changed else previous_attempt_count
        resolution.max_attempts = int(config["max_attempts"])
        resolution.recovery_deadline = (
            now + timedelta(minutes=int(config["recovery_deadline_minutes"]))
            if derived_status == "RECOVERY_PENDING"
            else None
        )
        resolution.next_attempt_at = now if derived_status == "RECOVERY_PENDING" else None
        resolution.request_window_start = group.observed_start - timedelta(
            minutes=int(config["request_window_before_minutes"])
        )
        resolution.request_window_end = group.observed_end + timedelta(
            minutes=int(config["request_window_after_minutes"])
        )
        resolution.response_flight_count = 0
        resolution.recovery_request_id = None
        resolution.candidate_summary = [
            {"flight_plan_id": item.flight_plan_id, "rank": item.rank, "score": item.score}
            for item in sorted(group.candidates, key=lambda row: row.rank)
        ]
        resolution.status_timeline = [
            {"status": derived_status, "at": now.isoformat(), "reason": reason}
        ]
        resolution.outbound_policy, resolution.outbox_status = outbound_state(
            derived_status,
            bool(config["temporary_group_send_enabled"]),
            already_sent=bool((group.lineage or {}).get("immutable_sent_replay")),
        )
        resolution.config_version = policy.version
        resolution.strategy_version = run.strategy_version_id
        resolution.finalized_at = None if derived_status == "RECOVERY_PENDING" else now
        await db.flush()
        changed.append((resolution, group))
    await _replace_terminal_records(db, changed)
    if commit:
        await db.commit()
    else:
        await db.flush()
    return run, batch, policy, [existing[group.id] for group in groups]


def _recovery_plan(
    group: FlightGroup,
    plans: list[FlightPlan],
    request_window_start: Any | None = None,
    request_window_end: Any | None = None,
) -> FlightPlan | None:
    node_reported = {
        (member.node.reported_flight_no or "").upper()
        for member in group.nodes
        if member.node.reported_flight_no
    }
    acdm_reference = (group.lineage or {}).get("acdm_reference") or {}
    acdm_flight_no = str(acdm_reference.get("flight_no") or "").upper()
    reported = {acdm_flight_no} if acdm_flight_no else node_reported
    window_start = request_window_start or group.observed_start
    window_end = request_window_end or group.observed_end
    reported_matches = [
        plan
        for plan in plans
        if plan.plan_start
        and plan.plan_end
        and reported
        & {
            (plan.inbound_flight_no or "").upper(),
            (plan.outbound_flight_no or "").upper(),
        }
        and plan.plan_start <= window_end
        and plan.plan_end >= window_start
    ]
    if len(reported_matches) == 1:
        return reported_matches[0]
    if "ACDM_PLAN_MISSING" in (group.issue_tags or []):
        return None
    candidates = [
        plan
        for plan in plans
        if plan.stand == group.stand
        and plan.plan_start
        and plan.plan_end
        and plan.plan_start <= window_end
        and plan.plan_end >= window_start
    ]
    ranked = sorted(
        candidates,
        key=lambda plan: (
            abs((plan.plan_start - group.observed_start).total_seconds()),
            plan.id,
        ),
    )
    if len(ranked) == 1:
        return ranked[0]
    if len(ranked) > 1:
        first = abs((ranked[0].plan_start - group.observed_start).total_seconds())
        second = abs((ranked[1].plan_start - group.observed_start).total_seconds())
        if second - first >= 30 * 60:
            return ranked[0]
    return None


async def _claim_recovery_attempt(
    db: AsyncSession,
    resolution: RecoveryResolution,
    now: Any,
    scan_interval_seconds: int,
    *,
    ignore_schedule: bool,
) -> int | None:
    expected = resolution.attempt_count
    conditions = [
        RecoveryResolution.id == resolution.id,
        RecoveryResolution.machine_status == "RECOVERY_PENDING",
        RecoveryResolution.attempt_count == expected,
        RecoveryResolution.attempt_count < RecoveryResolution.max_attempts,
        or_(
            RecoveryResolution.recovery_deadline.is_(None),
            RecoveryResolution.recovery_deadline > now,
        ),
    ]
    if not ignore_schedule:
        conditions.append(
            or_(
                RecoveryResolution.next_attempt_at.is_(None),
                RecoveryResolution.next_attempt_at <= now,
            )
        )
    attempt_no = expected + 1
    request_id = f"SIM-{resolution.id}-{resolution.group_version}-{attempt_no}"
    result = await db.execute(
        update(RecoveryResolution)
        .where(*conditions)
        .values(
            attempt_count=attempt_no,
            last_attempt_at=now,
            next_attempt_at=now + timedelta(seconds=scan_interval_seconds),
            recovery_request_id=request_id,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        return None
    resolution.attempt_count = attempt_no
    resolution.last_attempt_at = now
    resolution.next_attempt_at = now + timedelta(seconds=scan_interval_seconds)
    resolution.recovery_request_id = request_id
    return attempt_no


async def process_recovery_cycle(
    db: AsyncSession,
    run_id: int | None = None,
    *,
    exhaust: bool = False,
    commit: bool = True,
    recovery_gateway: FlightPlanRecoveryGateway | None = None,
) -> dict[str, int]:
    run, _, policy, resolutions = await ensure_run_resolutions(db, run_id, commit=False)
    config = DEFAULT_RECOVERY_CONFIG | dict(policy.config or {})
    plans = list(
        (await db.execute(select(FlightPlan).where(FlightPlan.batch_id == run.batch_id))).scalars()
    )
    groups = {
        group.id: group
        for group in (
            await db.execute(
                select(FlightGroup)
                .where(FlightGroup.run_id == run.id)
                .options(selectinload(FlightGroup.nodes).selectinload(GroupNode.node))
            )
        ).scalars()
    }
    counts = {"attempted": 0, "recovered": 0, "finalized_unassigned": 0}
    now = utcnow()
    gateway = recovery_gateway or PreviewOnlyFlightPlanRecoveryGateway()
    for resolution in resolutions:
        if resolution.machine_status != "RECOVERY_PENDING":
            continue
        group = groups[resolution.group_id]
        expired = bool(resolution.recovery_deadline and resolution.recovery_deadline <= now)
        if expired:
            attempts_to_run = 0
        elif resolution.next_attempt_at and resolution.next_attempt_at > now:
            continue
        else:
            attempts_to_run = resolution.max_attempts - resolution.attempt_count if exhaust else 1
        for _ in range(max(0, attempts_to_run)):
            attempt_no = await _claim_recovery_attempt(
                db,
                resolution,
                now,
                int(config["terminal_scan_interval_seconds"]),
                ignore_schedule=exhaust,
            )
            if attempt_no is None:
                break
            counts["attempted"] += 1
            request_id = f"SIM-{resolution.id}-{resolution.group_version}-{attempt_no}"
            acdm_reference = (group.lineage or {}).get("acdm_reference") or {}
            flight_numbers = sorted(
                {
                    *(str(acdm_reference.get("flight_no") or "").upper(),),
                    *(
                        (member.node.reported_flight_no or "").upper()
                        for member in group.nodes
                        if member.node.reported_flight_no
                    ),
                }
                - {""}
            )
            response = await gateway.request_plan_ids(
                airport_code="XIY",
                stand=group.stand,
                window_start=resolution.request_window_start,
                window_end=resolution.request_window_end,
                flight_numbers=flight_numbers,
                request_id=request_id,
            )
            response_plan_ids = set(response.get("plan_ids") or [])
            response_plans = [plan for plan in plans if plan.id in response_plan_ids]
            matched_plan = _recovery_plan(
                group,
                response_plans,
                resolution.request_window_start,
                resolution.request_window_end,
            )
            db.add(
                RecoveryAttempt(
                    resolution_id=resolution.id,
                    attempt_no=attempt_no,
                    request_id=request_id,
                    request_window_start=resolution.request_window_start,
                    request_window_end=resolution.request_window_end,
                    response_flight_count=len(response_plans),
                    status=(
                        "MATCHED"
                        if matched_plan
                        else "NO_MATCH"
                        if response.get("received")
                        else "NO_RESPONSE"
                    ),
                    candidates_before=resolution.candidate_summary or [],
                    candidates_after=(
                        [{"flight_plan_id": matched_plan.id, "score": 100}] if matched_plan else []
                    ),
                )
            )
            resolution.response_flight_count = len(response_plans)
            if matched_plan:
                group.assigned_flight_id = matched_plan.id
                group.assignment_status = "MATCHED_RECOVERED"
                resolution.machine_status = "MATCHED_RECOVERED"
                resolution.reason_code = "PLAN_RECOVERED"
                resolution.outbound_policy = "SEND_MATCHED_ONLY"
                resolution.outbox_status = "PENDING"
                resolution.finalized_at = now
                counts["recovered"] += 1
                break
        if resolution.machine_status == "RECOVERY_PENDING" and (
            resolution.attempt_count >= resolution.max_attempts
            or (resolution.recovery_deadline and resolution.recovery_deadline <= now)
        ):
            resolution.machine_status = "UNASSIGNED_FINAL"
            resolution.reason_code = "RECOVERY_EXHAUSTED"
            resolution.outbound_policy, resolution.outbox_status = outbound_state(
                "UNASSIGNED_FINAL", bool(config["temporary_group_send_enabled"])
            )
            resolution.finalized_at = now
            counts["finalized_unassigned"] += 1
        timeline = list(resolution.status_timeline or [])
        timeline.append(
            {
                "status": resolution.machine_status,
                "at": now.isoformat(),
                "reason": resolution.reason_code,
            }
        )
        resolution.status_timeline = timeline
        await db.flush()
        await _replace_terminal_records(db, [(resolution, group)])
    if commit:
        await db.commit()
    else:
        await db.flush()
    return counts


async def pending_recovery_run_ids(db: AsyncSession) -> list[int]:
    return list(
        (
            await db.execute(
                select(FlightGroup.run_id)
                .join(RecoveryResolution, RecoveryResolution.group_id == FlightGroup.id)
                .where(RecoveryResolution.machine_status == "RECOVERY_PENDING")
                .distinct()
                .order_by(FlightGroup.run_id)
            )
        ).scalars()
    )


async def process_delivery_outbox(
    db: AsyncSession,
    *,
    commit: bool = True,
    outbound_gateway: OutboundGateway | None = None,
) -> dict[str, int]:
    rows = (
        await db.execute(
            select(RecoveryDelivery, RecoveryResolution)
            .join(RecoveryResolution, RecoveryResolution.id == RecoveryDelivery.resolution_id)
            .where(RecoveryDelivery.outbox_status == "PENDING")
        )
    ).all()
    result = {"sent": 0, "previewed": 0, "dead": 0}
    gateway = outbound_gateway or PreviewOnlyOutboundGateway()
    for delivery, resolution in rows:
        if delivery.payload:
            response = await gateway.send_group(delivery.payload)
            if response.get("sent") is True:
                delivery.outbox_status = "SENT"
                delivery.sent_at = utcnow()
                resolution.outbox_status = "SENT"
                result["sent"] += 1
            elif response.get("mode") == "preview":
                delivery.outbox_status = "PREVIEWED"
                resolution.outbox_status = "PREVIEWED"
                result["previewed"] += 1
            else:
                delivery.outbox_status = "DEAD"
                resolution.outbox_status = "DEAD"
                result["dead"] += 1
        else:
            delivery.outbox_status = "DEAD"
            resolution.outbox_status = "DEAD"
            result["dead"] += 1
    if commit:
        await db.commit()
    else:
        await db.flush()
    return result


async def recovery_attempts(db: AsyncSession, resolution_id: int) -> list[RecoveryAttempt]:
    return list(
        (
            await db.execute(
                select(RecoveryAttempt)
                .where(RecoveryAttempt.resolution_id == resolution_id)
                .order_by(RecoveryAttempt.attempt_no)
            )
        ).scalars()
    )


async def next_policy_version(
    db: AsyncSession, airport_code: str, tenant_code: str, destination: str
) -> int:
    current = await db.scalar(
        select(func.max(RecoveryPolicy.version)).where(
            RecoveryPolicy.airport_code == airport_code,
            RecoveryPolicy.tenant_code == tenant_code,
            RecoveryPolicy.destination == destination,
        )
    )
    return int(current or 0) + 1


async def evaluate_policy_replay(
    db: AsyncSession,
    run_id: int,
    config: dict[str, Any],
    historical_regressions: int,
) -> dict[str, Any]:
    run = await db.get(SimulationRun, run_id)
    if not run:
        raise LookupError("运行不存在")
    groups = list(
        (
            await db.execute(
                select(FlightGroup)
                .where(FlightGroup.run_id == run.id, FlightGroup.assignment_status != "SUPERSEDED")
                .options(selectinload(FlightGroup.nodes).selectinload(GroupNode.node))
            )
        ).scalars()
    )
    plans = list(
        (await db.execute(select(FlightPlan).where(FlightPlan.batch_id == run.batch_id))).scalars()
    )
    counts: dict[str, int] = {}
    for group in groups:
        status, _ = machine_state(group, config)
        if status == "RECOVERY_PENDING":
            status = "UNASSIGNED_FINAL"
        counts[status] = counts.get(status, 0) + 1
    total = len(groups) or 1
    unassigned_rate = counts.get("UNASSIGNED_FINAL", 0) / total
    data_error_rate = counts.get("DATA_ERROR", 0) / total
    pending_groups = sum(machine_state(group, config)[0] == "RECOVERY_PENDING" for group in groups)
    scan_seconds = int(config["terminal_scan_interval_seconds"])
    deadline_seconds = int(config["recovery_deadline_minutes"]) * 60
    max_attempts = int(config["max_attempts"])
    retries_fit_deadline = max_attempts * scan_seconds <= deadline_seconds
    scan_cycles_before_deadline = math.ceil(deadline_seconds / scan_seconds)
    gate_passed = (
        bool(run.metrics.get("node_conservation"))
        and historical_regressions == 0
        and unassigned_rate <= float(config["max_unassigned_rate"])
        and data_error_rate <= float(config["max_data_error_rate"])
        and retries_fit_deadline
    )
    config_digest = hashlib.sha256(
        json.dumps(config, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return {
        "run_id": run.id,
        "group_count": len(groups),
        "status_counts": counts,
        "node_conservation": bool(run.metrics.get("node_conservation")),
        "historical_regressions": historical_regressions,
        "unassigned_rate": round(unassigned_rate, 6),
        "data_error_rate": round(data_error_rate, 6),
        "config_digest": config_digest,
        "recovery_execution": {
            "gateway_mode": "preview_no_response",
            "pending_groups": pending_groups,
            "attempts_per_group": max_attempts,
            "simulated_attempt_count": pending_groups * max_attempts,
            "scan_interval_seconds": scan_seconds,
            "deadline_seconds": deadline_seconds,
            "scan_cycles_before_deadline": scan_cycles_before_deadline,
            "retries_fit_deadline": retries_fit_deadline,
            "request_window_before_minutes": int(config["request_window_before_minutes"]),
            "request_window_after_minutes": int(config["request_window_after_minutes"]),
            "outbox_max_wait_seconds": int(config["outbox_max_wait_seconds"]),
        },
        "gate_passed": gate_passed,
    }
