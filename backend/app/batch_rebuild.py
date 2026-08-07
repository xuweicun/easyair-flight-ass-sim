from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.importers import normalize_flight_plan_rows
from app.models import (
    AcdmReferenceFeature,
    AppearanceFeature,
    Batch,
    FlightGroup,
    FlightPlan,
    NodeEvent,
    Review,
    SimulationRun,
    StrategyVersion,
    ValidationSample,
)
from app.services import execute_run


NORMALIZATION_VERSION = "physical-occupancy-v2"


def _raw_plan_rows(plans: list[FlightPlan]) -> list[dict[str, Any]]:
    rows_by_number: dict[int, dict[str, Any]] = {}
    for plan in plans:
        for row in (plan.raw_payload or {}).get("rows", []):
            row_number = row.get("__row_number__")
            if not isinstance(row_number, int):
                raise ValueError(f"计划 {plan.id} 缺少原始行号，无法无损重建")
            existing = rows_by_number.get(row_number)
            if existing is not None and existing != row:
                raise ValueError(f"原始计划第 {row_number} 行存在冲突副本")
            rows_by_number[row_number] = deepcopy(row)
    return [rows_by_number[number] for number in sorted(rows_by_number)]


def _plan_numbers(plan: FlightPlan) -> set[str]:
    return {value.upper() for value in (plan.inbound_flight_no, plan.outbound_flight_no) if value}


def _map_plan(
    old_plan: FlightPlan | None,
    flight_no: str | None,
    new_plans: list[FlightPlan],
) -> FlightPlan | None:
    normalized_number = flight_no.upper() if flight_no else None
    candidates = [
        plan
        for plan in new_plans
        if normalized_number is None or normalized_number in _plan_numbers(plan)
    ]
    if not candidates:
        return None
    if old_plan is None:
        return candidates[0] if len(candidates) == 1 else None

    def rank(plan: FlightPlan) -> tuple[int, int, int, int, int]:
        return (
            int(plan.stand == old_plan.stand),
            int(bool(plan.aircraft_no) and plan.aircraft_no == old_plan.aircraft_no),
            int(plan.plan_start == old_plan.plan_start),
            int(plan.plan_end == old_plan.plan_end),
            len(_plan_numbers(plan) & _plan_numbers(old_plan)),
        )

    return max(candidates, key=rank)


async def _clone_reference_evidence(
    db: AsyncSession,
    source_batch_id: int,
    target_batch_id: int,
) -> None:
    appearances = list(
        (
            await db.execute(
                select(AppearanceFeature)
                .where(AppearanceFeature.batch_id == source_batch_id)
                .order_by(AppearanceFeature.id)
            )
        ).scalars()
    )
    latest_appearances: dict[str, AppearanceFeature] = {}
    for feature in appearances:
        latest_appearances[feature.temporary_code] = feature
    for feature in latest_appearances.values():
        db.add(
            AppearanceFeature(
                batch_id=target_batch_id,
                temporary_code=feature.temporary_code,
                airline=feature.airline,
                aircraft_type=feature.aircraft_type,
                aircraft_registration=feature.aircraft_registration,
                registration_confidence=feature.registration_confidence,
                confidence=feature.confidence,
                evidence_time=feature.evidence_time,
                source_type=feature.source_type,
            )
        )

    references = list(
        (
            await db.execute(
                select(AcdmReferenceFeature)
                .where(AcdmReferenceFeature.batch_id == source_batch_id)
                .order_by(AcdmReferenceFeature.id)
            )
        ).scalars()
    )
    latest_references: dict[str, AcdmReferenceFeature] = {}
    for feature in references:
        latest_references[feature.temporary_code] = feature
    for feature in latest_references.values():
        db.add(
            AcdmReferenceFeature(
                batch_id=target_batch_id,
                temporary_code=feature.temporary_code,
                flight_no=feature.flight_no,
                node_payload=deepcopy(feature.node_payload),
                source_type=feature.source_type,
            )
        )


async def _clone_validation_state(
    db: AsyncSession,
    source_batch_id: int,
    target_batch_id: int,
    target_run: SimulationRun,
    source_to_target_node: dict[int, int],
) -> dict[str, int]:
    new_groups = list(
        (
            await db.execute(
                select(FlightGroup)
                .where(FlightGroup.run_id == target_run.id)
                .options(selectinload(FlightGroup.nodes))
            )
        ).scalars()
    )
    groups_by_code = {group.temporary_code: group for group in new_groups}
    groups_by_nodes = {
        frozenset(item.node_id for item in group.nodes): group
        for group in new_groups
        if group.nodes
    }

    samples = list(
        (
            await db.execute(
                select(ValidationSample).where(ValidationSample.batch_id == source_batch_id)
            )
        ).scalars()
    )
    copied_samples = 0
    for sample in samples:
        mapped_nodes = frozenset(
            source_to_target_node[node_id]
            for node_id in sample.node_ids or []
            if node_id in source_to_target_node
        )
        group = groups_by_code.get(sample.temporary_code) or groups_by_nodes.get(mapped_nodes)
        if not group:
            continue
        db.add(
            ValidationSample(
                batch_id=target_batch_id,
                temporary_code=group.temporary_code,
                source_run_id=target_run.id,
                node_ids=[
                    item.node_id for item in sorted(group.nodes, key=lambda item: item.order_index)
                ],
                selected_at=sample.selected_at,
            )
        )
        copied_samples += 1

    source_review_rows = (
        await db.execute(
            select(Review, FlightGroup)
            .join(FlightGroup, FlightGroup.id == Review.group_id)
            .join(SimulationRun, SimulationRun.id == FlightGroup.run_id)
            .where(SimulationRun.batch_id == source_batch_id)
            .where(Review.expected_assignment_status.is_not(None))
            .options(selectinload(FlightGroup.nodes))
            .order_by(Review.id)
        )
    ).all()
    latest_reviews: dict[str, tuple[Review, FlightGroup]] = {}
    for review, group in source_review_rows:
        latest_reviews[group.temporary_code] = (review, group)

    new_plans = list(
        (
            await db.execute(select(FlightPlan).where(FlightPlan.batch_id == target_batch_id))
        ).scalars()
    )
    copied_reviews = 0
    for temporary_code, (review, old_group) in latest_reviews.items():
        mapped_nodes = frozenset(
            source_to_target_node[item.node_id]
            for item in old_group.nodes
            if item.node_id in source_to_target_node
        )
        new_group = groups_by_code.get(temporary_code) or groups_by_nodes.get(mapped_nodes)
        if not new_group:
            continue
        old_expected = (
            await db.get(FlightPlan, review.expected_flight_id)
            if review.expected_flight_id
            else None
        )
        expected_plan = _map_plan(old_expected, review.expected_flight_no, new_plans)
        old_correct = (
            await db.get(FlightPlan, review.correct_flight_id) if review.correct_flight_id else None
        )
        correct_plan = _map_plan(old_correct, review.correct_flight_no, new_plans)
        strategy_flight_id = new_group.assigned_flight_id
        strategy_status = new_group.assignment_status
        strategy_plan = await db.get(FlightPlan, strategy_flight_id) if strategy_flight_id else None
        strategy_numbers = _plan_numbers(strategy_plan) if strategy_plan else set()

        if review.expected_flight_id and not expected_plan:
            continue
        new_group.assigned_flight_id = expected_plan.id if expected_plan else None
        new_group.assignment_status = review.expected_assignment_status or strategy_status
        expected_number = review.expected_flight_no.upper() if review.expected_flight_no else None
        new_group.lineage = {
            **(new_group.lineage or {}),
            "latest_review_comparison": {
                "strategy_flight_id": strategy_flight_id,
                "strategy_flight_no": (
                    " / ".join(sorted(strategy_numbers)) if strategy_numbers else None
                ),
                "strategy_status": strategy_status,
                "final_flight_id": new_group.assigned_flight_id,
                "final_flight_no": expected_number,
                "final_status": new_group.assignment_status,
                "strategy_correct": (
                    expected_number in strategy_numbers
                    if expected_number
                    else strategy_flight_id == new_group.assigned_flight_id
                    and strategy_status == new_group.assignment_status
                ),
                "copied_from_batch_id": source_batch_id,
            },
        }
        db.add(
            Review(
                group_id=new_group.id,
                verdict=review.verdict,
                error_type=review.error_type,
                correct_flight_id=correct_plan.id if correct_plan else None,
                correct_flight_no=review.correct_flight_no,
                expected_flight_id=expected_plan.id if expected_plan else None,
                expected_flight_no=expected_number,
                expected_assignment_status=new_group.assignment_status,
                comment=review.comment,
                reviewer=review.reviewer,
                created_at=review.created_at,
            )
        )
        copied_reviews += 1

    await db.commit()
    return {"validation_samples": copied_samples, "reviews": copied_reviews}


async def rebuild_normalized_batch(
    db: AsyncSession,
    source_batch_id: int,
    strategy_id: int | None = None,
) -> tuple[Batch, SimulationRun]:
    source_batch = await db.get(Batch, source_batch_id)
    if not source_batch:
        raise ValueError(f"源批次 {source_batch_id} 不存在")
    existing = (
        await db.execute(select(Batch).where(Batch.id != source_batch_id).order_by(Batch.id.desc()))
    ).scalars()
    for batch in existing:
        if (batch.source_files or {}).get("normalization", {}).get(
            "source_batch_id"
        ) == source_batch_id:
            if (batch.source_files or {}).get("normalization", {}).get(
                "version"
            ) == NORMALIZATION_VERSION:
                run = (
                    await db.execute(
                        select(SimulationRun)
                        .where(SimulationRun.batch_id == batch.id)
                        .order_by(SimulationRun.id.desc())
                        .limit(1)
                    )
                ).scalar_one()
                return batch, run

    source_plans = list(
        (
            await db.execute(select(FlightPlan).where(FlightPlan.batch_id == source_batch_id))
        ).scalars()
    )
    raw_rows = _raw_plan_rows(source_plans)
    normalized_plans = normalize_flight_plan_rows(raw_rows)
    source_nodes = list(
        (
            await db.execute(
                select(NodeEvent)
                .where(NodeEvent.batch_id == source_batch_id)
                .order_by(NodeEvent.id)
            )
        ).scalars()
    )
    merged_count = sum(
        plan["raw_payload"].get("normalization", {}).get("method") == "physical_occupancy"
        for plan in normalized_plans
    )

    batch = Batch(
        name=f"{source_batch.name} · 驻位归一化 v2",
        airport_code=source_batch.airport_code,
        status="ready",
        source_files={
            **deepcopy(source_batch.source_files or {}),
            "normalization": {
                "version": NORMALIZATION_VERSION,
                "source_batch_id": source_batch_id,
            },
        },
        stats={
            "raw_plan_rows": len(raw_rows),
            "source_plan_groups": len(source_plans),
            "plan_groups": len(normalized_plans),
            "merged_occupancy_pairs": merged_count,
            "nodes": len(source_nodes),
        },
    )
    db.add(batch)
    await db.flush()
    new_plans = [FlightPlan(batch_id=batch.id, **plan) for plan in normalized_plans]
    db.add_all(new_plans)

    new_nodes: list[NodeEvent] = []
    for node in source_nodes:
        new_node = NodeEvent(
            batch_id=batch.id,
            source_type=node.source_type,
            source_row_id=node.source_row_id,
            event_type=node.event_type,
            event_time=node.event_time,
            stand=node.stand,
            reported_flight_no=node.reported_flight_no,
            safeguard_code=node.safeguard_code,
            is_anomaly=node.is_anomaly,
            raw_payload=deepcopy(node.raw_payload),
        )
        db.add(new_node)
        new_nodes.append(new_node)
    await db.flush()
    node_mapping = {
        source.id: target.id for source, target in zip(source_nodes, new_nodes, strict=True)
    }
    await _clone_reference_evidence(db, source_batch_id, batch.id)
    await db.commit()

    strategy = await db.get(StrategyVersion, strategy_id) if strategy_id else None
    if strategy is None:
        strategy = (
            await db.execute(select(StrategyVersion).order_by(StrategyVersion.id.desc()).limit(1))
        ).scalar_one()
    run = await execute_run(db, batch, strategy)
    copied = await _clone_validation_state(
        db,
        source_batch_id=source_batch_id,
        target_batch_id=batch.id,
        target_run=run,
        source_to_target_node=node_mapping,
    )
    batch.stats = {**(batch.stats or {}), **copied}
    await db.commit()
    await db.refresh(batch)
    await db.refresh(run)
    return batch, run
