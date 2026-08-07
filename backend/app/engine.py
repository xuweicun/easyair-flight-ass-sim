from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable

from app.registration_similarity import registration_similarity


START_MARKERS = (
    "aircraftstart",
    "guidecarstart",
    "towstart",
    "aircraftentry",
    "aircraftarrival",
    "aircraftinposition",
    "进位",
    "入位",
    "靠桥",
    "牵引车开始",
)
END_MARKERS = (
    "aircraftleave",
    "aircraftbeginstaxi",
    "towend",
    "离位",
    "推出",
    "拖曳结束",
)

DEFAULT_TERMINAL_TAIL_EVENT_POLICY: dict[str, list[str]] = {
    "group_start_events": [
        "AircraftStart",
        "GuideCarStart",
        "TowStart",
        "飞机开始入位",
        "引导车开始",
        "牵引车开始",
    ],
    "aircraft_entry_events": ["AircraftEntry", "飞机入位", "入位"],
    "aircraft_leave_events": ["AircraftLeave", "飞机推出", "推出"],
    "tow_end_events": ["TowEnd", "牵引车结束", "拖曳结束"],
    "allowed_tail_events": [
        "AircraftLeave",
        "AircraftBeginsTaxi",
        "TowEnd",
        "离位",
        "推出",
        "拖曳结束",
        "OpenCargoDoor",
        "CloseCargoDoor",
        "CloseCabinDoor",
        "RemoveCorridorBridgeBegin",
        "RemoveCorridorBridge",
        "RemoveWheelGearStart",
        "RemoveWheelGearEnd",
        "TowArrival",
        "TractorInPosition",
        "TowShow",
    ],
}


DEFAULT_STRATEGY: dict[str, Any] = {
    "idle_gap_minutes": 180,
    "approach_chain_minutes": 30,
    "terminal_tail_reattach_enabled": False,
    "terminal_tail_lookback_minutes": 480,
    "terminal_tail_max_nodes": 3,
    "terminal_tail_event_policy": DEFAULT_TERMINAL_TAIL_EVENT_POLICY,
    "combination_stand_families": ["525"],
    "combination_parent_guard_enabled": False,
    "overnight_bridge_enabled": False,
    "overnight_bridge_max_gap_minutes": 1440,
    "overnight_bridge_plan_iou_threshold": 0.5,
    "open_occupancy_timeout_minutes": 480,
    "window_grace_minutes": 5,
    "sequence_resolution_enabled": False,
    "time_decay_minutes": 180,
    "plan_end_overrun_minutes": 20,
    "candidate_radius_hours": 8,
    "max_plan_hours": 12,
    "hard_reject_plan_hours": 24,
    "valid_plan_year_min": 2020,
    "valid_plan_year_max": 2035,
    "known_year_corrections": {"2076": 2026},
    "exclude_invalid_candidates_from_timeline": True,
    "auto_match_threshold": 70,
    "minimum_margin": 15,
    "appearance_confidence_threshold": 0.75,
    "acdm_time_tolerance_minutes": 10,
    "weights": {
        "stand": 30,
        "time_window": 25,
        "node_semantics": 20,
        "continuity": 15,
        "sequence_order": 40,
        "appearance_airline": 8,
        "appearance_type": 5,
        "appearance_registration": 12,
    },
}


@dataclass(frozen=True)
class PlanInput:
    id: int
    flight_key: str
    safeguard_code: str | None
    inbound_flight_no: str | None
    outbound_flight_no: str | None
    stand: str | None
    plan_start: datetime | None
    plan_end: datetime | None
    airline: str | None = None
    aircraft_type: str | None = None
    aircraft_no: str | None = None
    issue_tags: tuple[str, ...] = ()

    @property
    def flight_numbers(self) -> set[str]:
        return {
            value.upper() for value in (self.inbound_flight_no, self.outbound_flight_no) if value
        }


@dataclass(frozen=True)
class NodeInput:
    id: int
    source_type: str
    event_type: str
    event_time: datetime | None
    stand: str | None
    reported_flight_no: str | None = None
    is_anomaly: bool = False


@dataclass(frozen=True)
class AppearanceInput:
    temporary_code: str
    airline: str | None
    aircraft_type: str | None
    confidence: float
    aircraft_registration: str | None = None
    registration_confidence: float | None = None


@dataclass(frozen=True)
class AcdmReferenceInput:
    temporary_code: str
    flight_no: str
    aircraft_entry_time: datetime
    chock_on_time: datetime | None = None
    stand_release_time: datetime | None = None


@dataclass
class CandidateScore:
    flight_plan_id: int
    score: float
    breakdown: dict[str, float]
    selected: bool = False
    excluded_reason: str | None = None


@dataclass
class GroupResult:
    temporary_code: str
    stand: str
    observed_start: datetime
    observed_end: datetime
    node_ids: list[int]
    assignment_status: str
    assigned_flight_id: int | None
    confidence: float
    margin: float
    issue_tags: list[str] = field(default_factory=list)
    candidates: list[CandidateScore] = field(default_factory=list)
    lineage: dict[str, Any] = field(default_factory=dict)


def _normalized_event(event_type: str) -> str:
    return "".join(event_type.lower().split())


def _event_matches(event_type: str, configured_events: Iterable[str]) -> bool:
    normalized = _normalized_event(event_type)
    return normalized in {_normalized_event(value) for value in configured_events}


def is_start_event(event_type: str) -> bool:
    normalized = _normalized_event(event_type)
    return any(marker in normalized for marker in START_MARKERS)


def is_end_event(event_type: str) -> bool:
    normalized = _normalized_event(event_type)
    return any(marker in normalized for marker in END_MARKERS)


def is_aircraft_entry_event(event_type: str) -> bool:
    normalized = _normalized_event(event_type)
    return normalized == "aircraftentry" or normalized in {"飞机入位", "入位"}


def is_aircraft_leave_event(event_type: str) -> bool:
    normalized = _normalized_event(event_type)
    return normalized == "aircraftleave" or normalized in {"飞机推出", "推出"}


def is_tow_end_event(event_type: str) -> bool:
    normalized = _normalized_event(event_type)
    return normalized == "towend" or normalized in {"牵引车结束", "拖曳结束"}


def is_group_start_event(
    event_type: str,
    configured_events: Iterable[str] = DEFAULT_TERMINAL_TAIL_EVENT_POLICY["group_start_events"],
) -> bool:
    return _event_matches(event_type, configured_events)


def is_terminal_end_event(event_type: str) -> bool:
    return is_aircraft_leave_event(event_type) or is_tow_end_event(event_type)


def is_terminal_tail_event(
    event_type: str,
    configured_events: Iterable[str] = DEFAULT_TERMINAL_TAIL_EVENT_POLICY["allowed_tail_events"],
) -> bool:
    return _event_matches(event_type, configured_events)


def _combined_stand_family(stand: str | None) -> tuple[str, str | None]:
    normalized = (stand or "").strip().upper()
    if len(normalized) > 1 and normalized[-1] in {"L", "R"}:
        return normalized[:-1], normalized[-1]
    return normalized, None


def _plans_overlap(left: PlanInput, right: PlanInput) -> bool:
    if not left.plan_start or not left.plan_end or not right.plan_start or not right.plan_end:
        return False
    return left.plan_start < right.plan_end and right.plan_start < left.plan_end


def detect_plan_issues(
    plans: Iterable[PlanInput],
    max_plan_hours: float,
    valid_year_min: int = 2020,
    valid_year_max: int = 2035,
    combination_stand_families: set[str] | None = None,
) -> dict[int, list[str]]:
    plan_list = list(plans)
    issues: dict[int, list[str]] = {plan.id: list(plan.issue_tags) for plan in plan_list}

    for plan in plan_list:
        tags = issues[plan.id]
        if not plan.stand:
            tags.append("MISSING_STAND")
        if not plan.plan_start or not plan.plan_end:
            tags.append("MISSING_PLAN_TIME")
        else:
            if plan.plan_end < plan.plan_start:
                tags.append("INVALID_TIME_ORDER")
            duration_hours = (plan.plan_end - plan.plan_start).total_seconds() / 3600
            if duration_hours > max_plan_hours:
                tags.append("LONG_WINDOW")
            if (
                plan.plan_start.year < valid_year_min
                or plan.plan_start.year > valid_year_max
                or plan.plan_end.year < valid_year_min
                or plan.plan_end.year > valid_year_max
            ):
                tags.append("INVALID_YEAR")
    occupancy_groups: dict[tuple[str, str, datetime, datetime], list[PlanInput]] = {}
    for plan in plan_list:
        if plan.aircraft_no and plan.stand and plan.plan_start and plan.plan_end:
            key = (plan.aircraft_no, plan.stand, plan.plan_start, plan.plan_end)
            occupancy_groups.setdefault(key, []).append(plan)
    for occupancy_plans in occupancy_groups.values():
        if len(occupancy_plans) > 1:
            for plan in occupancy_plans:
                issues[plan.id].append("OCCUPANCY_FLIGHT_CONFLICT")

    for stand in {plan.stand for plan in plan_list if plan.stand}:
        ordered = sorted(
            [p for p in plan_list if p.stand == stand and p.plan_start and p.plan_end],
            key=lambda item: item.plan_start or datetime.min,
        )
        for previous, current in zip(ordered, ordered[1:]):
            if current.plan_start and previous.plan_end and current.plan_start < previous.plan_end:
                issues[previous.id].append("OVERLAP")
                issues[current.id].append("OVERLAP")

    plans_by_family: dict[str, list[PlanInput]] = {}
    for plan in plan_list:
        family, _ = _combined_stand_family(plan.stand)
        if family:
            plans_by_family.setdefault(family, []).append(plan)
    for family, family_plans in plans_by_family.items():
        if combination_stand_families is not None and family not in combination_stand_families:
            continue
        combined = [plan for plan in family_plans if _combined_stand_family(plan.stand)[1] is None]
        sides = [plan for plan in family_plans if _combined_stand_family(plan.stand)[1] is not None]
        for combined_plan in combined:
            for side_plan in sides:
                if _plans_overlap(combined_plan, side_plan):
                    issues[combined_plan.id].append("COMBINATION_STAND_CONFLICT")
                    issues[side_plan.id].append("COMBINATION_STAND_CONFLICT")

    return {plan_id: sorted(set(tags)) for plan_id, tags in issues.items()}


def _cluster_nodes(
    nodes: Iterable[NodeInput],
    airport_code: str,
    idle_gap_minutes: int,
    approach_chain_minutes: int,
    group_start_events: Iterable[str],
) -> list[GroupResult]:
    grouped_by_stand: dict[str, list[NodeInput]] = {}
    invalid_nodes: list[NodeInput] = []
    for node in nodes:
        if node.is_anomaly or not node.event_time or not node.stand:
            invalid_nodes.append(node)
            continue
        grouped_by_stand.setdefault(node.stand, []).append(node)

    results: list[GroupResult] = []
    for stand, stand_nodes in sorted(grouped_by_stand.items()):
        ordered = sorted(stand_nodes, key=lambda item: (item.event_time or datetime.min, item.id))
        chunks: list[list[NodeInput]] = []
        current: list[NodeInput] = []
        current_has_terminal_end = False

        for node in ordered:
            should_split = False
            if current:
                previous_time = current[-1].event_time or node.event_time
                gap = (node.event_time - previous_time).total_seconds() / 60 if previous_time else 0
                node_is_terminal_end = is_terminal_end_event(node.event_type)
                should_split = (
                    current_has_terminal_end and not node_is_terminal_end
                ) or gap > idle_gap_minutes
                if not should_split and is_aircraft_entry_event(node.event_type):
                    recent_start_indexes = [
                        index
                        for index, item in enumerate(current)
                        if is_group_start_event(item.event_type, group_start_events)
                        and item.event_time
                        and node.event_time
                        and 0
                        <= (node.event_time - item.event_time).total_seconds() / 60
                        <= approach_chain_minutes
                    ]
                    if recent_start_indexes:
                        start_index = recent_start_indexes[0]
                        if start_index > 0:
                            chunks.append(current[:start_index])
                            current = current[start_index:]
                            current_has_terminal_end = any(
                                is_terminal_end_event(item.event_type) for item in current
                            )
                    else:
                        should_split = True
            if should_split:
                chunks.append(current)
                current = []
                current_has_terminal_end = False
            current.append(node)
            current_has_terminal_end = current_has_terminal_end or is_terminal_end_event(
                node.event_type
            )
        if current:
            chunks.append(current)

        day_sequences: dict[str, int] = {}
        for chunk in chunks:
            start = chunk[0].event_time
            end = chunk[-1].event_time
            assert start and end
            day_key = start.strftime("%Y%m%d")
            day_sequences[day_key] = day_sequences.get(day_key, 0) + 1
            code = f"TMP-{airport_code}-{stand}-{day_key}-{day_sequences[day_key]:03d}"
            has_start = any(
                is_start_event(node.event_type)
                or is_group_start_event(node.event_type, group_start_events)
                for node in chunk
            )
            has_end = any(is_end_event(node.event_type) for node in chunk)
            orphan_start = len(chunk) == 1 and is_group_start_event(
                chunk[0].event_type, group_start_events
            )
            has_occupancy_boundary = any(
                is_group_start_event(node.event_type, group_start_events)
                or is_aircraft_entry_event(node.event_type)
                or is_terminal_end_event(node.event_type)
                for node in chunk
            )
            duration_seconds = (end - start).total_seconds()
            low_information_fragment = (
                len(chunk) <= 3 and duration_seconds <= 120 and not has_occupancy_boundary
            )
            tags = [] if has_start and has_end else ["INCOMPLETE_SEQUENCE"]
            if orphan_start:
                tags.append("ORPHAN_START_MARKER")
            if low_information_fragment:
                tags.append("INCOMPLETE_FRAGMENT")
            if orphan_start or low_information_fragment:
                tags.append("DEGRADED")
            is_degraded = orphan_start or low_information_fragment
            results.append(
                GroupResult(
                    temporary_code=code,
                    stand=stand,
                    observed_start=start,
                    observed_end=end,
                    node_ids=[node.id for node in chunk],
                    assignment_status="UNASSIGNED_FINAL" if is_degraded else "UNASSIGNED",
                    assigned_flight_id=None,
                    confidence=0.2 if is_degraded else (0.9 if has_start and has_end else 0.68),
                    margin=0,
                    issue_tags=tags,
                    lineage=(
                        {
                            "degraded": {
                                "reason": (
                                    "LOW_INFORMATION_FRAGMENT"
                                    if low_information_fragment
                                    else "ORPHAN_START_MARKER"
                                ),
                                "node_count": len(chunk),
                                "duration_seconds": duration_seconds,
                            }
                        }
                        if is_degraded
                        else {}
                    ),
                )
            )

    for index, node in enumerate(invalid_nodes, start=1):
        timestamp = node.event_time or datetime(1970, 1, 1)
        stand = node.stand or "UNKNOWN"
        results.append(
            GroupResult(
                temporary_code=f"ERR-{airport_code}-{index:04d}",
                stand=stand,
                observed_start=timestamp,
                observed_end=timestamp,
                node_ids=[node.id],
                assignment_status="DATA_ERROR",
                assigned_flight_id=None,
                confidence=0,
                margin=0,
                issue_tags=["NODE_DATA_ERROR"],
            )
        )
    return sorted(results, key=lambda item: (item.observed_start, item.stand))


def _plan_intersects_group(plan: PlanInput, group: GroupResult) -> bool:
    return bool(
        plan.stand == group.stand
        and plan.plan_start
        and plan.plan_end
        and plan.plan_start < group.observed_end
        and plan.plan_end > group.observed_start
    )


def _node_id_set_hash(node_ids: Iterable[int]) -> str:
    canonical = ",".join(str(node_id) for node_id in sorted(node_ids))
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def _stands_compete_for_resource(
    left: str,
    right: str,
    combination_families: set[str],
) -> bool:
    normalized_left = left.strip().upper()
    normalized_right = right.strip().upper()
    if normalized_left == normalized_right:
        return True
    left_family, left_side = _combined_stand_family(normalized_left)
    right_family, right_side = _combined_stand_family(normalized_right)
    return bool(
        left_family == right_family
        and left_family in combination_families
        and (left_side is None or right_side is None)
    )


def _plan_overlaps_gap(plan: PlanInput, previous: GroupResult, tail: GroupResult) -> bool:
    return bool(
        plan.plan_start
        and plan.plan_end
        and plan.plan_start <= tail.observed_start
        and plan.plan_end >= previous.observed_end
    )


def _interval_iou(
    left_start: datetime,
    left_end: datetime,
    right_start: datetime,
    right_end: datetime,
) -> float:
    """两个时间区间的交并比。计划时间与实际作业常有二三十分钟错位，不能要求完整覆盖。"""
    overlap = (
        min(left_end, right_end) - max(left_start, right_start)
    ).total_seconds()
    if overlap <= 0:
        return 0.0
    union = (
        (left_end - left_start).total_seconds()
        + (right_end - right_start).total_seconds()
        - overlap
    )
    return overlap / union if union > 0 else 0.0


def _group_overlaps_open_gap(
    group: GroupResult,
    previous: GroupResult,
    tail: GroupResult,
) -> bool:
    return bool(
        group.observed_end > previous.observed_end and group.observed_start < tail.observed_start
    )


def _groups_overlap(left: GroupResult, right: GroupResult) -> bool:
    if left.observed_start == left.observed_end:
        return right.observed_start <= left.observed_start <= right.observed_end
    if right.observed_start == right.observed_end:
        return left.observed_start <= right.observed_start <= left.observed_end
    return bool(
        left.observed_start < right.observed_end and right.observed_start < left.observed_end
    )


def _group_has_start_boundary(
    group: GroupResult,
    nodes_by_id: dict[int, NodeInput],
    group_start_events: Iterable[str],
) -> bool:
    return any(
        is_aircraft_entry_event(nodes_by_id[node_id].event_type)
        or is_group_start_event(nodes_by_id[node_id].event_type, group_start_events)
        for node_id in group.node_ids
    )


def _group_has_terminal_boundary(
    group: GroupResult,
    nodes_by_id: dict[int, NodeInput],
) -> bool:
    return any(is_terminal_end_event(nodes_by_id[node_id].event_type) for node_id in group.node_ids)


def _resource_occupancy_overlaps(
    target: GroupResult,
    occupant: GroupResult,
    all_groups: list[GroupResult],
    nodes_by_id: dict[int, NodeInput],
    group_start_events: Iterable[str],
    open_timeout_minutes: int,
) -> bool:
    if _groups_overlap(target, occupant):
        return True
    if not _group_has_start_boundary(
        occupant, nodes_by_id, group_start_events
    ) or _group_has_terminal_boundary(occupant, nodes_by_id):
        return False

    occupancy_end = occupant.observed_start + timedelta(minutes=open_timeout_minutes)
    later_boundaries = [
        other.observed_start
        for other in all_groups
        if other is not occupant
        and other.stand == occupant.stand
        and other.observed_start > occupant.observed_start
        and (
            _group_has_start_boundary(other, nodes_by_id, group_start_events)
            or _group_has_terminal_boundary(other, nodes_by_id)
        )
    ]
    if later_boundaries:
        occupancy_end = min(occupancy_end, min(later_boundaries))
    return bool(
        occupant.observed_start < target.observed_end and target.observed_start < occupancy_end
    )


def _restore_immutable_groups(
    groups: list[GroupResult],
    immutable_groups: Iterable[GroupResult],
) -> list[GroupResult]:
    restored = list(groups)
    claimed_node_ids: set[int] = set()
    for immutable in immutable_groups:
        immutable_node_ids = set(immutable.node_ids)
        if not immutable_node_ids or immutable_node_ids & claimed_node_ids:
            raise ValueError("immutable sent groups must have disjoint non-empty node sets")
        affected = [group for group in restored if immutable_node_ids.intersection(group.node_ids)]
        affected_node_ids = {node_id for group in affected for node_id in group.node_ids}
        if affected_node_ids != immutable_node_ids:
            raise ValueError(
                "immutable sent group membership overlaps mutable or missing source nodes"
            )
        remaining = [group for group in restored if group not in affected]
        if any(group.temporary_code == immutable.temporary_code for group in remaining):
            raise ValueError("immutable sent group temporary code collides with a mutable group")
        lineage = dict(immutable.lineage)
        lineage["immutable_sent_replay"] = {
            "temporary_code": immutable.temporary_code,
            "node_id_set_sha256": _node_id_set_hash(immutable.node_ids),
        }
        remaining.append(
            GroupResult(
                temporary_code=immutable.temporary_code,
                stand=immutable.stand,
                observed_start=immutable.observed_start,
                observed_end=immutable.observed_end,
                node_ids=list(immutable.node_ids),
                assignment_status=immutable.assignment_status,
                assigned_flight_id=immutable.assigned_flight_id,
                confidence=immutable.confidence,
                margin=immutable.margin,
                issue_tags=list(immutable.issue_tags),
                candidates=list(immutable.candidates),
                lineage=lineage,
            )
        )
        restored = remaining
        claimed_node_ids.update(immutable_node_ids)
    return sorted(restored, key=lambda item: (item.observed_start, item.stand))


def _reattach_terminal_tails(
    groups: list[GroupResult],
    nodes_by_id: dict[int, NodeInput],
    plans: list[PlanInput],
    plan_issues: dict[int, list[str]],
    strategy: dict[str, Any],
    protected_codes: set[str],
    protected_node_ids: set[int],
) -> list[GroupResult]:
    if not strategy.get("terminal_tail_reattach_enabled", False):
        return groups

    maximum_gap = timedelta(minutes=int(strategy["terminal_tail_lookback_minutes"]))
    maximum_nodes = int(strategy["terminal_tail_max_nodes"])
    policy = strategy["terminal_tail_event_policy"]
    group_start_events = policy["group_start_events"]
    aircraft_entry_events = policy["aircraft_entry_events"]
    aircraft_leave_events = policy["aircraft_leave_events"]
    tow_end_events = policy["tow_end_events"]
    allowed_tail_events = policy["allowed_tail_events"]
    combination_families = {
        value.strip().upper() for value in strategy.get("combination_stand_families", [])
    }
    original_groups = list(groups)
    existing_codes = {group.temporary_code for group in groups}
    groups_by_stand: dict[str, list[GroupResult]] = {}
    for group in groups:
        groups_by_stand.setdefault(group.stand, []).append(group)

    merged: list[GroupResult] = []
    for stand_groups in groups_by_stand.values():
        stand_results: list[GroupResult] = []
        for tail in sorted(
            stand_groups, key=lambda item: (item.observed_start, item.temporary_code)
        ):
            previous = stand_results[-1] if stand_results else None
            if (
                previous is None
                or previous.assignment_status == "DATA_ERROR"
                or tail.assignment_status == "DATA_ERROR"
                or previous.temporary_code in protected_codes
                or tail.temporary_code in protected_codes
                or bool(set(previous.node_ids + tail.node_ids) & protected_node_ids)
            ):
                stand_results.append(tail)
                continue

            tail_nodes = [nodes_by_id[node_id] for node_id in tail.node_ids]
            gap = tail.observed_start - previous.observed_end
            contains_terminal = any(
                _event_matches(node.event_type, aircraft_leave_events)
                or _event_matches(node.event_type, tow_end_events)
                for node in tail_nodes
            )
            contains_start = any(
                _event_matches(node.event_type, aircraft_entry_events)
                or _event_matches(node.event_type, group_start_events)
                for node in tail_nodes
            )
            terminal_chain = bool(
                timedelta(0) <= gap <= maximum_gap
                and 0 < len(tail_nodes) <= maximum_nodes
                and contains_terminal
                and not contains_start
                and all(
                    is_terminal_tail_event(node.event_type, allowed_tail_events)
                    for node in tail_nodes
                )
            )
            if not terminal_chain:
                stand_results.append(tail)
                continue

            previous_nodes = [nodes_by_id[node_id] for node_id in previous.node_ids]
            previous_has_terminal = any(
                _event_matches(node.event_type, aircraft_leave_events)
                or _event_matches(node.event_type, tow_end_events)
                for node in previous_nodes
            )
            shared_plans = [
                plan
                for plan in plans
                if _plan_intersects_group(plan, previous) and _plan_intersects_group(plan, tail)
            ]
            previous_plans = [plan for plan in plans if _plan_intersects_group(plan, previous)]
            blocking_plan_tags = {
                "COMBINATION_STAND_CONFLICT",
                "INVALID_YEAR",
                "INVALID_TIME_ORDER",
                "MISSING_PLAN_TIME",
            }
            usable_shared_plans = [
                plan
                for plan in shared_plans
                if not blocking_plan_tags.intersection(plan_issues.get(plan.id, []))
            ]
            shared_plan_ids = {plan.id for plan in shared_plans}
            previous_plan_ids = {plan.id for plan in previous_plans}
            intervening_plan_ids = [
                plan.id
                for plan in plans
                if plan.id not in shared_plan_ids
                and (
                    plan.id not in previous_plan_ids
                    or (plan.plan_end and plan.plan_end >= tail.observed_start)
                )
                and plan.stand
                and _stands_compete_for_resource(previous.stand, plan.stand, combination_families)
                and _plan_overlaps_gap(plan, previous, tail)
                and not {"INVALID_YEAR", "INVALID_TIME_ORDER", "MISSING_PLAN_TIME"}.intersection(
                    plan_issues.get(plan.id, [])
                )
            ]
            intervening_group_codes: list[str] = []
            for other in original_groups:
                if other is previous or other is tail:
                    continue
                if not _stands_compete_for_resource(
                    previous.stand, other.stand, combination_families
                ):
                    continue
                if not _group_overlaps_open_gap(other, previous, tail):
                    continue
                intervening_group_codes.append(other.temporary_code)

            tail_has_complete_terminal_pair = any(
                _event_matches(node.event_type, aircraft_leave_events) for node in tail_nodes
            ) and any(_event_matches(node.event_type, tow_end_events) for node in tail_nodes)
            reported_flight_numbers = {
                node.reported_flight_no.strip().upper()
                for node in previous_nodes + tail_nodes
                if node.reported_flight_no and node.reported_flight_no.strip()
            }
            reported_numbers_fit_shared_plan = any(
                reported_flight_numbers.issubset(plan.flight_numbers)
                for plan in usable_shared_plans
            )
            if reported_flight_numbers and not reported_numbers_fit_shared_plan:
                tail.issue_tags = sorted(
                    set(tail.issue_tags) | {"TERMINAL_TAIL_REFERENCE_CONFLICT"}
                )
                stand_results.append(tail)
                continue
            evidence = None
            if not intervening_group_codes and not intervening_plan_ids:
                if len(shared_plans) == 1 and len(usable_shared_plans) == 1:
                    evidence = "UNIQUE_PLAN_WINDOW"
                elif (
                    not shared_plans
                    and len(previous_plans) <= 1
                    and not previous_has_terminal
                    and tail_has_complete_terminal_pair
                ):
                    evidence = "MISSING_PREVIOUS_END_WITH_COMPLETE_TAIL"
            if evidence is None:
                stand_results.append(tail)
                continue

            combined_node_ids = sorted(
                previous.node_ids + tail.node_ids,
                key=lambda node_id: (nodes_by_id[node_id].event_time or datetime.min, node_id),
            )
            combined_nodes = [nodes_by_id[node_id] for node_id in combined_node_ids]
            combined_tags = (
                set(previous.issue_tags) | set(tail.issue_tags) | {"TERMINAL_TAIL_REATTACHED"}
            ) - {"INCOMPLETE_SEQUENCE", "INCOMPLETE_FRAGMENT", "DEGRADED"}
            if not (
                any(
                    is_start_event(node.event_type)
                    or _event_matches(node.event_type, group_start_events)
                    for node in combined_nodes
                )
                and any(is_end_event(node.event_type) for node in combined_nodes)
            ):
                combined_tags.add("INCOMPLETE_SEQUENCE")
            merged_code = f"{previous.temporary_code}-M"
            if merged_code in existing_codes:
                merged_code = f"{merged_code}-{_node_id_set_hash(combined_node_ids)[:8]}"
            existing_codes.add(merged_code)
            merged_group = GroupResult(
                temporary_code=merged_code,
                stand=previous.stand,
                observed_start=min(previous.observed_start, tail.observed_start),
                observed_end=max(previous.observed_end, tail.observed_end),
                node_ids=combined_node_ids,
                assignment_status="UNASSIGNED",
                assigned_flight_id=None,
                confidence=max(previous.confidence, 0.68),
                margin=0,
                issue_tags=sorted(combined_tags),
                candidates=[],
                lineage={
                    "terminal_tail_reattachment": {
                        "source_groups": [
                            {
                                "temporary_code": previous.temporary_code,
                                "node_id_set_sha256": _node_id_set_hash(previous.node_ids),
                            },
                            {
                                "temporary_code": tail.temporary_code,
                                "node_id_set_sha256": _node_id_set_hash(tail.node_ids),
                            },
                        ],
                        "merged_node_id_set_sha256": _node_id_set_hash(combined_node_ids),
                        "tail_node_ids": list(tail.node_ids),
                        "gap_minutes": round(gap.total_seconds() / 60, 2),
                        "evidence": evidence,
                        "shared_plan_ids": [plan.id for plan in shared_plans],
                        "previous_plan_ids": [plan.id for plan in previous_plans],
                        "intervening_group_codes": intervening_group_codes,
                        "intervening_plan_ids": intervening_plan_ids,
                    }
                },
            )
            stand_results[-1] = merged_group
        merged.extend(stand_results)
    return sorted(merged, key=lambda item: (item.observed_start, item.stand))


def _bridge_overnight_stays(
    groups: list[GroupResult],
    nodes_by_id: dict[int, NodeInput],
    plans: list[PlanInput],
    plan_issues: dict[int, list[str]],
    strategy: dict[str, Any],
    protected_codes: set[str],
    protected_node_ids: set[int],
) -> list[GroupResult]:
    if not strategy.get("overnight_bridge_enabled", False):
        return groups

    idle_gap = timedelta(minutes=int(strategy["idle_gap_minutes"]))
    maximum_gap = timedelta(minutes=int(strategy["overnight_bridge_max_gap_minutes"]))
    plan_iou_threshold = float(strategy["overnight_bridge_plan_iou_threshold"])
    group_start_events = strategy["terminal_tail_event_policy"]["group_start_events"]
    combination_families = {
        value.strip().upper() for value in strategy.get("combination_stand_families", [])
    }
    blocking_plan_tags = {
        "COMBINATION_STAND_CONFLICT",
        "INVALID_YEAR",
        "INVALID_TIME_ORDER",
        "MISSING_PLAN_TIME",
    }

    original_groups = list(groups)
    existing_codes = {group.temporary_code for group in groups}
    groups_by_stand: dict[str, list[GroupResult]] = {}
    for group in groups:
        groups_by_stand.setdefault(group.stand, []).append(group)

    bridged: list[GroupResult] = []
    for stand_groups in groups_by_stand.values():
        stand_results: list[GroupResult] = []
        for current in sorted(
            stand_groups, key=lambda item: (item.observed_start, item.temporary_code)
        ):
            previous = stand_results[-1] if stand_results else None
            if (
                previous is None
                or previous.assignment_status == "DATA_ERROR"
                or current.assignment_status == "DATA_ERROR"
                or previous.temporary_code in protected_codes
                or current.temporary_code in protected_codes
                or bool(set(previous.node_ids + current.node_ids) & protected_node_ids)
            ):
                stand_results.append(current)
                continue

            gap = current.observed_start - previous.observed_end
            if not idle_gap < gap <= maximum_gap:
                stand_results.append(current)
                continue

            # 过夜形态：前组飞机入位后未推出，后组次晨推出且不是新入位。
            if (
                not _group_has_start_boundary(previous, nodes_by_id, group_start_events)
                or _group_has_terminal_boundary(previous, nodes_by_id)
                or _group_has_start_boundary(current, nodes_by_id, group_start_events)
                or not _group_has_terminal_boundary(current, nodes_by_id)
            ):
                stand_results.append(current)
                continue

            # 计划窗口与合并后观测窗口按交并比匹配，不要求完整覆盖。
            stay_start = min(previous.observed_start, current.observed_start)
            stay_end = max(previous.observed_end, current.observed_end)
            stand_plans = [
                plan
                for plan in plans
                if plan.stand
                and plan.plan_start
                and plan.plan_end
                and _stands_compete_for_resource(previous.stand, plan.stand, combination_families)
            ]
            matching_plans = [
                plan
                for plan in stand_plans
                if _interval_iou(plan.plan_start, plan.plan_end, stay_start, stay_end)
                >= plan_iou_threshold
            ]
            usable_plans = [
                plan
                for plan in matching_plans
                if not blocking_plan_tags.intersection(plan_issues.get(plan.id, []))
            ]
            # 唯一已确认计划关系：不得有第二条计划同样贴合这段停场。
            if len(matching_plans) != 1 or len(usable_plans) != 1:
                stand_results.append(current)
                continue
            bridging_plan = usable_plans[0]

            # 夜间不得有其他计划占用同一驻位资源。
            intervening_plan_ids = [
                plan.id
                for plan in stand_plans
                if plan.id != bridging_plan.id
                and plan.plan_start < current.observed_start
                and plan.plan_end > previous.observed_end
                and not {"INVALID_YEAR", "INVALID_TIME_ORDER", "MISSING_PLAN_TIME"}.intersection(
                    plan_issues.get(plan.id, [])
                )
            ]
            if intervening_plan_ids:
                stand_results.append(current)
                continue

            intervening_group_codes = [
                other.temporary_code
                for other in original_groups
                if other is not previous
                and other is not current
                and _stands_compete_for_resource(previous.stand, other.stand, combination_families)
                and _group_overlaps_open_gap(other, previous, current)
            ]
            if intervening_group_codes:
                stand_results.append(current)
                continue

            previous_nodes = [nodes_by_id[node_id] for node_id in previous.node_ids]
            current_nodes = [nodes_by_id[node_id] for node_id in current.node_ids]
            reported_flight_numbers = {
                node.reported_flight_no.strip().upper()
                for node in previous_nodes + current_nodes
                if node.reported_flight_no and node.reported_flight_no.strip()
            }
            if reported_flight_numbers and not reported_flight_numbers.issubset(
                bridging_plan.flight_numbers
            ):
                current.issue_tags = sorted(
                    set(current.issue_tags) | {"OVERNIGHT_BRIDGE_REFERENCE_CONFLICT"}
                )
                stand_results.append(current)
                continue

            combined_node_ids = sorted(
                previous.node_ids + current.node_ids,
                key=lambda node_id: (nodes_by_id[node_id].event_time or datetime.min, node_id),
            )
            combined_tags = (
                set(previous.issue_tags) | set(current.issue_tags) | {"OVERNIGHT_BRIDGED"}
            ) - {"INCOMPLETE_SEQUENCE", "INCOMPLETE_FRAGMENT", "DEGRADED"}
            bridged_code = f"{previous.temporary_code}-N"
            if bridged_code in existing_codes:
                bridged_code = f"{bridged_code}-{_node_id_set_hash(combined_node_ids)[:8]}"
            existing_codes.add(bridged_code)
            stand_results[-1] = GroupResult(
                temporary_code=bridged_code,
                stand=previous.stand,
                observed_start=min(previous.observed_start, current.observed_start),
                observed_end=max(previous.observed_end, current.observed_end),
                node_ids=combined_node_ids,
                assignment_status="UNASSIGNED",
                assigned_flight_id=None,
                confidence=max(previous.confidence, 0.68),
                margin=0,
                issue_tags=sorted(combined_tags),
                candidates=[],
                lineage={
                    "overnight_bridge": {
                        "source_groups": [
                            {
                                "temporary_code": previous.temporary_code,
                                "node_id_set_sha256": _node_id_set_hash(previous.node_ids),
                            },
                            {
                                "temporary_code": current.temporary_code,
                                "node_id_set_sha256": _node_id_set_hash(current.node_ids),
                            },
                        ],
                        "merged_node_id_set_sha256": _node_id_set_hash(combined_node_ids),
                        "gap_minutes": round(gap.total_seconds() / 60, 2),
                        "bridging_plan_id": bridging_plan.id,
                        "plan_iou": round(
                            _interval_iou(
                                bridging_plan.plan_start,
                                bridging_plan.plan_end,
                                stay_start,
                                stay_end,
                            ),
                            4,
                        ),
                        "plan_start": bridging_plan.plan_start.isoformat(),
                        "plan_end": bridging_plan.plan_end.isoformat(),
                    }
                },
            )
        bridged.extend(stand_results)
    return sorted(bridged, key=lambda item: (item.observed_start, item.stand))


def _parent_stand_issue(
    group: GroupResult,
    groups: list[GroupResult],
    nodes_by_id: dict[int, NodeInput],
    plans: list[PlanInput],
    plan_issues: dict[int, list[str]],
    combination_families: set[str],
    group_start_events: Iterable[str],
    open_occupancy_timeout_minutes: int,
) -> str | None:
    family, side = _combined_stand_family(group.stand)
    if not family or side is not None or family not in combination_families:
        return None
    business_dates = {group.observed_start.date(), group.observed_end.date()}

    def touches_business_date(plan: PlanInput) -> bool:
        return bool(
            plan.plan_start
            and plan.plan_end
            and any(plan.plan_start.date() <= day <= plan.plan_end.date() for day in business_dates)
        )

    parent_plans = [plan for plan in plans if plan.stand == family and touches_business_date(plan)]
    side_exists = any(
        _combined_stand_family(plan.stand) in {(family, "L"), (family, "R")}
        and touches_business_date(plan)
        for plan in plans
    )
    side_occupancy_exists = any(
        other is not group
        and _combined_stand_family(other.stand) in {(family, "L"), (family, "R")}
        and _resource_occupancy_overlaps(
            group,
            other,
            groups,
            nodes_by_id,
            group_start_events,
            open_occupancy_timeout_minutes,
        )
        for other in groups
    )
    if not side_exists and not side_occupancy_exists:
        return None
    if not parent_plans:
        return "PARENT_STAND_CODE_WITHOUT_PLAN"
    if side_occupancy_exists:
        return "PARENT_STAND_ACTUAL_OCCUPANCY_CONFLICT"
    if all("COMBINATION_STAND_CONFLICT" in plan_issues.get(plan.id, []) for plan in parent_plans):
        return "PARENT_STAND_PLAN_CONFLICT"
    return None


def _minutes_between(left: datetime, right: datetime) -> float:
    return abs((left - right).total_seconds()) / 60


def _time_ranges_overlap(group: GroupResult, plan: PlanInput) -> bool:
    if not plan.plan_start or not plan.plan_end:
        return False
    return group.observed_start < plan.plan_end and plan.plan_start < group.observed_end


def _acdm_times_fit_group(
    group: GroupResult, reference: AcdmReferenceInput, tolerance_minutes: float
) -> bool:
    tolerance = timedelta(minutes=tolerance_minutes)
    reported_times = [reference.aircraft_entry_time]
    if reference.chock_on_time:
        reported_times.append(reference.chock_on_time)
    if reference.stand_release_time:
        reported_times.append(reference.stand_release_time)
    return all(
        group.observed_start - tolerance <= value <= group.observed_end + tolerance
        for value in reported_times
    )


def _apply_stand_occupancy_lineage(
    group: GroupResult,
    group_nodes: list[NodeInput],
    reference: AcdmReferenceInput | None,
) -> None:
    algorithm_entries = [
        node.event_time
        for node in group_nodes
        if node.source_type == "algorithm_node"
        and node.event_time
        and is_aircraft_entry_event(node.event_type)
    ]
    algorithm_terminal = [
        node.event_time
        for node in group_nodes
        if node.source_type == "algorithm_node"
        and node.event_time
        and is_terminal_end_event(node.event_type)
    ]
    if reference:
        start_time = reference.aircraft_entry_time
        start_source = "acdm_aircraft_entry"
    elif algorithm_entries:
        start_time = min(algorithm_entries)
        start_source = "algorithm_aircraft_entry"
    else:
        start_time = group.observed_start
        start_source = "observed_group_start"

    if algorithm_terminal:
        end_time = max(algorithm_terminal)
        end_source = "algorithm_terminal"
    elif reference and reference.stand_release_time:
        end_time = reference.stand_release_time
        end_source = "acdm_stand_release"
    else:
        end_time = group.observed_end
        end_source = "observed_group_end"

    group.lineage["stand_occupancy"] = {
        "start_time": start_time.isoformat(),
        "start_source": start_source,
        "end_time": end_time.isoformat(),
        "end_source": end_source,
    }


def _acdm_lineage(
    reference: AcdmReferenceInput,
    state: str,
    times_within_tolerance: bool,
    tolerance_minutes: float,
) -> dict[str, Any]:
    return {
        "state": state,
        "flight_no": reference.flight_no.upper(),
        "aircraft_entry_time": reference.aircraft_entry_time.isoformat(),
        "chock_on_time": (reference.chock_on_time.isoformat() if reference.chock_on_time else None),
        "stand_release_time": (
            reference.stand_release_time.isoformat() if reference.stand_release_time else None
        ),
        "time_tolerance_minutes": tolerance_minutes,
        "times_within_tolerance": times_within_tolerance,
    }


def _score_candidate(
    group: GroupResult,
    group_nodes: list[NodeInput],
    plan: PlanInput,
    appearance: AppearanceInput | None,
    acdm_reference: AcdmReferenceInput | None,
    config: dict[str, Any],
) -> CandidateScore:
    weights = config["weights"]
    breakdown: dict[str, float] = {}
    excluded_reason: str | None = None

    breakdown["stand"] = float(weights["stand"] if group.stand == plan.stand else 0)
    if not plan.plan_start or not plan.plan_end:
        excluded_reason = "计划时间缺失"
        return CandidateScore(plan.id, 0, breakdown, excluded_reason=excluded_reason)

    valid_year_min = int(config.get("valid_plan_year_min", 2020))
    valid_year_max = int(config.get("valid_plan_year_max", 2035))
    if not all(
        valid_year_min <= value.year <= valid_year_max for value in (plan.plan_start, plan.plan_end)
    ):
        excluded_reason = "计划年份异常"
        return CandidateScore(plan.id, 0, breakdown, excluded_reason=excluded_reason)

    duration_hours = (plan.plan_end - plan.plan_start).total_seconds() / 3600
    if duration_hours < 0 or duration_hours > config["hard_reject_plan_hours"]:
        excluded_reason = "计划时间窗不可用"
        return CandidateScore(plan.id, 0, breakdown, excluded_reason=excluded_reason)

    use_continuous_decay = bool(config.get("sequence_resolution_enabled"))
    grace_minutes = 0.0 if use_continuous_decay else float(config["window_grace_minutes"])
    grace = timedelta(minutes=grace_minutes)
    start_distance = max(
        0.0, _minutes_between(group.observed_start, plan.plan_start) - grace_minutes
    )
    end_distance = max(0.0, _minutes_between(group.observed_end, plan.plan_end) - grace_minutes)
    decay_minutes = float(config.get("time_decay_minutes", 60)) if use_continuous_decay else 60.0
    start_fit = max(0.0, 1 - start_distance / decay_minutes)
    end_fit = max(0.0, 1 - end_distance / decay_minutes)
    breakdown["time_window"] = round(
        float(weights["time_window"]) * (start_fit + end_fit) / 2,
        2,
    )

    start_count = sum(is_start_event(node.event_type) for node in group_nodes)
    end_count = sum(is_end_event(node.event_type) for node in group_nodes)
    semantic_weight = float(weights["node_semantics"])
    if end_count > start_count:
        distance = _minutes_between(group.observed_end, plan.plan_end)
    elif start_count > 0:
        distance = _minutes_between(group.observed_start, plan.plan_start)
    else:
        group_center = group.observed_start + (group.observed_end - group.observed_start) / 2
        plan_center = plan.plan_start + (plan.plan_end - plan.plan_start) / 2
        distance = _minutes_between(group_center, plan_center)
    breakdown["node_semantics"] = round(semantic_weight * max(0, 1 - distance / 120), 2)

    valid_times = [node.event_time for node in group_nodes if node.event_time]
    covered = sum(
        plan.plan_start - grace <= value <= plan.plan_end + grace for value in valid_times
    )
    coverage = covered / len(valid_times) if valid_times else 0
    breakdown["continuity"] = round(float(weights["continuity"]) * coverage, 2)

    appearance_confident = appearance and (
        appearance.confidence >= config["appearance_confidence_threshold"]
    )
    if appearance_confident and appearance:
        if appearance.airline and plan.airline:
            breakdown["appearance_airline"] = float(
                weights["appearance_airline"]
                if appearance.airline.upper() == plan.airline.upper()
                else -weights["appearance_airline"]
            )
        if appearance.aircraft_type and plan.aircraft_type:
            breakdown["appearance_type"] = float(
                weights["appearance_type"]
                if appearance.aircraft_type.upper() == plan.aircraft_type.upper()
                else -weights["appearance_type"]
            )

    if appearance and appearance.aircraft_registration and plan.aircraft_no:
        similarity = registration_similarity(appearance.aircraft_registration, plan.aircraft_no)
        registration_confidence = (
            appearance.registration_confidence
            if appearance.registration_confidence is not None
            else appearance.confidence
        )
        evidence_strength = max(0.0, (similarity - 0.5) * 2)
        breakdown["registration_similarity"] = similarity
        breakdown["appearance_registration"] = round(
            float(weights["appearance_registration"]) * evidence_strength * registration_confidence,
            2,
        )

    score = round(
        sum(value for key, value in breakdown.items() if key != "registration_similarity"),
        2,
    )
    return CandidateScore(plan.id, score, breakdown, excluded_reason=excluded_reason)


def _apply_sequence_resolution(
    groups: list[GroupResult],
    plans: list[PlanInput],
    plan_issues: dict[int, list[str]],
    strategy: dict[str, Any],
) -> None:
    if not strategy.get("sequence_resolution_enabled"):
        return

    plans_by_stand: dict[str, list[PlanInput]] = {}
    for plan in plans:
        if plan.stand and plan.plan_start and plan.plan_end:
            plans_by_stand.setdefault(plan.stand, []).append(plan)
    for stand_plans in plans_by_stand.values():
        stand_plans.sort(key=lambda plan: (plan.plan_start or datetime.min, plan.id))

    groups_by_stand: dict[str, list[GroupResult]] = {}
    for group in groups:
        if group.assignment_status != "DATA_ERROR":
            groups_by_stand.setdefault(group.stand, []).append(group)
    for stand_groups in groups_by_stand.values():
        stand_groups.sort(key=lambda group: (group.observed_start, group.temporary_code))

    base_anchors = {
        group.temporary_code: group.assigned_flight_id
        for group in groups
        if group.assignment_status in {"MATCHED", "MATCHED_REFERENCE"}
        and group.assigned_flight_id is not None
    }
    occupied_plan_ids = set(base_anchors.values())
    blocking_tags = {
        "MISSING_PLAN",
        "INCOMPLETE_SEQUENCE",
        "CROSS_STAND_CODE",
        "COMBINATION_STAND_CONFLICT",
        "PARENT_STAND_PLAN_CONFLICT",
        "PARENT_STAND_ACTUAL_OCCUPANCY_CONFLICT",
        "REFERENCE_CONFLICT",
        "PLAN_END_OVERRUN",
        "INVALID_YEAR",
        "INVALID_TIME_ORDER",
        "MISSING_PLAN_TIME",
        "MISSING_STAND",
        "MISSING_SAFEGUARD_CODE",
        "LONG_WINDOW",
        "NODE_DATA_ERROR",
        "ORPHAN_START_MARKER",
    }

    for stand, stand_groups in groups_by_stand.items():
        stand_plans = plans_by_stand.get(stand, [])
        plan_positions = {plan.id: index for index, plan in enumerate(stand_plans)}
        for actual_index, group in enumerate(stand_groups):
            group.lineage["sequence_resolution"] = {"state": "not_applied"}
            if actual_index == 0 or group.assignment_status != "NEEDS_REVIEW":
                continue
            if blocking_tags & set(group.issue_tags):
                continue

            previous_group = stand_groups[actual_index - 1]
            previous_plan_id = base_anchors.get(previous_group.temporary_code)
            if previous_plan_id is None:
                continue
            previous_plan_index = plan_positions.get(previous_plan_id)
            if previous_plan_index is None or previous_plan_index + 1 >= len(stand_plans):
                continue

            expected_plan = stand_plans[previous_plan_index + 1]
            if expected_plan.id in occupied_plan_ids:
                continue
            candidate = next(
                (item for item in group.candidates if item.flight_plan_id == expected_plan.id),
                None,
            )
            if candidate is None or candidate.excluded_reason:
                continue
            if blocking_tags & set(plan_issues.get(expected_plan.id, [])):
                continue
            if not _time_ranges_overlap(group, expected_plan):
                group.lineage["sequence_resolution"] = {
                    "state": "rejected_no_time_overlap",
                    "previous_group": previous_group.temporary_code,
                    "previous_flight_plan_id": previous_plan_id,
                    "expected_flight_plan_id": expected_plan.id,
                }
                continue

            sequence_score = float(strategy["weights"]["sequence_order"])
            candidate.breakdown["sequence_order"] = sequence_score
            candidate.score = round(sum(candidate.breakdown.values()), 2)
            group.candidates.sort(key=lambda item: (-item.score, item.flight_plan_id))
            top = group.candidates[0]
            second_score = group.candidates[1].score if len(group.candidates) > 1 else 0
            group.margin = round(top.score - second_score, 2)
            group.confidence = round(min(0.99, max(group.confidence, top.score / 100)), 2)
            group.lineage["sequence_resolution"] = {
                "state": "applied",
                "previous_group": previous_group.temporary_code,
                "previous_flight_plan_id": previous_plan_id,
                "expected_flight_plan_id": expected_plan.id,
                "relative_actual_order": 1,
                "relative_plan_order": 1,
                "stand_actual_position": actual_index + 1,
                "stand_plan_position": previous_plan_index + 2,
                "time_overlap": True,
            }
            if (
                top.flight_plan_id == expected_plan.id
                and top.score >= strategy["auto_match_threshold"]
                and group.margin >= strategy["minimum_margin"]
            ):
                group.assignment_status = "MATCHED"
                group.assigned_flight_id = expected_plan.id
                for item in group.candidates:
                    item.selected = item.flight_plan_id == expected_plan.id
                group.issue_tags = [tag for tag in group.issue_tags if tag != "AMBIGUOUS_MATCH"]
                occupied_plan_ids.add(expected_plan.id)


def _validate_terminal_tail_config(config: dict[str, Any]) -> None:
    if not config.get("terminal_tail_reattach_enabled"):
        return
    policy = config.get("terminal_tail_event_policy")
    required_tail_keys = {
        "terminal_tail_event_policy",
        "terminal_tail_lookback_minutes",
        "terminal_tail_max_nodes",
        "combination_stand_families",
    }
    required_policy_keys = {
        "group_start_events",
        "aircraft_entry_events",
        "aircraft_leave_events",
        "tow_end_events",
        "allowed_tail_events",
    }
    valid_policy = isinstance(policy, dict) and set(policy) == required_policy_keys
    if not required_tail_keys.issubset(config) or not valid_policy:
        raise ValueError("terminal tail reattachment requires a complete versioned event policy")

    assert isinstance(policy, dict)
    if any(
        not isinstance(policy[key], list)
        or not policy[key]
        or any(not isinstance(value, str) or not value.strip() for value in policy[key])
        for key in required_policy_keys
    ):
        raise ValueError("terminal tail event policy values must be non-empty string lists")
    if (
        not isinstance(config["combination_stand_families"], list)
        or not config["combination_stand_families"]
        or any(
            not isinstance(value, str) or not value.strip()
            for value in config["combination_stand_families"]
        )
    ):
        raise ValueError("terminal tail combination stand families must be a non-empty list")
    if (
        int(config["terminal_tail_lookback_minutes"]) <= 0
        or int(config["terminal_tail_max_nodes"]) <= 0
    ):
        raise ValueError("terminal tail limits must be positive")

    normalized = {
        key: {_normalized_event(value) for value in policy[key]} for key in required_policy_keys
    }
    required_events = {
        key: {_normalized_event(value) for value in DEFAULT_TERMINAL_TAIL_EVENT_POLICY[key]}
        for key in required_policy_keys
    }
    if any(not required_events[key].issubset(normalized[key]) for key in required_policy_keys):
        raise ValueError("terminal tail event policy cannot remove required boundary events")
    start_boundaries = normalized["group_start_events"] | normalized["aircraft_entry_events"]
    if start_boundaries & normalized["allowed_tail_events"]:
        raise ValueError("terminal tail events cannot include a group start boundary")


def _validate_parent_guard_config(config: dict[str, Any]) -> None:
    if not config.get("combination_parent_guard_enabled"):
        return
    families = config.get("combination_stand_families")
    timeout = config.get("open_occupancy_timeout_minutes")
    if (
        not isinstance(families, list)
        or not families
        or any(not isinstance(value, str) or not value.strip() for value in families)
        or not isinstance(timeout, (int, float))
        or timeout <= 0
    ):
        raise ValueError(
            "combination parent guard requires stand families and a positive occupancy timeout"
        )


def _validate_overnight_bridge_config(config: dict[str, Any]) -> None:
    if not config.get("overnight_bridge_enabled"):
        return
    required_keys = {
        "overnight_bridge_max_gap_minutes",
        "overnight_bridge_plan_iou_threshold",
        "terminal_tail_event_policy",
        "combination_stand_families",
    }
    if not required_keys.issubset(config):
        raise ValueError("overnight bridging requires a complete versioned configuration")
    maximum_gap = config["overnight_bridge_max_gap_minutes"]
    idle_gap = config.get("idle_gap_minutes", DEFAULT_STRATEGY["idle_gap_minutes"])
    if not isinstance(maximum_gap, (int, float)) or maximum_gap <= 0:
        raise ValueError("overnight bridging maximum gap must be positive")
    if maximum_gap <= idle_gap:
        raise ValueError("overnight bridging must span a gap wider than the idle threshold")
    threshold = config["overnight_bridge_plan_iou_threshold"]
    if not isinstance(threshold, (int, float)) or not 0 < threshold <= 1:
        raise ValueError("overnight bridging plan IoU threshold must fall in (0, 1]")


def run_strategy(
    *,
    airport_code: str,
    plans: list[PlanInput],
    nodes: list[NodeInput],
    appearances: list[AppearanceInput] | None = None,
    acdm_references: list[AcdmReferenceInput] | None = None,
    config: dict[str, Any] | None = None,
    protected_group_codes: set[str] | None = None,
    protected_node_ids: set[int] | None = None,
    immutable_groups: list[GroupResult] | None = None,
) -> list[GroupResult]:
    supplied_config = config or {}
    _validate_terminal_tail_config(supplied_config)
    _validate_parent_guard_config(supplied_config)
    _validate_overnight_bridge_config(supplied_config)
    strategy = DEFAULT_STRATEGY | (config or {})
    strategy["weights"] = DEFAULT_STRATEGY["weights"] | (config or {}).get("weights", {})
    plan_issues = detect_plan_issues(
        plans,
        strategy["max_plan_hours"],
        int(strategy["valid_plan_year_min"]),
        int(strategy["valid_plan_year_max"]),
        {value.strip().upper() for value in strategy.get("combination_stand_families", [])},
    )
    node_by_id = {node.id: node for node in nodes}
    appearance_by_code = {item.temporary_code: item for item in appearances or []}
    acdm_by_code = {item.temporary_code: item for item in acdm_references or []}
    groups = _cluster_nodes(
        nodes,
        airport_code,
        int(strategy["idle_gap_minutes"]),
        int(strategy["approach_chain_minutes"]),
        strategy["terminal_tail_event_policy"]["group_start_events"],
    )
    groups = _restore_immutable_groups(groups, immutable_groups or [])
    immutable_codes = {group.temporary_code for group in immutable_groups or []}
    immutable_node_ids = {node_id for group in immutable_groups or [] for node_id in group.node_ids}
    guarded_codes = (
        set(appearance_by_code)
        | set(acdm_by_code)
        | (protected_group_codes or set())
        | immutable_codes
    )
    guarded_node_ids = (protected_node_ids or set()) | immutable_node_ids
    groups = _reattach_terminal_tails(
        groups,
        node_by_id,
        plans,
        plan_issues,
        strategy,
        guarded_codes,
        guarded_node_ids,
    )
    groups = _bridge_overnight_stays(
        groups,
        node_by_id,
        plans,
        plan_issues,
        strategy,
        guarded_codes,
        guarded_node_ids,
    )
    radius = timedelta(hours=strategy["candidate_radius_hours"])

    for group in groups:
        if group.assignment_status == "DATA_ERROR":
            continue
        if group.lineage.get("immutable_sent_replay"):
            continue
        group_nodes = [node_by_id[node_id] for node_id in group.node_ids]
        acdm_reference = acdm_by_code.get(group.temporary_code)
        _apply_stand_occupancy_lineage(group, group_nodes, acdm_reference)
        parent_stand_issue = (
            _parent_stand_issue(
                group,
                groups,
                node_by_id,
                plans,
                plan_issues,
                {value.strip().upper() for value in strategy.get("combination_stand_families", [])},
                strategy["terminal_tail_event_policy"]["group_start_events"],
                int(strategy["open_occupancy_timeout_minutes"]),
            )
            if strategy.get("combination_parent_guard_enabled", False)
            else None
        )
        if parent_stand_issue:
            group.issue_tags.append(parent_stand_issue)
        same_stand_reference_exists = bool(
            acdm_reference
            and any(
                plan.stand == group.stand
                and acdm_reference.flight_no.upper() in plan.flight_numbers
                for plan in plans
            )
        )
        candidates = []
        for plan in plans:
            reference_match = bool(
                acdm_reference and acdm_reference.flight_no.upper() in plan.flight_numbers
            )
            if (
                (plan.stand != group.stand and (not reference_match or same_stand_reference_exists))
                or not plan.plan_start
                or not plan.plan_end
            ):
                continue
            if (
                plan.plan_end < group.observed_start - radius
                or plan.plan_start > group.observed_end + radius
            ):
                continue
            candidate = _score_candidate(
                group,
                group_nodes,
                plan,
                appearance_by_code.get(group.temporary_code),
                acdm_by_code.get(group.temporary_code),
                strategy,
            )
            candidates.append(candidate)
        candidates.sort(key=lambda item: (-item.score, item.flight_plan_id))
        group.candidates = candidates

        selected_plan_ids = {candidate.flight_plan_id for candidate in candidates}
        related_plan_tags = {
            tag
            for plan_id, tags in plan_issues.items()
            if plan_id in selected_plan_ids
            for tag in tags
        }
        group.issue_tags.extend(sorted(related_plan_tags))

        if acdm_reference:
            reference_candidates = [
                candidate
                for candidate in candidates
                if not candidate.excluded_reason
                and acdm_reference.flight_no.upper()
                in next(
                    plan for plan in plans if plan.id == candidate.flight_plan_id
                ).flight_numbers
            ]
            same_stand = [
                candidate
                for candidate in reference_candidates
                if next(plan for plan in plans if plan.id == candidate.flight_plan_id).stand
                == group.stand
            ]
            if same_stand:
                reference_candidates = same_stand
            acdm_times_fit = _acdm_times_fit_group(
                group,
                acdm_reference,
                float(strategy["acdm_time_tolerance_minutes"]),
            )
            if not acdm_times_fit:
                group.issue_tags.append("ACDM_TIME_OUTLIER")
            if (
                acdm_reference.chock_on_time
                and acdm_reference.chock_on_time < acdm_reference.aircraft_entry_time
            ) or (
                acdm_reference.stand_release_time
                and acdm_reference.stand_release_time < acdm_reference.aircraft_entry_time
            ):
                group.issue_tags.append("ACDM_NODE_ORDER_ANOMALY")
            group.lineage["acdm_reference"] = _acdm_lineage(
                acdm_reference,
                "ambiguous",
                acdm_times_fit,
                float(strategy["acdm_time_tolerance_minutes"]),
            )
            if len(reference_candidates) == 1 and not {
                "COMBINATION_STAND_CONFLICT",
                "PARENT_STAND_PLAN_CONFLICT",
                "PARENT_STAND_ACTUAL_OCCUPANCY_CONFLICT",
            }.intersection(group.issue_tags):
                selected = reference_candidates[0]
                group.candidates.sort(
                    key=lambda item: (
                        item.flight_plan_id != selected.flight_plan_id,
                        -item.score,
                        item.flight_plan_id,
                    )
                )
                selected.selected = True
                group.assignment_status = "MATCHED_REFERENCE"
                group.assigned_flight_id = selected.flight_plan_id
                group.confidence = 1.0
                second_score = max(
                    (item.score for item in candidates if item is not selected),
                    default=0,
                )
                group.margin = round(selected.score - second_score, 2)
                group.lineage["acdm_reference"] = _acdm_lineage(
                    acdm_reference,
                    "confirmed",
                    acdm_times_fit,
                    float(strategy["acdm_time_tolerance_minutes"]),
                )
                group.issue_tags = sorted(set(group.issue_tags))
                continue
            elif not reference_candidates:
                group.assignment_status = "MATCHED_REFERENCE_NO_PLAN"
                group.assigned_flight_id = None
                group.confidence = 1.0
                group.margin = 0
                group.issue_tags.extend(["ACDM_PLAN_MISSING", "MISSING_PLAN"])
                group.lineage["acdm_reference"] = _acdm_lineage(
                    acdm_reference,
                    "confirmed_plan_missing",
                    acdm_times_fit,
                    float(strategy["acdm_time_tolerance_minutes"]),
                )
                group.issue_tags = sorted(set(group.issue_tags))
                continue
            else:
                group.issue_tags.append("ACDM_FLIGHT_AMBIGUOUS")

        if not candidates or candidates[0].score <= 0:
            group.issue_tags.append("MISSING_PLAN")
            group.issue_tags = sorted(set(group.issue_tags))
            continue

        top = candidates[0]
        top_plan = next(plan for plan in plans if plan.id == top.flight_plan_id)
        second_score = candidates[1].score if len(candidates) > 1 else 0
        group.margin = round(top.score - second_score, 2)
        group.confidence = round(min(0.99, max(group.confidence, top.score / 100)), 2)
        if top_plan.plan_end and group.observed_end - top_plan.plan_end > timedelta(
            minutes=strategy["plan_end_overrun_minutes"]
        ):
            group.issue_tags.append("PLAN_END_OVERRUN")

        reported = {
            node.reported_flight_no.upper() for node in group_nodes if node.reported_flight_no
        }
        acdm_reference = acdm_by_code.get(group.temporary_code)
        if acdm_reference:
            reported.add(acdm_reference.flight_no.upper())
        reference_matches_any = (
            any(reported & plan.flight_numbers for plan in plans) if reported else True
        )
        if not reference_matches_any:
            group.issue_tags.append("REFERENCE_CONFLICT")

        if (
            top.score >= strategy["auto_match_threshold"]
            and group.margin >= strategy["minimum_margin"]
            and "REFERENCE_CONFLICT" not in group.issue_tags
            and "PLAN_END_OVERRUN" not in group.issue_tags
            and "COMBINATION_STAND_CONFLICT" not in group.issue_tags
            and "PARENT_STAND_PLAN_CONFLICT" not in group.issue_tags
            and "PARENT_STAND_ACTUAL_OCCUPANCY_CONFLICT" not in group.issue_tags
            and not {
                "ACDM_TIME_OUTLIER",
                "ACDM_PLAN_MISSING",
                "ACDM_FLIGHT_AMBIGUOUS",
            }
            & set(group.issue_tags)
        ):
            group.assignment_status = "MATCHED"
            group.assigned_flight_id = top.flight_plan_id
            top.selected = True
        else:
            group.assignment_status = "NEEDS_REVIEW"
            group.issue_tags.append("AMBIGUOUS_MATCH")

        group.issue_tags = sorted(set(group.issue_tags))

    _apply_sequence_resolution(groups, plans, plan_issues, strategy)
    return groups


def summarize(groups: list[GroupResult], total_nodes: int) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    issue_counts: dict[str, int] = {}
    accounted_nodes = 0
    accounted_node_ids: list[int] = []
    for group in groups:
        status_counts[group.assignment_status] = status_counts.get(group.assignment_status, 0) + 1
        accounted_nodes += len(group.node_ids)
        accounted_node_ids.extend(group.node_ids)
        for tag in group.issue_tags:
            issue_counts[tag] = issue_counts.get(tag, 0) + 1
    return {
        "group_count": len(groups),
        "status_counts": status_counts,
        "issue_counts": issue_counts,
        "total_nodes": total_nodes,
        "accounted_nodes": accounted_nodes,
        "unique_accounted_nodes": len(set(accounted_node_ids)),
        "node_conservation": (
            accounted_nodes == total_nodes and len(set(accounted_node_ids)) == total_nodes
        ),
    }
