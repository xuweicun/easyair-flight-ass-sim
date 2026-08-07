from datetime import datetime

import pytest

from app.engine import (
    AcdmReferenceInput,
    AppearanceInput,
    DEFAULT_TERMINAL_TAIL_EVENT_POLICY,
    NodeInput,
    PlanInput,
    detect_plan_issues,
    run_strategy,
    summarize,
)


def dt(hour: int, minute: int) -> datetime:
    return datetime(2026, 6, 18, hour, minute)


def plan(
    plan_id: int,
    key: str,
    start: tuple[int, int],
    end: tuple[int, int],
    airline: str = "CZ",
    aircraft_type: str = "320",
    aircraft_no: str | None = None,
) -> PlanInput:
    return PlanInput(
        id=plan_id,
        flight_key=key,
        safeguard_code=key,
        inbound_flight_no=f"{airline}{plan_id}01",
        outbound_flight_no=f"{airline}{plan_id}02",
        stand="589",
        plan_start=dt(*start),
        plan_end=dt(*end),
        airline=airline,
        aircraft_type=aircraft_type,
        aircraft_no=aircraft_no,
    )


def node(
    node_id: int,
    event: str,
    time: tuple[int, int],
    stand: str = "589",
    reported_flight_no: str | None = None,
) -> NodeInput:
    return NodeInput(
        id=node_id,
        source_type="algorithm_node",
        event_type=event,
        event_time=dt(*time),
        stand=stand,
        reported_flight_no=reported_flight_no,
    )


def terminal_tail_config(**updates: object) -> dict[str, object]:
    config: dict[str, object] = {
        "terminal_tail_reattach_enabled": True,
        "terminal_tail_lookback_minutes": 480,
        "terminal_tail_max_nodes": 3,
        "terminal_tail_event_policy": {
            key: list(values) for key, values in DEFAULT_TERMINAL_TAIL_EVENT_POLICY.items()
        },
        "combination_stand_families": ["525"],
    }
    config.update(updates)
    return config


def parent_guard_config(**updates: object) -> dict[str, object]:
    config: dict[str, object] = {
        "combination_parent_guard_enabled": True,
        "combination_stand_families": ["525"],
        "open_occupancy_timeout_minutes": 480,
    }
    config.update(updates)
    return config


def test_end_nodes_prefer_previous_flight_over_nearest_next_start() -> None:
    plans = [
        plan(1, "PREVIOUS", (10, 40), (13, 10), "CZ"),
        plan(2, "NEXT", (13, 0), (16, 20), "MU", "321"),
    ]
    nodes = [
        node(1, "AircraftEntry", (10, 55)),
        node(2, "CargoDoorClose", (12, 58)),
        node(3, "AircraftBeginsTaxi", (13, 7)),
        node(4, "AircraftLeave", (13, 8)),
        node(5, "TowEnd", (13, 9)),
    ]

    groups = run_strategy(airport_code="XIY", plans=plans, nodes=nodes)

    assert len(groups) == 1
    assert groups[0].assignment_status == "MATCHED"
    assert groups[0].assigned_flight_id == 1
    assert groups[0].candidates[0].score > groups[0].candidates[1].score


def test_missing_plan_still_creates_unassigned_temporary_group() -> None:
    nodes = [
        node(1, "AircraftEntry", (8, 0), "963"),
        node(2, "BridgeDocked", (8, 10), "963"),
        node(3, "AircraftLeave", (10, 40), "963"),
    ]

    groups = run_strategy(airport_code="XIY", plans=[], nodes=nodes)

    assert groups[0].temporary_code.startswith("TMP-XIY-963-")
    assert groups[0].assignment_status == "UNASSIGNED"
    assert "MISSING_PLAN" in groups[0].issue_tags
    assert summarize(groups, len(nodes))["node_conservation"] is True


def test_invalid_year_candidate_is_retained_for_audit_but_cannot_be_selected() -> None:
    invalid_plan = PlanInput(
        id=2076,
        flight_key="INVALID-YEAR",
        safeguard_code="VALID-BUSINESS-ID-2076",
        inbound_flight_no="OQ2075",
        outbound_flight_no="OQ2076",
        stand="589",
        plan_start=datetime(2076, 6, 18, 10, 0),
        plan_end=datetime(2076, 6, 18, 12, 0),
    )
    nodes = [node(1, "AircraftEntry", (10, 0)), node(2, "AircraftLeave", (12, 0))]

    group = run_strategy(
        airport_code="XIY",
        plans=[invalid_plan],
        nodes=nodes,
        config={"candidate_radius_hours": 500_000},
    )[0]

    assert group.assignment_status == "UNASSIGNED"
    assert group.assigned_flight_id is None
    assert group.candidates[0].excluded_reason == "计划年份异常"
    assert "INVALID_YEAR" in group.issue_tags


def test_actual_end_over_twenty_minutes_after_plan_is_flagged() -> None:
    plans = [plan(1, "LATE-END", (10, 0), (12, 0))]
    nodes = [node(1, "AircraftEntry", (10, 5)), node(2, "AircraftLeave", (12, 21))]

    groups = run_strategy(airport_code="XIY", plans=plans, nodes=nodes)

    assert "PLAN_END_OVERRUN" in groups[0].issue_tags


def test_time_window_gets_partial_credit_when_start_matches_but_end_is_late() -> None:
    plans = [plan(1, "PARTIAL-WINDOW", (10, 0), (12, 0))]
    nodes = [node(1, "AircraftEntry", (10, 3)), node(2, "AircraftLeave", (13, 2))]

    groups = run_strategy(airport_code="XIY", plans=plans, nodes=nodes)

    time_score = groups[0].candidates[0].breakdown["time_window"]
    assert 0 < time_score < 25
    assert groups[0].assignment_status == "NEEDS_REVIEW"
    assert "PLAN_END_OVERRUN" in groups[0].issue_tags


def test_sequence_resolves_only_when_plan_and_node_ranges_overlap() -> None:
    plans = [
        plan(1, "ANCHOR", (8, 0), (9, 0)),
        plan(2, "NEXT", (9, 20), (12, 0)),
    ]
    nodes = [
        node(1, "AircraftEntry", (8, 0)),
        node(2, "AircraftLeave", (9, 0)),
        node(3, "AircraftEntry", (9, 45)),
        node(4, "AircraftLeave", (10, 15)),
    ]

    groups = run_strategy(
        airport_code="XIY",
        plans=plans,
        nodes=nodes,
        config={
            "sequence_resolution_enabled": True,
            "time_decay_minutes": 180,
            "auto_match_threshold": 85,
        },
    )

    assert groups[0].assignment_status == "MATCHED"
    assert groups[0].assigned_flight_id == 1
    assert groups[1].assignment_status == "MATCHED"
    assert groups[1].assigned_flight_id == 2
    assert groups[1].candidates[0].breakdown["sequence_order"] == 40
    assert groups[1].lineage["sequence_resolution"]["time_overlap"] is True


def test_sequence_is_rejected_when_ranges_only_touch_at_boundary() -> None:
    plans = [
        plan(1, "ANCHOR", (8, 0), (9, 0)),
        plan(2, "NEXT", (9, 30), (10, 30)),
    ]
    nodes = [
        node(1, "AircraftEntry", (8, 0)),
        node(2, "AircraftLeave", (9, 0)),
        node(3, "AircraftEntry", (9, 0)),
        node(4, "AircraftLeave", (9, 30)),
    ]

    groups = run_strategy(
        airport_code="XIY",
        plans=plans,
        nodes=nodes,
        config={
            "sequence_resolution_enabled": True,
            "time_decay_minutes": 180,
            "auto_match_threshold": 85,
        },
    )

    assert groups[0].assignment_status == "MATCHED"
    assert groups[1].assignment_status == "NEEDS_REVIEW"
    assert "sequence_order" not in groups[1].candidates[0].breakdown
    assert groups[1].lineage["sequence_resolution"]["state"] == "rejected_no_time_overlap"


def test_aircraft_start_and_entry_stay_in_the_same_new_group() -> None:
    nodes = [
        node(1, "AircraftEntry", (8, 0)),
        node(2, "AircraftLeave", (8, 50)),
        node(3, "TowEnd", (8, 52)),
        node(4, "AircraftStart", (9, 1)),
        node(5, "GuideCarStart", (9, 2)),
        node(6, "AircraftEntry", (9, 3)),
        node(7, "PlaceChockEnd", (9, 4)),
    ]

    groups = run_strategy(airport_code="XIY", plans=[], nodes=nodes)

    assert len(groups) == 2
    assert groups[0].node_ids == [1, 2, 3]
    assert groups[1].node_ids == [4, 5, 6, 7]
    assert summarize(groups, len(nodes))["node_conservation"] is True


def test_tow_end_and_aircraft_leave_stay_in_previous_group_in_either_order() -> None:
    nodes = [
        node(1, "AircraftEntry", (8, 0)),
        node(2, "TowEnd", (8, 50)),
        node(3, "AircraftLeave", (8, 50)),
        node(4, "GuideCarStart", (9, 0)),
        node(5, "AircraftStart", (9, 1)),
        node(6, "AircraftEntry", (9, 2)),
    ]

    groups = run_strategy(airport_code="XIY", plans=[], nodes=nodes)

    assert [group.node_ids for group in groups] == [[1, 2, 3], [4, 5, 6]]


def test_aircraft_entry_still_splits_when_start_event_is_missing() -> None:
    nodes = [
        node(1, "FlightFoodEnd", (9, 0)),
        node(2, "AircraftEntry", (9, 2)),
        node(3, "PlaceChockEnd", (9, 3)),
    ]

    groups = run_strategy(airport_code="XIY", plans=[], nodes=nodes)

    assert [group.node_ids for group in groups] == [[1], [2, 3]]


def test_entry_uses_only_recent_approach_start_and_isolates_stale_marker() -> None:
    nodes = [
        node(1, "TowEnd", (8, 0)),
        node(2, "GuideCarStart", (8, 10)),
        node(3, "AircraftStart", (11, 0)),
        node(4, "GuideCarStart", (11, 1)),
        node(5, "AircraftEntry", (11, 2)),
    ]

    groups = run_strategy(airport_code="XIY", plans=[], nodes=nodes)

    assert [group.node_ids for group in groups] == [[1], [2], [3, 4, 5]]
    assert groups[1].assignment_status == "UNASSIGNED_FINAL"
    assert "ORPHAN_START_MARKER" in groups[1].issue_tags


def test_long_gap_complete_terminal_tail_reattaches_to_incomplete_previous_group() -> None:
    previous_plan = PlanInput(
        id=5250,
        flight_key="525L-PREVIOUS",
        safeguard_code="525L-PREVIOUS",
        inbound_flight_no="MU2366",
        outbound_flight_no="MU2385",
        stand="525L",
        plan_start=dt(8, 0),
        plan_end=dt(11, 12),
    )
    nodes = [
        node(1, "OpenCabinDoor", (9, 19), "525L"),
        node(2, "LuggageCarBegin", (10, 20), "525L"),
        node(3, "OpenCargoDoor", (11, 0), "525L"),
        node(4, "AircraftBeginsTaxi", (15, 52), "525L"),
        node(5, "TowEnd", (15, 56), "525L"),
        node(6, "AircraftLeave", (15, 56), "525L"),
    ]

    baseline = run_strategy(airport_code="XIY", plans=[previous_plan], nodes=nodes)
    fixed = run_strategy(
        airport_code="XIY",
        plans=[previous_plan],
        nodes=nodes,
        config=terminal_tail_config(),
    )

    assert [group.node_ids for group in baseline] == [[1, 2, 3], [4, 5, 6]]
    assert [group.node_ids for group in fixed] == [[1, 2, 3, 4, 5, 6]]
    assert fixed[0].temporary_code == f"{baseline[0].temporary_code}-M"
    assert "TERMINAL_TAIL_REATTACHED" in fixed[0].issue_tags
    assert fixed[0].lineage["terminal_tail_reattachment"]["evidence"] == (
        "MISSING_PREVIOUS_END_WITH_COMPLETE_TAIL"
    )
    assert len(fixed[0].lineage["terminal_tail_reattachment"]["source_groups"]) == 2
    assert fixed[0].lineage["terminal_tail_reattachment"]["merged_node_id_set_sha256"]
    assert fixed[0].lineage["terminal_tail_reattachment"]["previous_plan_ids"] == [5250]
    assert summarize(fixed, len(nodes))["node_conservation"] is True


def test_terminal_tail_after_leave_requires_one_shared_plan_window() -> None:
    supporting_plan = PlanInput(
        id=5251,
        flight_key="525R-SUPPORT",
        safeguard_code="525R-SUPPORT",
        inbound_flight_no="MU2153",
        outbound_flight_no="MU2153",
        stand="525R",
        plan_start=dt(8, 24),
        plan_end=dt(10, 22),
    )
    nodes = [
        node(1, "AircraftEntry", (8, 30), "525R"),
        node(2, "AircraftLeave", (9, 54), "525R"),
        node(3, "OpenCargoDoor", (9, 56), "525R"),
        node(4, "TowEnd", (9, 57), "525R"),
    ]

    groups = run_strategy(
        airport_code="XIY",
        plans=[supporting_plan],
        nodes=nodes,
        config=terminal_tail_config(),
    )

    assert [group.node_ids for group in groups] == [[1, 2, 3, 4]]
    evidence = groups[0].lineage["terminal_tail_reattachment"]
    assert evidence["evidence"] == "UNIQUE_PLAN_WINDOW"
    assert evidence["shared_plan_ids"] == [5251]


def test_terminal_tail_does_not_cross_a_new_start_boundary() -> None:
    nodes = [
        node(1, "AircraftEntry", (8, 0), "525R"),
        node(2, "OpenCargoDoor", (9, 0), "525R"),
        node(3, "AircraftStart", (13, 0), "525R"),
        node(4, "TowEnd", (13, 2), "525R"),
    ]

    groups = run_strategy(
        airport_code="XIY",
        plans=[],
        nodes=nodes,
        config=terminal_tail_config(),
    )

    assert [group.node_ids for group in groups] == [[1, 2], [3, 4]]
    assert all("TERMINAL_TAIL_REATTACHED" not in group.issue_tags for group in groups)


def test_terminal_tail_does_not_cross_a_tow_start_boundary() -> None:
    nodes = [
        node(1, "AircraftEntry", (8, 0), "525R"),
        node(2, "OpenCargoDoor", (9, 0), "525R"),
        node(3, "TowStart", (13, 0), "525R"),
        node(4, "TowEnd", (13, 2), "525R"),
    ]

    groups = run_strategy(
        airport_code="XIY",
        plans=[],
        nodes=nodes,
        config=terminal_tail_config(),
    )

    assert [group.node_ids for group in groups] == [[1, 2], [3, 4]]


def test_terminal_tail_never_absorbs_an_invalid_node() -> None:
    nodes = [
        node(1, "AircraftEntry", (8, 0), "525R"),
        node(2, "OpenCargoDoor", (9, 0), "525R"),
        NodeInput(
            id=3,
            source_type="algorithm_node",
            event_type="TowEnd",
            event_time=dt(12, 0),
            stand="525R",
            is_anomaly=True,
        ),
    ]

    groups = run_strategy(
        airport_code="XIY",
        plans=[],
        nodes=nodes,
        config=terminal_tail_config(),
    )

    assert [group.node_ids for group in groups] == [[1, 2], [3]]
    assert groups[1].assignment_status == "DATA_ERROR"


def test_ordinary_gap_over_180_minutes_still_splits_when_tail_rule_is_enabled() -> None:
    nodes = [
        node(1, "AircraftEntry", (8, 0), "525R"),
        node(2, "OpenCargoDoor", (9, 0), "525R"),
        node(3, "FuelStart", (12, 1), "525R"),
        node(4, "FuelEnd", (12, 5), "525R"),
    ]

    groups = run_strategy(
        airport_code="XIY",
        plans=[],
        nodes=nodes,
        config=terminal_tail_config(),
    )

    assert [group.node_ids for group in groups] == [[1, 2], [3, 4]]


def test_terminal_tail_does_not_cross_parent_side_resource_occupancy() -> None:
    nodes = [
        node(1, "AircraftEntry", (8, 0), "525"),
        node(2, "OpenCargoDoor", (8, 30), "525"),
        node(3, "AircraftEntry", (10, 0), "525L"),
        node(4, "AircraftLeave", (11, 0), "525L"),
        node(5, "AircraftLeave", (12, 20), "525"),
        node(6, "TowEnd", (12, 21), "525"),
    ]

    groups = run_strategy(
        airport_code="XIY",
        plans=[],
        nodes=nodes,
        config=terminal_tail_config(),
    )

    assert [group.node_ids for group in groups if group.stand == "525"] == [[1, 2], [5, 6]]
    assert all("TERMINAL_TAIL_REATTACHED" not in group.issue_tags for group in groups)


def test_terminal_tail_does_not_cross_side_work_without_a_start_marker() -> None:
    nodes = [
        node(1, "AircraftEntry", (8, 0), "525"),
        node(2, "OpenCargoDoor", (8, 30), "525"),
        node(3, "FuelStart", (10, 0), "525L"),
        node(4, "FuelEnd", (11, 0), "525L"),
        node(5, "AircraftLeave", (12, 20), "525"),
        node(6, "TowEnd", (12, 21), "525"),
    ]

    groups = run_strategy(
        airport_code="XIY",
        plans=[],
        nodes=nodes,
        config=terminal_tail_config(),
    )

    assert [group.node_ids for group in groups if group.stand == "525"] == [[1, 2], [5, 6]]
    assert all("TERMINAL_TAIL_REATTACHED" not in group.issue_tags for group in groups)


def test_plan_touching_only_group_endpoints_blocks_terminal_tail_merge() -> None:
    intervening_plan = PlanInput(
        id=5255,
        flight_key="525R-INTERVENING",
        safeguard_code="525R-INTERVENING",
        inbound_flight_no="MU5255",
        outbound_flight_no="MU5256",
        stand="525R",
        plan_start=dt(9, 0),
        plan_end=dt(12, 1),
    )
    nodes = [
        node(1, "AircraftEntry", (8, 0), "525R"),
        node(2, "OpenCargoDoor", (9, 0), "525R"),
        node(3, "AircraftLeave", (12, 1), "525R"),
        node(4, "TowEnd", (12, 2), "525R"),
    ]

    groups = run_strategy(
        airport_code="XIY",
        plans=[intervening_plan],
        nodes=nodes,
        config=terminal_tail_config(),
    )

    assert [group.node_ids for group in groups] == [[1, 2], [3, 4]]
    assert all("TERMINAL_TAIL_REATTACHED" not in group.issue_tags for group in groups)


def test_second_plan_slightly_overlapping_previous_group_blocks_tail_merge() -> None:
    plans = [
        PlanInput(
            id=5258,
            flight_key="525R-SHARED",
            safeguard_code="525R-SHARED",
            inbound_flight_no="MU1",
            outbound_flight_no="MU2",
            stand="525R",
            plan_start=dt(7, 0),
            plan_end=dt(14, 0),
        ),
        PlanInput(
            id=5259,
            flight_key="525R-GAP",
            safeguard_code="525R-GAP",
            inbound_flight_no="CZ1",
            outbound_flight_no="CZ2",
            stand="525R",
            plan_start=dt(8, 59),
            plan_end=dt(12, 1),
        ),
    ]
    nodes = [
        node(1, "AircraftEntry", (8, 0), "525R"),
        node(2, "OpenCargoDoor", (9, 0), "525R"),
        node(3, "AircraftLeave", (12, 1), "525R"),
        node(4, "TowEnd", (12, 2), "525R"),
    ]

    groups = run_strategy(
        airport_code="XIY",
        plans=plans,
        nodes=nodes,
        config=terminal_tail_config(),
    )

    assert [group.node_ids for group in groups] == [[1, 2], [3, 4]]
    assert all("TERMINAL_TAIL_REATTACHED" not in group.issue_tags for group in groups)


def test_terminal_tail_does_not_merge_conflicting_reported_flight_numbers() -> None:
    supporting_plan = PlanInput(
        id=5256,
        flight_key="525R-SUPPORT",
        safeguard_code="525R-SUPPORT",
        inbound_flight_no="MU1",
        outbound_flight_no="MU1",
        stand="525R",
        plan_start=dt(7, 0),
        plan_end=dt(14, 0),
    )
    nodes = [
        node(1, "AircraftEntry", (8, 0), "525R", "MU1"),
        node(2, "OpenCargoDoor", (8, 30), "525R", "MU1"),
        node(3, "AircraftLeave", (12, 0), "525R", "CZ9"),
        node(4, "TowEnd", (12, 1), "525R", "CZ9"),
    ]

    groups = run_strategy(
        airport_code="XIY",
        plans=[supporting_plan],
        nodes=nodes,
        config=terminal_tail_config(),
    )

    assert [group.node_ids for group in groups] == [[1, 2], [3, 4]]
    assert "TERMINAL_TAIL_REFERENCE_CONFLICT" in groups[1].issue_tags


def test_terminal_tail_does_not_merge_one_number_conflicting_with_shared_plan() -> None:
    supporting_plan = PlanInput(
        id=5266,
        flight_key="525R-SUPPORT",
        safeguard_code="525R-SUPPORT",
        inbound_flight_no="MU1",
        outbound_flight_no="MU2",
        stand="525R",
        plan_start=dt(7, 0),
        plan_end=dt(14, 0),
    )
    nodes = [
        node(1, "AircraftEntry", (8, 0), "525R"),
        node(2, "OpenCargoDoor", (8, 30), "525R"),
        node(3, "AircraftLeave", (12, 0), "525R", "CZ9"),
        node(4, "TowEnd", (12, 1), "525R", "CZ9"),
    ]

    groups = run_strategy(
        airport_code="XIY",
        plans=[supporting_plan],
        nodes=nodes,
        config=terminal_tail_config(),
    )

    assert [group.node_ids for group in groups] == [[1, 2], [3, 4]]
    assert "TERMINAL_TAIL_REFERENCE_CONFLICT" in groups[1].issue_tags


def test_terminal_tail_accepts_inbound_and_outbound_numbers_from_one_plan() -> None:
    supporting_plan = PlanInput(
        id=5257,
        flight_key="525R-SUPPORT",
        safeguard_code="525R-SUPPORT",
        inbound_flight_no="MU1",
        outbound_flight_no="MU2",
        stand="525R",
        plan_start=dt(7, 0),
        plan_end=dt(14, 0),
    )
    nodes = [
        node(1, "AircraftEntry", (8, 0), "525R", "MU1"),
        node(2, "OpenCargoDoor", (8, 30), "525R", "MU1"),
        node(3, "AircraftLeave", (12, 0), "525R", "MU2"),
        node(4, "TowEnd", (12, 1), "525R", "MU2"),
    ]

    groups = run_strategy(
        airport_code="XIY",
        plans=[supporting_plan],
        nodes=nodes,
        config=terminal_tail_config(),
    )

    assert [group.node_ids for group in groups] == [[1, 2, 3, 4]]
    assert "TERMINAL_TAIL_REFERENCE_CONFLICT" not in groups[0].issue_tags


def test_complete_terminal_pair_stays_separate_when_two_plans_share_the_window() -> None:
    plans = [
        PlanInput(
            id=1,
            flight_key="A",
            safeguard_code="A",
            inbound_flight_no="MU1",
            outbound_flight_no="MU2",
            stand="525R",
            plan_start=dt(7, 0),
            plan_end=dt(14, 0),
        ),
        PlanInput(
            id=2,
            flight_key="B",
            safeguard_code="B",
            inbound_flight_no="MU3",
            outbound_flight_no="MU4",
            stand="525R",
            plan_start=dt(7, 30),
            plan_end=dt(14, 30),
        ),
    ]
    nodes = [
        node(1, "AircraftEntry", (8, 0), "525R"),
        node(2, "OpenCargoDoor", (8, 30), "525R"),
        node(3, "AircraftLeave", (12, 0), "525R"),
        node(4, "TowEnd", (12, 1), "525R"),
    ]

    groups = run_strategy(
        airport_code="XIY",
        plans=plans,
        nodes=nodes,
        config=terminal_tail_config(),
    )

    assert [group.node_ids for group in groups] == [[1, 2], [3, 4]]


def test_immutable_sent_nodes_are_not_changed_by_terminal_tail_rule() -> None:
    nodes = [
        node(1, "AircraftEntry", (8, 0), "525R"),
        node(2, "OpenCargoDoor", (8, 30), "525R"),
        node(3, "AircraftLeave", (12, 0), "525R"),
        node(4, "TowEnd", (12, 1), "525R"),
    ]
    baseline = run_strategy(airport_code="XIY", plans=[], nodes=nodes)

    groups = run_strategy(
        airport_code="XIY",
        plans=[],
        nodes=nodes,
        config=terminal_tail_config(),
        protected_node_ids=set(baseline[0].node_ids),
    )

    assert [group.node_ids for group in groups] == [[1, 2], [3, 4]]
    assert groups[0].temporary_code == baseline[0].temporary_code


def test_immutable_sent_merged_group_is_restored_without_resplitting() -> None:
    nodes = [
        node(1, "AircraftEntry", (8, 0), "525R"),
        node(2, "OpenCargoDoor", (8, 30), "525R"),
        node(3, "AircraftLeave", (12, 0), "525R"),
        node(4, "TowEnd", (12, 1), "525R"),
    ]
    sent = run_strategy(
        airport_code="XIY",
        plans=[],
        nodes=nodes,
        config=terminal_tail_config(),
    )[0]
    sent.assignment_status = "MATCHED"
    sent.assigned_flight_id = 5256

    groups = run_strategy(
        airport_code="XIY",
        plans=[],
        nodes=nodes,
        config=terminal_tail_config(),
        immutable_groups=[sent],
    )

    assert len(groups) == 1
    assert groups[0].temporary_code == sent.temporary_code
    assert groups[0].node_ids == sent.node_ids
    assert groups[0].assignment_status == "MATCHED"
    assert groups[0].assigned_flight_id == 5256
    assert groups[0].lineage["immutable_sent_replay"]["node_id_set_sha256"]


def test_tail_rule_requires_event_policy_in_the_saved_strategy() -> None:
    with pytest.raises(ValueError, match="complete versioned event policy"):
        run_strategy(
            airport_code="XIY",
            plans=[],
            nodes=[node(1, "TowEnd", (8, 0), "525R")],
            config={"terminal_tail_reattach_enabled": True},
        )


def test_tail_rule_rejects_policy_that_moves_tow_start_into_tail_events() -> None:
    config = terminal_tail_config()
    policy = config["terminal_tail_event_policy"]
    assert isinstance(policy, dict)
    policy["group_start_events"].remove("TowStart")
    policy["allowed_tail_events"].append("TowStart")

    with pytest.raises(ValueError, match="cannot remove required boundary events"):
        run_strategy(
            airport_code="XIY",
            plans=[],
            nodes=[node(1, "TowEnd", (8, 0), "525R")],
            config=config,
        )


def test_parent_stand_nodes_are_flagged_when_only_side_plans_exist_that_day() -> None:
    side_plan = PlanInput(
        id=5252,
        flight_key="525L-ONLY",
        safeguard_code="525L-ONLY",
        inbound_flight_no="MU5251",
        outbound_flight_no="MU5252",
        stand="525L",
        plan_start=dt(10, 0),
        plan_end=dt(12, 0),
    )
    nodes = [
        node(1, "AircraftEntry", (10, 5), "525"),
        node(2, "AircraftLeave", (11, 55), "525"),
    ]

    group = run_strategy(
        airport_code="XIY",
        plans=[side_plan],
        nodes=nodes,
        config=parent_guard_config(),
    )[0]

    assert group.assignment_status == "UNASSIGNED"
    assert group.assigned_flight_id is None
    assert "PARENT_STAND_CODE_WITHOUT_PLAN" in group.issue_tags


def test_parent_stand_guard_is_disabled_by_default() -> None:
    side_plan = PlanInput(
        id=5260,
        flight_key="525L-ONLY",
        safeguard_code="525L-ONLY",
        inbound_flight_no="MU5260",
        outbound_flight_no="MU5261",
        stand="525L",
        plan_start=dt(10, 0),
        plan_end=dt(12, 0),
    )
    nodes = [
        node(1, "AircraftEntry", (10, 5), "525"),
        node(2, "AircraftLeave", (11, 55), "525"),
    ]

    group = run_strategy(airport_code="XIY", plans=[side_plan], nodes=nodes)[0]

    assert "PARENT_STAND_CODE_WITHOUT_PLAN" not in group.issue_tags


def test_parent_stand_remains_legal_when_same_day_parent_plan_exists() -> None:
    parent_plan = PlanInput(
        id=5253,
        flight_key="525-PARENT",
        safeguard_code="525-PARENT",
        inbound_flight_no="MU5253",
        outbound_flight_no="MU5254",
        stand="525",
        plan_start=dt(10, 0),
        plan_end=dt(12, 0),
    )
    nodes = [
        node(1, "AircraftEntry", (10, 5), "525"),
        node(2, "AircraftLeave", (11, 55), "525"),
    ]

    group = run_strategy(
        airport_code="XIY",
        plans=[parent_plan],
        nodes=nodes,
        config=parent_guard_config(),
    )[0]

    assert group.assigned_flight_id == 5253
    assert "PARENT_STAND_CODE_WITHOUT_PLAN" not in group.issue_tags


def test_parent_stand_plan_cannot_auto_match_during_actual_side_occupancy() -> None:
    parent_plan = PlanInput(
        id=5253,
        flight_key="525-PARENT",
        safeguard_code="525-PARENT",
        inbound_flight_no="MU5253",
        outbound_flight_no="MU5254",
        stand="525",
        plan_start=dt(10, 0),
        plan_end=dt(12, 0),
    )
    nodes = [
        node(1, "AircraftEntry", (10, 5), "525"),
        node(2, "AircraftLeave", (11, 55), "525"),
        node(3, "FuelStart", (10, 30), "525L"),
        node(4, "FuelEnd", (11, 30), "525L"),
    ]

    parent_group = next(
        group
        for group in run_strategy(
            airport_code="XIY",
            plans=[parent_plan],
            nodes=nodes,
            config=parent_guard_config(),
        )
        if group.stand == "525"
    )

    assert parent_group.assignment_status == "NEEDS_REVIEW"
    assert parent_group.assigned_flight_id is None
    assert "PARENT_STAND_ACTUAL_OCCUPANCY_CONFLICT" in parent_group.issue_tags


def test_open_side_occupancy_without_end_blocks_parent_stand_until_timeout() -> None:
    parent_plan = PlanInput(
        id=5262,
        flight_key="525-PARENT",
        safeguard_code="525-PARENT",
        inbound_flight_no="MU5262",
        outbound_flight_no="MU5263",
        stand="525",
        plan_start=dt(10, 30),
        plan_end=dt(12, 0),
    )
    nodes = [
        node(1, "AircraftEntry", (10, 0), "525L"),
        node(2, "OpenCargoDoor", (10, 10), "525L"),
        node(3, "AircraftEntry", (10, 30), "525"),
        node(4, "AircraftLeave", (11, 55), "525"),
    ]

    parent_group = next(
        group
        for group in run_strategy(
            airport_code="XIY",
            plans=[parent_plan],
            nodes=nodes,
            config=parent_guard_config(),
        )
        if group.stand == "525"
    )

    assert parent_group.assignment_status == "NEEDS_REVIEW"
    assert parent_group.assigned_flight_id is None
    assert "PARENT_STAND_ACTUAL_OCCUPANCY_CONFLICT" in parent_group.issue_tags


def test_open_side_occupancy_expires_after_configured_timeout() -> None:
    parent_plan = PlanInput(
        id=5264,
        flight_key="525-PARENT",
        safeguard_code="525-PARENT",
        inbound_flight_no="MU5264",
        outbound_flight_no="MU5265",
        stand="525",
        plan_start=dt(10, 0),
        plan_end=dt(12, 0),
    )
    nodes = [
        node(1, "AircraftEntry", (1, 0), "525L"),
        node(2, "OpenCargoDoor", (1, 10), "525L"),
        node(3, "AircraftEntry", (10, 0), "525"),
        node(4, "AircraftLeave", (11, 55), "525"),
    ]

    parent_group = next(
        group
        for group in run_strategy(
            airport_code="XIY",
            plans=[parent_plan],
            nodes=nodes,
            config=parent_guard_config(open_occupancy_timeout_minutes=480),
        )
        if group.stand == "525"
    )

    assert parent_group.assignment_status == "MATCHED"
    assert parent_group.assigned_flight_id == 5264
    assert "PARENT_STAND_ACTUAL_OCCUPANCY_CONFLICT" not in parent_group.issue_tags


def test_later_terminal_boundary_closes_open_side_occupancy() -> None:
    parent_plan = PlanInput(
        id=5268,
        flight_key="525-PARENT",
        safeguard_code="525-PARENT",
        inbound_flight_no="MU5268",
        outbound_flight_no="MU5269",
        stand="525",
        plan_start=dt(5, 0),
        plan_end=dt(6, 0),
    )
    nodes = [
        node(1, "AircraftEntry", (1, 0), "525L"),
        node(2, "OpenCargoDoor", (1, 10), "525L"),
        node(3, "TowEnd", (4, 30), "525L"),
        node(4, "AircraftEntry", (5, 0), "525"),
        node(5, "AircraftLeave", (5, 55), "525"),
    ]

    parent_group = next(
        group
        for group in run_strategy(
            airport_code="XIY",
            plans=[parent_plan],
            nodes=nodes,
            config=parent_guard_config(),
        )
        if group.stand == "525"
    )

    assert parent_group.assignment_status == "MATCHED"
    assert parent_group.assigned_flight_id == 5268
    assert "PARENT_STAND_ACTUAL_OCCUPANCY_CONFLICT" not in parent_group.issue_tags


def test_conflicting_parent_plan_cannot_auto_match() -> None:
    parent_plan = PlanInput(
        id=5253,
        flight_key="525-PARENT",
        safeguard_code="525-PARENT",
        inbound_flight_no="MU5253",
        outbound_flight_no="MU5254",
        stand="525",
        plan_start=dt(10, 0),
        plan_end=dt(12, 0),
    )
    side_plan = PlanInput(
        id=5254,
        flight_key="525L-SIDE",
        safeguard_code="525L-SIDE",
        inbound_flight_no="MU5255",
        outbound_flight_no="MU5256",
        stand="525L",
        plan_start=dt(10, 30),
        plan_end=dt(11, 30),
    )
    nodes = [
        node(1, "AircraftEntry", (10, 5), "525"),
        node(2, "AircraftLeave", (11, 55), "525"),
    ]

    group = run_strategy(
        airport_code="XIY",
        plans=[parent_plan, side_plan],
        nodes=nodes,
        config=parent_guard_config(),
    )[0]

    assert group.assignment_status == "NEEDS_REVIEW"
    assert group.assigned_flight_id is None
    assert "COMBINATION_STAND_CONFLICT" in group.issue_tags
    assert "PARENT_STAND_PLAN_CONFLICT" in group.issue_tags


def test_node_conservation_detects_offsetting_duplicate_and_missing_ids() -> None:
    groups = run_strategy(
        airport_code="XIY",
        plans=[],
        nodes=[
            node(1, "AircraftEntry", (8, 0)),
            node(2, "AircraftLeave", (9, 0)),
            node(3, "AircraftEntry", (10, 0)),
            node(4, "AircraftLeave", (11, 0)),
        ],
    )
    groups[1].node_ids[0] = 1

    metrics = summarize(groups, 4)

    assert metrics["accounted_nodes"] == 4
    assert metrics["unique_accounted_nodes"] == 3
    assert metrics["node_conservation"] is False


def test_high_confidence_appearance_breaks_an_ambiguous_tie() -> None:
    plans = [
        plan(1, "CZ-FLIGHT", (10, 0), (13, 0), "CZ", "320"),
        plan(2, "MU-FLIGHT", (10, 0), (13, 0), "MU", "321"),
    ]
    nodes = [node(1, "AircraftEntry", (10, 10)), node(2, "AircraftLeave", (12, 50))]
    initial = run_strategy(airport_code="XIY", plans=plans, nodes=nodes)
    feature = AppearanceInput(
        temporary_code=initial[0].temporary_code,
        airline="MU",
        aircraft_type="321",
        confidence=0.95,
    )

    rerun = run_strategy(airport_code="XIY", plans=plans, nodes=nodes, appearances=[feature])

    assert rerun[0].candidates[0].flight_plan_id == 2
    assert rerun[0].candidates[0].breakdown["appearance_airline"] > 0
    assert rerun[0].candidates[0].breakdown["appearance_type"] > 0


def test_registration_ocr_similarity_breaks_tie_without_hard_rejection() -> None:
    plans = [
        plan(1, "CLOSER", (10, 0), (13, 0), aircraft_no="B53B"),
        plan(2, "FARTHER", (10, 0), (13, 0), aircraft_no="B524"),
    ]
    nodes = [node(1, "AircraftEntry", (10, 10)), node(2, "AircraftLeave", (12, 50))]
    initial = run_strategy(airport_code="XIY", plans=plans, nodes=nodes)
    feature = AppearanceInput(
        temporary_code=initial[0].temporary_code,
        airline=None,
        aircraft_type=None,
        confidence=0.9,
        aircraft_registration="B533",
        registration_confidence=0.8,
    )

    group = run_strategy(airport_code="XIY", plans=plans, nodes=nodes, appearances=[feature])[0]

    assert group.candidates[0].flight_plan_id == 1
    closer = group.candidates[0].breakdown
    farther = group.candidates[1].breakdown
    assert closer["registration_similarity"] > farther["registration_similarity"]
    assert closer["appearance_registration"] > farther["appearance_registration"]


def test_acdm_confirms_unique_flight_without_changing_candidate_score() -> None:
    plans = [
        plan(1, "CZ-FLIGHT", (10, 0), (13, 0), "CZ", "320"),
        plan(2, "MU-FLIGHT", (12, 0), (15, 0), "MU", "321"),
    ]
    nodes = [node(1, "AircraftEntry", (10, 10)), node(2, "AircraftLeave", (12, 50))]
    initial = run_strategy(airport_code="XIY", plans=plans, nodes=nodes)
    assert initial[0].candidates[0].flight_plan_id == 1
    initial_scores = {
        candidate.flight_plan_id: candidate.score for candidate in initial[0].candidates
    }
    reference = AcdmReferenceInput(
        temporary_code=initial[0].temporary_code,
        flight_no="MU201",
        aircraft_entry_time=dt(10, 10),
        chock_on_time=dt(10, 12),
    )

    rerun = run_strategy(
        airport_code="XIY",
        plans=plans,
        nodes=nodes,
        acdm_references=[reference],
    )

    assert rerun[0].assignment_status == "MATCHED_REFERENCE"
    assert rerun[0].assigned_flight_id == 2
    rerun_scores = {candidate.flight_plan_id: candidate.score for candidate in rerun[0].candidates}
    assert rerun_scores == initial_scores
    assert all("reference" not in candidate.breakdown for candidate in rerun[0].candidates)


def test_acdm_same_flight_number_prefers_same_stand_without_scoring_it() -> None:
    same_stand = plan(1, "SAME-STAND", (10, 0), (13, 0), "MU", "319")
    cross_stand = PlanInput(
        **{
            **plan(2, "CROSS-STAND", (10, 0), (13, 0), "MU", "C919").__dict__,
            "stand": "523",
            "inbound_flight_no": "MU2160",
            "outbound_flight_no": "MU2336",
        }
    )
    same_stand = PlanInput(
        **{
            **same_stand.__dict__,
            "inbound_flight_no": "MU2336",
            "outbound_flight_no": "MU2145",
        }
    )
    nodes = [node(1, "AircraftEntry", (10, 10)), node(2, "AircraftLeave", (12, 50))]
    initial = run_strategy(airport_code="XIY", plans=[same_stand, cross_stand], nodes=nodes)
    reference = AcdmReferenceInput(
        temporary_code=initial[0].temporary_code,
        flight_no="MU2336",
        aircraft_entry_time=dt(10, 10),
    )

    group = run_strategy(
        airport_code="XIY",
        plans=[same_stand, cross_stand],
        nodes=nodes,
        acdm_references=[reference],
    )[0]
    scores = {candidate.flight_plan_id: candidate for candidate in group.candidates}

    assert "reference" not in scores[1].breakdown
    assert 2 not in scores
    assert group.assigned_flight_id == 1


def test_acdm_can_recover_cross_stand_plan_when_no_same_stand_plan_exists() -> None:
    cross_stand = PlanInput(
        **{
            **plan(2, "CROSS-STAND", (10, 0), (13, 0), "MU", "C919").__dict__,
            "stand": "523",
            "outbound_flight_no": "MU2336",
        }
    )
    nodes = [node(1, "AircraftEntry", (10, 10)), node(2, "AircraftLeave", (12, 50))]
    initial = run_strategy(airport_code="XIY", plans=[cross_stand], nodes=nodes)
    reference = AcdmReferenceInput(
        temporary_code=initial[0].temporary_code,
        flight_no="MU2336",
        aircraft_entry_time=dt(10, 10),
    )

    group = run_strategy(
        airport_code="XIY",
        plans=[cross_stand],
        nodes=nodes,
        acdm_references=[reference],
    )[0]

    assert [candidate.flight_plan_id for candidate in group.candidates] == [2]
    assert group.assigned_flight_id == 2


def test_acdm_time_outlier_does_not_override_reliable_flight_number() -> None:
    plans = [plan(1, "CZ-FLIGHT", (10, 0), (13, 0), "CZ", "320")]
    nodes = [node(1, "AircraftEntry", (10, 10)), node(2, "AircraftLeave", (12, 50))]
    initial = run_strategy(airport_code="XIY", plans=plans, nodes=nodes)
    reference = AcdmReferenceInput(
        temporary_code=initial[0].temporary_code,
        flight_no="CZ101",
        aircraft_entry_time=dt(14, 0),
        chock_on_time=dt(14, 2),
    )

    rerun = run_strategy(
        airport_code="XIY",
        plans=plans,
        nodes=nodes,
        acdm_references=[reference],
    )

    assert rerun[0].assignment_status == "MATCHED_REFERENCE"
    assert rerun[0].assigned_flight_id == 1
    assert "ACDM_TIME_OUTLIER" in rerun[0].issue_tags


def test_acdm_entry_is_absolute_occupancy_start_and_intermediate_order_is_non_blocking() -> None:
    plans = [plan(1, "CZ-FLIGHT", (10, 0), (13, 0), "CZ", "320")]
    nodes = [node(1, "AircraftEntry", (10, 10)), node(2, "AircraftLeave", (12, 50))]
    initial = run_strategy(airport_code="XIY", plans=plans, nodes=nodes)
    reference = AcdmReferenceInput(
        temporary_code=initial[0].temporary_code,
        flight_no="CZ101",
        aircraft_entry_time=dt(10, 8),
        chock_on_time=dt(10, 6),
        stand_release_time=dt(12, 55),
    )

    group = run_strategy(airport_code="XIY", plans=plans, nodes=nodes, acdm_references=[reference])[
        0
    ]

    occupancy = group.lineage["stand_occupancy"]
    assert occupancy["start_time"] == dt(10, 8).isoformat()
    assert occupancy["start_source"] == "acdm_aircraft_entry"
    assert occupancy["end_time"] == dt(12, 50).isoformat()
    assert occupancy["end_source"] == "algorithm_terminal"
    assert group.assignment_status == "MATCHED_REFERENCE"
    assert "ACDM_NODE_ORDER_ANOMALY" in group.issue_tags


def test_acdm_release_fills_occupancy_end_when_algorithm_has_no_terminal_node() -> None:
    plans = [plan(1, "CZ-FLIGHT", (10, 0), (13, 0), "CZ", "320")]
    nodes = [node(1, "AircraftEntry", (10, 10)), node(2, "CargoDoorClose", (12, 40))]
    initial = run_strategy(airport_code="XIY", plans=plans, nodes=nodes)
    reference = AcdmReferenceInput(
        temporary_code=initial[0].temporary_code,
        flight_no="CZ101",
        aircraft_entry_time=dt(10, 8),
        stand_release_time=dt(12, 55),
    )

    group = run_strategy(airport_code="XIY", plans=plans, nodes=nodes, acdm_references=[reference])[
        0
    ]

    occupancy = group.lineage["stand_occupancy"]
    assert occupancy["end_time"] == dt(12, 55).isoformat()
    assert occupancy["end_source"] == "acdm_stand_release"


def test_acdm_confirms_diversion_flight_when_plan_is_missing() -> None:
    nodes = [node(1, "AircraftEntry", (10, 10)), node(2, "AircraftLeave", (12, 50))]
    initial = run_strategy(airport_code="XIY", plans=[], nodes=nodes)
    reference = AcdmReferenceInput(
        temporary_code=initial[0].temporary_code,
        flight_no="DIV123",
        aircraft_entry_time=dt(10, 8),
    )

    group = run_strategy(airport_code="XIY", plans=[], nodes=nodes, acdm_references=[reference])[0]

    assert group.assignment_status == "MATCHED_REFERENCE_NO_PLAN"
    assert group.assigned_flight_id is None
    assert group.lineage["acdm_reference"]["flight_no"] == "DIV123"
    assert group.lineage["acdm_reference"]["state"] == "confirmed_plan_missing"


def test_invalid_node_is_retained_in_data_error_group() -> None:
    invalid = NodeInput(
        id=99,
        source_type="algorithm_node",
        event_type="AircraftEntry",
        event_time=None,
        stand=None,
        is_anomaly=True,
    )
    groups = run_strategy(airport_code="XIY", plans=[], nodes=[invalid])

    assert groups[0].assignment_status == "DATA_ERROR"
    assert groups[0].node_ids == [99]
    assert summarize(groups, 1)["node_conservation"] is True


def test_short_fragment_without_aircraft_boundary_is_unassigned_final() -> None:
    nodes = [
        node(1, "ReflectiveBucketPlacementStart", (18, 40), "505"),
        node(2, "ReflectiveBucketPlacementStart", (18, 40), "505"),
        node(3, "ReflectiveBucketPlacementCompletion", (18, 41), "505"),
    ]

    groups = run_strategy(airport_code="XIY", plans=[], nodes=nodes)

    assert len(groups) == 1
    assert groups[0].assignment_status == "UNASSIGNED_FINAL"
    assert groups[0].node_ids == [1, 2, 3]
    assert "INCOMPLETE_FRAGMENT" in groups[0].issue_tags
    assert "DEGRADED" in groups[0].issue_tags
    assert "NODE_DATA_ERROR" not in groups[0].issue_tags
    assert groups[0].lineage["degraded"]["reason"] == "LOW_INFORMATION_FRAGMENT"
    assert summarize(groups, len(nodes))["node_conservation"] is True


def test_isolated_aircraft_entry_is_unassigned_final_not_data_error() -> None:
    groups = run_strategy(
        airport_code="XIY",
        plans=[],
        nodes=[node(1, "AircraftStart", (18, 40), "505")],
    )

    assert groups[0].assignment_status == "UNASSIGNED_FINAL"
    assert "ORPHAN_START_MARKER" in groups[0].issue_tags
    assert "DEGRADED" in groups[0].issue_tags
    assert summarize(groups, 1)["node_conservation"] is True


def combination_plan(
    plan_id: int, stand: str, start: tuple[int, int], end: tuple[int, int]
) -> PlanInput:
    return PlanInput(
        id=plan_id,
        flight_key=f"PLAN-{plan_id}@{stand}",
        safeguard_code=f"PLAN-{plan_id}",
        inbound_flight_no=f"MU{plan_id}01",
        outbound_flight_no=f"MU{plan_id}02",
        stand=stand,
        plan_start=dt(*start),
        plan_end=dt(*end),
    )


def test_left_and_right_combination_stands_can_operate_at_the_same_time() -> None:
    issues = detect_plan_issues(
        [
            combination_plan(1, "525L", (9, 0), (12, 0)),
            combination_plan(2, "525R", (9, 0), (12, 0)),
        ],
        12,
    )

    assert "COMBINATION_STAND_CONFLICT" not in issues[1]
    assert "COMBINATION_STAND_CONFLICT" not in issues[2]


def test_combined_large_stand_conflicts_with_either_side_stand() -> None:
    issues = detect_plan_issues(
        [
            combination_plan(1, "525", (9, 0), (12, 0)),
            combination_plan(2, "525L", (10, 0), (11, 0)),
            combination_plan(3, "525R", (12, 0), (13, 0)),
        ],
        12,
    )

    assert "COMBINATION_STAND_CONFLICT" in issues[1]
    assert "COMBINATION_STAND_CONFLICT" in issues[2]
    assert "COMBINATION_STAND_CONFLICT" not in issues[3]


def test_combination_conflicts_only_apply_to_configured_resource_families() -> None:
    issues = detect_plan_issues(
        [
            combination_plan(1, "964", (9, 0), (12, 0)),
            combination_plan(2, "964L", (10, 0), (11, 0)),
        ],
        12,
        combination_stand_families={"525"},
    )

    assert "COMBINATION_STAND_CONFLICT" not in issues[1]
    assert "COMBINATION_STAND_CONFLICT" not in issues[2]


def test_internal_id_is_not_a_plan_quality_or_direction_signal() -> None:
    without_internal_id = plan(1, "ROW-1", (10, 0), (13, 0))
    without_internal_id = PlanInput(**{**without_internal_id.__dict__, "safeguard_code": None})

    issues = detect_plan_issues([without_internal_id], 12)

    assert "MISSING_SAFEGUARD_CODE" not in issues[1]


def test_same_aircraft_occupancy_with_multiple_plans_is_flagged() -> None:
    plans = [
        plan(1, "ONE", (10, 0), (13, 0), aircraft_no="B533"),
        plan(2, "TWO", (10, 0), (13, 0), aircraft_no="B533"),
    ]

    issues = detect_plan_issues(plans, 12)

    assert "OCCUPANCY_FLIGHT_CONFLICT" in issues[1]
    assert "OCCUPANCY_FLIGHT_CONFLICT" in issues[2]


def night(day: int, hour: int, minute: int) -> datetime:
    return datetime(2026, 6, day, hour, minute)


def overnight_config(**updates: object) -> dict[str, object]:
    config: dict[str, object] = {
        "overnight_bridge_enabled": True,
        "overnight_bridge_max_gap_minutes": 1440,
        "overnight_bridge_plan_iou_threshold": 0.5,
        "terminal_tail_event_policy": {
            key: list(values) for key, values in DEFAULT_TERMINAL_TAIL_EVENT_POLICY.items()
        },
        "combination_stand_families": ["525"],
    }
    config.update(updates)
    return config


def overnight_plan(plan_id: int = 9001, stand: str = "601", same_day: bool = False) -> PlanInput:
    return PlanInput(
        id=plan_id,
        flight_key=f"{stand}-RON",
        safeguard_code=f"{stand}-RON",
        inbound_flight_no="MU2101",
        outbound_flight_no="MU2102",
        stand=stand,
        plan_start=night(18, 22, 0),
        plan_end=night(18, 20, 0) if same_day else night(19, 7, 30),
    )


def overnight_nodes(stand: str = "601") -> list[NodeInput]:
    return [
        NodeInput(1, "algorithm_node", "AircraftEntry", night(18, 22, 10), stand, None),
        NodeInput(2, "algorithm_node", "OpenCabinDoor", night(18, 22, 20), stand, None),
        NodeInput(3, "algorithm_node", "CloseCabinDoor", night(19, 6, 40), stand, None),
        NodeInput(4, "algorithm_node", "AircraftLeave", night(19, 7, 20), stand, None),
    ]


def test_overnight_stay_bridges_the_night_with_one_confirmed_plan() -> None:
    plans = [overnight_plan()]
    nodes = overnight_nodes()

    baseline = run_strategy(airport_code="XIY", plans=plans, nodes=nodes)
    bridged = run_strategy(
        airport_code="XIY", plans=plans, nodes=nodes, config=overnight_config()
    )

    assert [group.node_ids for group in baseline] == [[1, 2], [3, 4]]
    assert [group.node_ids for group in bridged] == [[1, 2, 3, 4]]
    assert "OVERNIGHT_BRIDGED" in bridged[0].issue_tags
    lineage = bridged[0].lineage["overnight_bridge"]
    assert lineage["bridging_plan_id"] == 9001
    assert len(lineage["source_groups"]) == 2
    assert lineage["merged_node_id_set_sha256"]
    assert summarize(bridged, len(nodes))["node_conservation"] is True


def test_overnight_bridge_is_disabled_by_default() -> None:
    plans = [overnight_plan()]
    nodes = overnight_nodes()

    groups = run_strategy(airport_code="XIY", plans=plans, nodes=nodes)

    assert [group.node_ids for group in groups] == [[1, 2], [3, 4]]


def test_overnight_bridge_requires_a_single_plan_across_the_night() -> None:
    second_plan = PlanInput(
        id=9002,
        flight_key="601-SECOND",
        safeguard_code="601-SECOND",
        inbound_flight_no="CZ3301",
        outbound_flight_no="CZ3302",
        stand="601",
        plan_start=night(18, 23, 0),
        plan_end=night(19, 6, 0),
    )
    plans = [overnight_plan(), second_plan]
    nodes = overnight_nodes()

    groups = run_strategy(
        airport_code="XIY", plans=plans, nodes=nodes, config=overnight_config()
    )

    assert [group.node_ids for group in groups] == [[1, 2], [3, 4]]


def test_overnight_bridge_does_not_cross_another_aircraft_on_the_stand() -> None:
    plans = [overnight_plan()]
    nodes = overnight_nodes() + [
        NodeInput(5, "algorithm_node", "AircraftEntry", night(19, 1, 0), "601", None),
        NodeInput(6, "algorithm_node", "AircraftLeave", night(19, 2, 0), "601", None),
    ]

    groups = run_strategy(
        airport_code="XIY", plans=plans, nodes=nodes, config=overnight_config()
    )

    assert [group.node_ids for group in groups] == [[1, 2], [5, 6], [3, 4]]


def test_overnight_bridge_ignores_the_calendar_date_of_the_stay() -> None:
    """凌晨进港当天离港，与前晚进港次晨离港，必须得到同样的桥接结果。

    日历日界不参与聚类判断：过夜航班在 0 点以后进港很常见，用日期切分会造成假边界。
    """
    after_midnight_plan = PlanInput(
        id=9003,
        flight_key="601-RON-LATE",
        safeguard_code="601-RON-LATE",
        inbound_flight_no="MU2101",
        outbound_flight_no="MU2102",
        stand="601",
        plan_start=night(19, 0, 30),
        plan_end=night(19, 13, 0),
    )
    nodes = [
        NodeInput(1, "algorithm_node", "AircraftEntry", night(19, 0, 40), "601", None),
        NodeInput(2, "algorithm_node", "OpenCabinDoor", night(19, 0, 50), "601", None),
        NodeInput(3, "algorithm_node", "CloseCabinDoor", night(19, 12, 10), "601", None),
        NodeInput(4, "algorithm_node", "AircraftLeave", night(19, 12, 40), "601", None),
    ]

    same_day = run_strategy(
        airport_code="XIY", plans=[after_midnight_plan], nodes=nodes, config=overnight_config()
    )
    across_midnight = run_strategy(
        airport_code="XIY",
        plans=[overnight_plan()],
        nodes=overnight_nodes(),
        config=overnight_config(),
    )

    assert [group.node_ids for group in same_day] == [[1, 2, 3, 4]]
    assert [group.node_ids for group in across_midnight] == [[1, 2, 3, 4]]
    assert "OVERNIGHT_BRIDGED" in same_day[0].issue_tags
    assert same_day[0].lineage["overnight_bridge"]["bridging_plan_id"] == 9003


def test_overnight_bridge_does_not_absorb_a_new_entry_group() -> None:
    plans = [overnight_plan()]
    nodes = [
        NodeInput(1, "algorithm_node", "AircraftEntry", night(18, 22, 10), "601", None),
        NodeInput(2, "algorithm_node", "OpenCabinDoor", night(18, 22, 20), "601", None),
        NodeInput(3, "algorithm_node", "AircraftEntry", night(19, 6, 40), "601", None),
        NodeInput(4, "algorithm_node", "AircraftLeave", night(19, 7, 20), "601", None),
    ]

    groups = run_strategy(
        airport_code="XIY", plans=plans, nodes=nodes, config=overnight_config()
    )

    assert [group.node_ids for group in groups] == [[1, 2], [3, 4]]


def test_overnight_bridge_requires_a_versioned_configuration() -> None:
    with pytest.raises(ValueError):
        run_strategy(
            airport_code="XIY",
            plans=[overnight_plan()],
            nodes=overnight_nodes(),
            config={"overnight_bridge_enabled": True},
        )


def test_overnight_bridge_tolerates_a_plan_offset_from_actual_work() -> None:
    """计划与实际作业错位二三十分钟仍应桥接：旧的"计划完整覆盖间隔"判据会误拒。"""
    offset_plan = PlanInput(
        id=9004,
        flight_key="601-OFFSET",
        safeguard_code="601-OFFSET",
        inbound_flight_no="MU2101",
        outbound_flight_no="MU2102",
        stand="601",
        # 计划比实际入位晚 25 分钟、比实际推出早 28 分钟，两端都不覆盖。
        plan_start=night(18, 22, 35),
        plan_end=night(19, 6, 52),
    )
    nodes = overnight_nodes()

    groups = run_strategy(
        airport_code="XIY", plans=[offset_plan], nodes=nodes, config=overnight_config()
    )

    assert [group.node_ids for group in groups] == [[1, 2, 3, 4]]
    lineage = groups[0].lineage["overnight_bridge"]
    assert lineage["bridging_plan_id"] == 9004
    assert lineage["plan_iou"] >= 0.5


def test_overnight_bridge_rejects_a_plan_that_barely_touches_the_stay() -> None:
    """交并比低于阈值的计划不构成停场证据。"""
    grazing_plan = PlanInput(
        id=9005,
        flight_key="601-GRAZE",
        safeguard_code="601-GRAZE",
        inbound_flight_no="MU2101",
        outbound_flight_no="MU2102",
        stand="601",
        plan_start=night(19, 6, 30),
        plan_end=night(19, 8, 0),
    )

    groups = run_strategy(
        airport_code="XIY", plans=[grazing_plan], nodes=overnight_nodes(),
        config=overnight_config(),
    )

    assert [group.node_ids for group in groups] == [[1, 2], [3, 4]]


def test_overnight_bridge_iou_threshold_must_be_a_ratio() -> None:
    with pytest.raises(ValueError):
        run_strategy(
            airport_code="XIY",
            plans=[overnight_plan()],
            nodes=overnight_nodes(),
            config=overnight_config(overnight_bridge_plan_iou_threshold=1.5),
        )
