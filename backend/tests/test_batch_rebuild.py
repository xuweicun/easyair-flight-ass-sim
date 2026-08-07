from datetime import datetime

import pytest

from app.batch_rebuild import _map_plan, _raw_plan_rows
from app.models import FlightPlan


def plan(
    plan_id: int,
    inbound: str | None,
    outbound: str | None,
    aircraft_no: str = "B533",
) -> FlightPlan:
    return FlightPlan(
        id=plan_id,
        batch_id=1,
        flight_key=f"P{plan_id}",
        inbound_flight_no=inbound,
        outbound_flight_no=outbound,
        stand="514",
        plan_start=datetime(2026, 6, 17, 16, 37),
        plan_end=datetime(2026, 6, 18, 10, 2),
        aircraft_no=aircraft_no,
        issue_tags=[],
        raw_payload={},
    )


def test_raw_plan_rows_deduplicates_identical_source_rows() -> None:
    first = plan(1, "MU2136", None)
    second = plan(2, None, "MU2259")
    first.raw_payload = {"rows": [{"__row_number__": 2, "航班号": "MU2136"}]}
    second.raw_payload = {
        "rows": [
            {"__row_number__": 2, "航班号": "MU2136"},
            {"__row_number__": 3, "航班号": "MU2259"},
        ]
    }

    rows = _raw_plan_rows([first, second])

    assert [row["__row_number__"] for row in rows] == [2, 3]


def test_raw_plan_rows_rejects_conflicting_source_copies() -> None:
    first = plan(1, "MU2136", None)
    second = plan(2, None, "MU2259")
    first.raw_payload = {"rows": [{"__row_number__": 2, "航班号": "MU2136"}]}
    second.raw_payload = {"rows": [{"__row_number__": 2, "航班号": "MU2259"}]}

    with pytest.raises(ValueError, match="冲突副本"):
        _raw_plan_rows([first, second])


def test_map_plan_finds_new_occupancy_plan_by_flight_and_aircraft() -> None:
    old = plan(1, "MU2136", None)
    wrong_aircraft = plan(2, "MU2136", "MU2259", aircraft_no="B524")
    merged = plan(3, "MU2136", "MU2259")

    assert _map_plan(old, "MU2136", [wrong_aircraft, merged]) is merged
