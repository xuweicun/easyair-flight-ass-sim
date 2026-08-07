from datetime import datetime

from app.models import FlightGroup, FlightPlan, GroupNode, NodeEvent
from app.recovery import DEFAULT_RECOVERY_CONFIG, _recovery_plan, machine_state


def group(status: str, assigned_flight_id: int | None, tags: list[str]) -> FlightGroup:
    return FlightGroup(
        run_id=1,
        temporary_code="TMP-XIY-505-20260618-001",
        stand="505",
        observed_start=datetime(2026, 6, 18, 10),
        observed_end=datetime(2026, 6, 18, 12),
        assignment_status=status,
        assigned_flight_id=assigned_flight_id,
        issue_tags=tags,
        lineage={},
    )


def test_acdm_reference_without_plan_still_enters_plan_recovery() -> None:
    status, reason = machine_state(
        group("MATCHED_REFERENCE_NO_PLAN", None, ["MISSING_PLAN", "ACDM_PLAN_MISSING"]),
        DEFAULT_RECOVERY_CONFIG,
    )

    assert status == "RECOVERY_PENDING"
    assert reason == "PLAN_MISSING"


def test_recovery_disabled_finishes_without_waiting_for_human() -> None:
    status, reason = machine_state(
        group("UNASSIGNED", None, ["MISSING_PLAN"]),
        {**DEFAULT_RECOVERY_CONFIG, "flight_recovery_enabled": False},
    )

    assert status == "UNASSIGNED_FINAL"
    assert reason == "RECOVERY_DISABLED"


def test_acdm_plan_missing_does_not_fall_back_to_unrelated_overlapping_plan() -> None:
    item = group("MATCHED_REFERENCE_NO_PLAN", None, ["MISSING_PLAN", "ACDM_PLAN_MISSING"])
    item.lineage = {"acdm_reference": {"flight_no": "ZZ999"}}
    item.nodes = []
    unrelated = FlightPlan(
        id=7,
        batch_id=1,
        safeguard_code="20990001",
        stand="505",
        plan_start=datetime(2026, 6, 18, 10),
        plan_end=datetime(2026, 6, 18, 12),
        inbound_flight_no="MU1001",
        outbound_flight_no="MU1002",
    )

    assert _recovery_plan(item, [unrelated]) is None


def test_acdm_plan_missing_ignores_conflicting_node_reported_flight_number() -> None:
    item = group("MATCHED_REFERENCE_NO_PLAN", None, ["MISSING_PLAN", "ACDM_PLAN_MISSING"])
    item.lineage = {"acdm_reference": {"flight_no": "ZZ999"}}
    item.nodes = [GroupNode(
        node_id=1,
        order_index=0,
        node=NodeEvent(
            batch_id=1,
            source_type="algorithm_node",
            source_row_id="conflicting-flight",
            event_type="AircraftEntry",
            event_time=datetime(2026, 6, 18, 10),
            stand="505",
            reported_flight_no="MU1001",
        ),
    )]
    unrelated = FlightPlan(
        id=8,
        batch_id=1,
        safeguard_code="20990002",
        stand="505",
        plan_start=datetime(2026, 6, 18, 10),
        plan_end=datetime(2026, 6, 18, 12),
        inbound_flight_no="MU1001",
        outbound_flight_no="MU1002",
    )

    assert _recovery_plan(item, [unrelated]) is None


def test_recovery_uses_expanded_request_window_for_plan_candidates() -> None:
    item = group("UNASSIGNED", None, ["MISSING_PLAN"])
    item.nodes = []
    delayed_plan = FlightPlan(
        id=9,
        batch_id=1,
        safeguard_code="20990003",
        stand="505",
        plan_start=datetime(2026, 6, 18, 12, 30),
        plan_end=datetime(2026, 6, 18, 13, 30),
        inbound_flight_no="MU2001",
        outbound_flight_no="MU2002",
    )

    assert _recovery_plan(
        item,
        [delayed_plan],
        datetime(2026, 6, 18, 8),
        datetime(2026, 6, 18, 14),
    ) is delayed_plan
