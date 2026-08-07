from __future__ import annotations

from datetime import datetime
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.engine import (
    AcdmReferenceInput,
    AppearanceInput,
    GroupResult,
    NodeInput,
    PlanInput,
    run_strategy,
    summarize,
)
from app.models import (
    AppearanceFeature,
    AcdmReferenceFeature,
    Batch,
    FlightGroup,
    FlightPlan,
    GroupNode,
    MatchCandidate,
    NodeEvent,
    Review,
    RecoveryDelivery,
    SimulationRun,
    StrategyVersion,
    utcnow,
)


ARRIVAL_EVENTS = {
    "AircraftStart",
    "GuideCarStart",
    "GuideCarEnd",
    "AircraftEntry",
    "PlaceChockBegin",
    "PlaceChockEnd",
    "AccessCorridorBridgeBegin",
    "AccessCorridorBridge",
    "OpenCabinDoor",
    "OpenCargoDoor",
    "FirstPieceBaggage",
}

DEPARTURE_EVENTS = {
    "CloseCargoDoor",
    "CloseCabinDoor",
    "LadderCarStartLeave",
    "LadderCarLeave",
    "RemoveCorridorBridgeBegin",
    "RemoveCorridorBridge",
    "RemoveWheelGearStart",
    "RemoveWheelGearEnd",
    "TractorInPosition",
    "TowShow",
    "TowArrival",
    "TowEnd",
    "AircraftLeave",
    "AircraftBeginsTaxi",
}


def node_phase(event_type: str) -> str:
    if event_type in ARRIVAL_EVENTS:
        return "ARRIVAL"
    if event_type in DEPARTURE_EVENTS:
        return "DEPARTURE"
    return "TURNAROUND"


def _plan_input(plan: FlightPlan) -> PlanInput:
    return PlanInput(
        id=plan.id,
        flight_key=plan.flight_key,
        safeguard_code=plan.safeguard_code,
        inbound_flight_no=plan.inbound_flight_no,
        outbound_flight_no=plan.outbound_flight_no,
        stand=plan.stand,
        plan_start=plan.plan_start,
        plan_end=plan.plan_end,
        airline=plan.airline,
        aircraft_type=plan.aircraft_type,
        aircraft_no=plan.aircraft_no,
        issue_tags=tuple(plan.issue_tags or []),
    )


def _node_input(node: NodeEvent) -> NodeInput:
    return NodeInput(
        id=node.id,
        source_type=node.source_type,
        event_type=node.event_type,
        event_time=node.event_time,
        stand=node.stand,
        reported_flight_no=node.reported_flight_no,
        is_anomaly=node.is_anomaly,
    )


async def execute_run(db: AsyncSession, batch: Batch, strategy: StrategyVersion) -> SimulationRun:
    run = SimulationRun(
        batch_id=batch.id,
        strategy_version_id=strategy.id,
        status="running",
        metrics={},
    )
    db.add(run)
    await db.flush()

    plans = list(
        (await db.execute(select(FlightPlan).where(FlightPlan.batch_id == batch.id))).scalars()
    )
    nodes = list(
        (await db.execute(select(NodeEvent).where(NodeEvent.batch_id == batch.id))).scalars()
    )
    features = list(
        (
            await db.execute(
                select(AppearanceFeature)
                .where(AppearanceFeature.batch_id == batch.id)
                .order_by(AppearanceFeature.created_at)
            )
        ).scalars()
    )
    latest_features: dict[str, AppearanceFeature] = {}
    for feature in features:
        latest_features[feature.temporary_code] = feature
    acdm_features = list(
        (
            await db.execute(
                select(AcdmReferenceFeature)
                .where(AcdmReferenceFeature.batch_id == batch.id)
                .order_by(AcdmReferenceFeature.created_at)
            )
        ).scalars()
    )
    latest_acdm: dict[str, AcdmReferenceFeature] = {}
    for feature in acdm_features:
        latest_acdm[feature.temporary_code] = feature

    review_rows = (
        await db.execute(
            select(Review, FlightGroup.temporary_code)
            .join(FlightGroup, FlightGroup.id == Review.group_id)
            .join(SimulationRun, SimulationRun.id == FlightGroup.run_id)
            .where(SimulationRun.batch_id == batch.id)
            .where(Review.expected_assignment_status.is_not(None))
            .where(Review.expected_assignment_status.not_in(("NEEDS_REVIEW", "SUPERSEDED")))
            .order_by(Review.id)
        )
    ).all()
    protected_group_codes: set[str] = set()
    protected_node_ids: set[int] = set()
    sent_groups = list(
        (
            await db.execute(
                select(FlightGroup)
                .join(RecoveryDelivery, RecoveryDelivery.group_id == FlightGroup.id)
                .join(SimulationRun, SimulationRun.id == FlightGroup.run_id)
                .where(SimulationRun.batch_id == batch.id)
                .where(RecoveryDelivery.outbox_status.in_(("SENT", "ALREADY_SENT")))
                .options(selectinload(FlightGroup.nodes))
                .order_by(FlightGroup.id.desc())
            )
        ).scalars()
    )
    immutable_groups: list[GroupResult] = []
    immutable_node_ids: set[int] = set()
    for sent_group in sent_groups:
        member_ids = [
            member.node_id for member in sorted(sent_group.nodes, key=lambda item: item.order_index)
        ]
        member_set = set(member_ids)
        if not member_set or member_set <= immutable_node_ids:
            continue
        if member_set & immutable_node_ids:
            raise RuntimeError("已发送保障组的节点归属发生交叉，停止重跑以避免重复发送")
        immutable_node_ids.update(member_set)
        protected_group_codes.add(sent_group.temporary_code)
        protected_node_ids.update(member_set)
        immutable_groups.append(
            GroupResult(
                temporary_code=sent_group.temporary_code,
                stand=sent_group.stand,
                observed_start=sent_group.observed_start,
                observed_end=sent_group.observed_end,
                node_ids=member_ids,
                assignment_status=sent_group.assignment_status,
                assigned_flight_id=sent_group.assigned_flight_id,
                confidence=sent_group.confidence,
                margin=sent_group.margin,
                issue_tags=list(sent_group.issue_tags or []),
                lineage=dict(sent_group.lineage or {}),
            )
        )

    results = run_strategy(
        airport_code=batch.airport_code,
        plans=[_plan_input(plan) for plan in plans],
        nodes=[_node_input(node) for node in nodes],
        appearances=[
            AppearanceInput(
                temporary_code=item.temporary_code,
                airline=item.airline,
                aircraft_type=item.aircraft_type,
                confidence=item.confidence,
                aircraft_registration=item.aircraft_registration,
                registration_confidence=item.registration_confidence,
            )
            for item in latest_features.values()
        ],
        acdm_references=[
            AcdmReferenceInput(
                temporary_code=item.temporary_code,
                flight_no=item.flight_no,
                aircraft_entry_time=datetime.fromisoformat(
                    item.node_payload["aircraft_entry_time"]
                ),
                chock_on_time=(
                    datetime.fromisoformat(item.node_payload["chock_on_time"])
                    if item.node_payload.get("chock_on_time")
                    else None
                ),
                stand_release_time=(
                    datetime.fromisoformat(item.node_payload["stand_release_time"])
                    if item.node_payload.get("stand_release_time")
                    else None
                ),
            )
            for item in latest_acdm.values()
        ],
        config=strategy.config,
        protected_group_codes=protected_group_codes,
        protected_node_ids=protected_node_ids,
        immutable_groups=immutable_groups,
    )
    reviewed_group_ids = {review.group_id for review, _ in review_rows}
    reviewed_nodes: dict[int, set[int]] = {}
    if reviewed_group_ids:
        for group_id, node_id in (
            await db.execute(
                select(GroupNode.group_id, GroupNode.node_id).where(
                    GroupNode.group_id.in_(reviewed_group_ids)
                )
            )
        ).all():
            reviewed_nodes.setdefault(group_id, set()).add(node_id)
    _replay_structural_reviews(
        results,
        [
            {
                "review_id": review.id,
                "temporary_code": temporary_code,
                "node_ids": reviewed_nodes.get(review.group_id, set()),
                "expected_flight_id": review.expected_flight_id,
                "expected_flight_no": review.expected_flight_no,
                "expected_assignment_status": review.expected_assignment_status,
            }
            for review, temporary_code in review_rows
        ],
    )

    for result in results:
        group = FlightGroup(
            run_id=run.id,
            temporary_code=result.temporary_code,
            stand=result.stand,
            observed_start=result.observed_start,
            observed_end=result.observed_end,
            assignment_status=result.assignment_status,
            assigned_flight_id=result.assigned_flight_id,
            confidence=result.confidence,
            margin=result.margin,
            issue_tags=result.issue_tags,
            lineage={"kind": "strategy_run", **result.lineage},
        )
        db.add(group)
        await db.flush()
        for order_index, node_id in enumerate(result.node_ids):
            db.add(GroupNode(group_id=group.id, node_id=node_id, order_index=order_index))
        for rank, candidate in enumerate(result.candidates, start=1):
            db.add(
                MatchCandidate(
                    group_id=group.id,
                    flight_plan_id=candidate.flight_plan_id,
                    rank=rank,
                    score=candidate.score,
                    score_breakdown=candidate.breakdown,
                    excluded_reason=candidate.excluded_reason,
                    selected=candidate.selected,
                )
            )

    run.metrics = summarize(results, len(nodes))
    run.status = "completed"
    run.completed_at = utcnow()
    await db.flush()
    from app.recovery import process_delivery_outbox, process_recovery_cycle

    await process_recovery_cycle(db, run.id, commit=False)
    await process_delivery_outbox(db, commit=False)
    await db.commit()
    await db.refresh(run)
    return run


def _replay_structural_reviews(
    results: list[GroupResult],
    expectations: list[dict],
) -> None:
    current_nodes_by_code = {
        result.temporary_code: frozenset(result.node_ids) for result in results
    }
    latest_by_nodes: dict[frozenset[int], dict] = {}
    for expectation in expectations:
        node_ids = frozenset(expectation["node_ids"])
        if not node_ids:
            continue
        if current_nodes_by_code.get(expectation["temporary_code"]) == node_ids:
            latest_by_nodes.pop(node_ids, None)
            continue
        latest_by_nodes[node_ids] = expectation

    for result in results:
        if result.lineage.get("immutable_sent_replay"):
            continue
        expectation = latest_by_nodes.get(frozenset(result.node_ids))
        if not expectation:
            continue
        result.assigned_flight_id = expectation["expected_flight_id"]
        result.assignment_status = expectation["expected_assignment_status"]
        result.confidence = 1.0
        for candidate in result.candidates:
            candidate.selected = candidate.flight_plan_id == result.assigned_flight_id
        result.lineage["structural_review_replay"] = {
            "review_id": expectation["review_id"],
            "source_temporary_code": expectation["temporary_code"],
            "matched_by": "exact_node_set",
            "expected_flight_id": expectation["expected_flight_id"],
            "expected_flight_no": expectation["expected_flight_no"],
            "expected_assignment_status": expectation["expected_assignment_status"],
        }


async def latest_run(db: AsyncSession, batch_id: int | None = None) -> SimulationRun | None:
    stmt = select(SimulationRun).order_by(SimulationRun.id.desc()).limit(1)
    if batch_id:
        stmt = stmt.where(SimulationRun.batch_id == batch_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def group_detail(db: AsyncSession, group_id: int) -> FlightGroup | None:
    return (
        await db.execute(
            select(FlightGroup)
            .where(FlightGroup.id == group_id)
            .options(
                selectinload(FlightGroup.nodes).selectinload(GroupNode.node),
                selectinload(FlightGroup.candidates).selectinload(MatchCandidate.flight_plan),
                selectinload(FlightGroup.reviews),
                selectinload(FlightGroup.cluster_reviews),
            )
        )
    ).scalar_one_or_none()


async def association_groups(db: AsyncSession, run_id: int) -> list[dict]:
    groups = list(
        (
            await db.execute(
                select(FlightGroup)
                .where(FlightGroup.run_id == run_id)
                .where(FlightGroup.assignment_status != "SUPERSEDED")
                .options(
                    selectinload(FlightGroup.nodes).selectinload(GroupNode.node),
                    selectinload(FlightGroup.candidates).selectinload(MatchCandidate.flight_plan),
                )
                .order_by(FlightGroup.observed_start)
            )
        ).scalars()
    )
    output = []
    for group in groups:
        assigned = next(
            (
                candidate.flight_plan
                for candidate in group.candidates
                if candidate.flight_plan_id == group.assigned_flight_id
            ),
            None,
        )
        candidate = assigned or next(
            (
                item.flight_plan
                for item in sorted(group.candidates, key=lambda value: value.rank)
                if not item.excluded_reason
            ),
            None,
        )
        acdm_lineage = (group.lineage or {}).get("acdm_reference", {})
        acdm_flight_no = acdm_lineage.get("flight_no")
        occupancy = (group.lineage or {}).get("stand_occupancy", {})
        occupancy_start = datetime.fromisoformat(
            occupancy.get("start_time", group.observed_start.isoformat())
        )
        occupancy_end = datetime.fromisoformat(
            occupancy.get("end_time", group.observed_end.isoformat())
        )
        occupancy_start_source = occupancy.get("start_source", "observed_group_start")
        occupancy_end_source = occupancy.get("end_source", "observed_group_end")
        overrun = 0
        if candidate and candidate.plan_end:
            overrun = max(
                0,
                round((occupancy_end - candidate.plan_end).total_seconds() / 60),
            )
        nodes = []
        for item in sorted(group.nodes, key=lambda value: value.order_index):
            phase = node_phase(item.node.event_type)
            attributed_flight = None
            if candidate:
                attributed_flight = (
                    candidate.inbound_flight_no
                    if phase == "ARRIVAL"
                    else candidate.outbound_flight_no
                )
            elif acdm_flight_no:
                attributed_flight = acdm_flight_no
            nodes.append(
                {
                    "id": item.node.id,
                    "source_type": item.node.source_type,
                    "event_type": item.node.event_type,
                    "event_time": item.node.event_time,
                    "stand": item.node.stand,
                    "reported_flight_no": item.node.reported_flight_no,
                    "safeguard_code": item.node.safeguard_code,
                    "is_anomaly": item.node.is_anomaly,
                    "phase": phase,
                    "attributed_flight_no": attributed_flight,
                }
            )
        output.append(
            {
                "group_id": group.id,
                "temporary_code": group.temporary_code,
                "service_date": (
                    candidate.plan_start.date().isoformat()
                    if candidate and candidate.plan_start
                    else group.observed_start.date().isoformat()
                ),
                "assignment_status": group.assignment_status,
                "safeguard_code": candidate.safeguard_code if candidate else None,
                "stand": group.stand,
                "aircraft_no": candidate.aircraft_no if candidate else None,
                "aircraft_type": candidate.aircraft_type if candidate else None,
                "inbound_flight_no": (candidate.inbound_flight_no if candidate else acdm_flight_no),
                "outbound_flight_no": candidate.outbound_flight_no if candidate else None,
                "observed_start": group.observed_start,
                "observed_end": group.observed_end,
                "occupancy_start": occupancy_start,
                "occupancy_end": occupancy_end,
                "occupancy_start_source": occupancy_start_source,
                "occupancy_end_source": occupancy_end_source,
                "plan_start": candidate.plan_start if candidate else None,
                "plan_end": candidate.plan_end if candidate else None,
                "overrun_minutes": overrun,
                "issue_tags": group.issue_tags or [],
                "node_count": len(nodes),
                "nodes": nodes,
            }
        )
    return output


async def review_counts(db: AsyncSession, run_id: int) -> dict[str, object]:
    run = await db.get(SimulationRun, run_id)
    if not run:
        return {
            "required": 0,
            "completed": 0,
            "incorrect": 0,
            "regressions": 0,
            "regression_cases": [],
        }
    groups = list(
        (
            await db.execute(
                select(FlightGroup)
                .where(FlightGroup.run_id == run_id)
                .where(FlightGroup.assignment_status != "SUPERSEDED")
                .options(
                    selectinload(FlightGroup.reviews),
                    selectinload(FlightGroup.nodes),
                )
            )
        ).scalars()
    )
    required = [
        group for group in groups if group.issue_tags or group.assignment_status != "MATCHED"
    ]
    latest_reviews = []
    completed_group_ids = set()
    for group in required:
        final_reviews = [review for review in group.reviews if _is_final_review(review)]
        if final_reviews:
            latest_reviews.append(final_reviews[-1])
            completed_group_ids.add(group.id)
    historical_rows = (
        await db.execute(
            select(Review, FlightGroup)
            .join(FlightGroup, FlightGroup.id == Review.group_id)
            .join(SimulationRun, SimulationRun.id == FlightGroup.run_id)
            .where(SimulationRun.batch_id == run.batch_id)
            .where(SimulationRun.id != run_id)
            .where(Review.expected_assignment_status.is_not(None))
            .where(Review.expected_assignment_status.not_in(("NEEDS_REVIEW", "SUPERSEDED")))
            .options(selectinload(FlightGroup.nodes))
            .order_by(Review.id)
        )
    ).all()
    expected_by_code: dict[str, tuple[Review, FlightGroup, frozenset[int]]] = {}
    for review, historical_group in historical_rows:
        expected_by_code[historical_group.temporary_code] = (
            review,
            historical_group,
            frozenset(node.node_id for node in historical_group.nodes),
        )
    current_by_nodes = {
        frozenset(node.node_id for node in group.nodes): group for group in groups if group.nodes
    }
    regressions = 0
    regression_cases: list[dict[str, object]] = []
    for temporary_code, (review, historical_group, historical_node_ids) in expected_by_code.items():
        current = current_by_nodes.get(historical_node_ids)
        matches_expected = False
        if not current:
            regressions += 1
        elif review.expected_flight_id is not None:
            matches_expected = current.assigned_flight_id == review.expected_flight_id
            regressions += int(not matches_expected)
        elif review.expected_flight_no:
            current_numbers: set[str] = set()
            if current.assigned_flight_id:
                plan = await db.get(FlightPlan, current.assigned_flight_id)
                if plan:
                    current_numbers = {
                        value.upper()
                        for value in (plan.inbound_flight_no, plan.outbound_flight_no)
                        if value
                    }
            elif current.assignment_status == "MATCHED_REFERENCE_NO_PLAN":
                acdm_flight_no = (current.lineage or {}).get("acdm_reference", {}).get("flight_no")
                if acdm_flight_no:
                    current_numbers.add(acdm_flight_no.upper())
            matches_expected = review.expected_flight_no.upper() in current_numbers
            regressions += int(not matches_expected)
        else:
            matches_expected = current.assignment_status == review.expected_assignment_status
            regressions += int(not matches_expected)
        if current and matches_expected:
            completed_group_ids.add(current.id)

        expected_plan = (
            await db.get(FlightPlan, review.expected_flight_id)
            if review.expected_flight_id is not None
            else None
        )
        current_plan = (
            await db.get(FlightPlan, current.assigned_flight_id)
            if current and current.assigned_flight_id is not None
            else None
        )
        expected_result = review.expected_flight_no or _flight_plan_label(expected_plan)
        if not expected_result:
            expected_result = review.expected_assignment_status or "未定义"
        current_result = _flight_plan_label(current_plan)
        if not current_result and current:
            current_result = (current.lineage or {}).get("acdm_reference", {}).get(
                "flight_no"
            ) or current.assignment_status
        regression_cases.append(
            {
                "temporary_code": current.temporary_code if current else temporary_code,
                "source_run_id": historical_group.run_id,
                "current_group_id": current.id if current else None,
                "stand": current.stand if current else historical_group.stand,
                "expected_result": expected_result,
                "current_result": current_result or "保障组缺失",
                "passed": matches_expected,
            }
        )
    return {
        "required": len(required),
        "completed": len(completed_group_ids & {group.id for group in required}),
        "incorrect": sum(review.verdict == "incorrect" for review in latest_reviews),
        "regressions": regressions,
        "regression_cases": regression_cases,
    }


def _flight_plan_label(plan: FlightPlan | None) -> str | None:
    if not plan:
        return None
    numbers = [value for value in (plan.inbound_flight_no, plan.outbound_flight_no) if value]
    return " / ".join(dict.fromkeys(numbers)) or None


def _is_final_review(review: Review) -> bool:
    return review.expected_assignment_status not in {None, "NEEDS_REVIEW", "SUPERSEDED"}


async def split_group(db: AsyncSession, group_id: int, split_node_id: int) -> list[FlightGroup]:
    original = await group_detail(db, group_id)
    if not original:
        raise ValueError("分组不存在")
    ordered = sorted(original.nodes, key=lambda item: item.order_index)
    split_index = next((i for i, item in enumerate(ordered) if item.node_id == split_node_id), -1)
    if split_index <= 0 or split_index >= len(ordered):
        raise ValueError("拆分节点必须位于分组中间")
    chunks = [ordered[:split_index], ordered[split_index:]]
    created = []
    for suffix, chunk in zip(("A", "B"), chunks):
        times = [item.node.event_time for item in chunk if item.node.event_time]
        group = FlightGroup(
            run_id=original.run_id,
            temporary_code=f"{original.temporary_code}-{suffix}",
            stand=original.stand,
            observed_start=min(times),
            observed_end=max(times),
            assignment_status="UNASSIGNED",
            confidence=0.75,
            margin=0,
            issue_tags=["MANUAL_SPLIT"],
            lineage={"split_from": original.id},
        )
        db.add(group)
        await db.flush()
        for index, item in enumerate(chunk):
            db.add(GroupNode(group_id=group.id, node_id=item.node_id, order_index=index))
        created.append(group)
    await db.execute(delete(GroupNode).where(GroupNode.group_id == original.id))
    original.assignment_status = "SUPERSEDED"
    original.lineage = {**(original.lineage or {}), "split_into": [group.id for group in created]}
    db.add(
        Review(
            group_id=original.id,
            verdict="incorrect",
            error_type="grouping_error",
            comment=f"人工在节点 {split_node_id} 处拆分",
        )
    )
    await db.commit()
    from app.recovery import ensure_run_resolutions

    await ensure_run_resolutions(db, original.run_id)
    return created


async def merge_groups(db: AsyncSession, group_ids: list[int]) -> FlightGroup:
    if len(group_ids) < 2:
        raise ValueError("至少选择两个分组")
    groups = [await group_detail(db, group_id) for group_id in group_ids]
    if any(group is None for group in groups):
        raise ValueError("存在无效分组")
    valid_groups = [group for group in groups if group]
    if (
        len({group.run_id for group in valid_groups}) != 1
        or len({group.stand for group in valid_groups}) != 1
    ):
        raise ValueError("只能合并同一次运行、同一机位的分组")
    all_nodes = sorted(
        [item for group in valid_groups for item in group.nodes],
        key=lambda item: item.node.event_time or datetime.min,
    )
    times = [item.node.event_time for item in all_nodes if item.node.event_time]
    merged = FlightGroup(
        run_id=valid_groups[0].run_id,
        temporary_code=f"{valid_groups[0].temporary_code}-M",
        stand=valid_groups[0].stand,
        observed_start=min(times),
        observed_end=max(times),
        assignment_status="UNASSIGNED",
        confidence=0.75,
        margin=0,
        issue_tags=["MANUAL_MERGE"],
        lineage={"merged_from": group_ids},
    )
    db.add(merged)
    await db.flush()
    for index, item in enumerate(all_nodes):
        db.add(GroupNode(group_id=merged.id, node_id=item.node_id, order_index=index))
    for group in valid_groups:
        await db.execute(delete(GroupNode).where(GroupNode.group_id == group.id))
        group.assignment_status = "SUPERSEDED"
        group.lineage = {**(group.lineage or {}), "merged_into": merged.id}
    await db.commit()
    from app.recovery import ensure_run_resolutions

    await ensure_run_resolutions(db, merged.run_id)
    await db.refresh(merged)
    return merged
