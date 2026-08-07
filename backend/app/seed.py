from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine import DEFAULT_STRATEGY
from app.models import Batch, FlightPlan, NodeEvent, StrategyVersion, utcnow
from app.services import execute_run


def dt(day: int, hour: int, minute: int) -> datetime:
    return datetime(2026, 6, day, hour, minute)


async def seed_demo(db: AsyncSession) -> None:
    count = await db.scalar(select(func.count(Batch.id)))
    if count:
        return

    strategy = StrategyVersion(
        name="基线策略 v1",
        status="published",
        config=DEFAULT_STRATEGY,
        published_at=utcnow(),
    )
    batch = Batch(
        name="西安机场 2026-06 问题样本",
        airport_code="XIY",
        status="ready",
        source_files={"mode": "built-in-regression-fixtures"},
        stats={
            "historical_plan_rows": 17934,
            "historical_node_rows": 69823,
            "missing_safeguard_code": 225,
            "invalid_year_rows": 24,
            "long_windows": 868,
            "overlap_pairs": 60,
            "multi_candidate_nodes": 840,
            "no_candidate_nodes": 4815,
        },
    )
    db.add_all([strategy, batch])
    await db.flush()

    plans = [
        FlightPlan(
            batch_id=batch.id,
            flight_key="20993035@505",
            safeguard_code="20993035",
            inbound_flight_no="MU2148",
            outbound_flight_no="MU9969",
            stand="505",
            plan_start=dt(18, 16, 58),
            plan_end=dt(18, 21, 10),
            airline="MU",
            aircraft_type="319",
            aircraft_no="B6452",
            issue_tags=[],
            raw_payload={"fixture": "截图案例"},
        ),
        FlightPlan(
            batch_id=batch.id,
            flight_key="20994482@589",
            safeguard_code="20994482",
            inbound_flight_no="CZ3201",
            outbound_flight_no="CZ3202",
            stand="589",
            plan_start=dt(18, 10, 40),
            plan_end=dt(18, 13, 10),
            airline="CZ",
            aircraft_type="320",
            issue_tags=[],
            raw_payload={"fixture": "结束节点语义错例"},
        ),
        FlightPlan(
            batch_id=batch.id,
            flight_key="20994484@589",
            safeguard_code="20994484",
            inbound_flight_no="MU5101",
            outbound_flight_no="MU5102",
            stand="589",
            plan_start=dt(18, 13, 0),
            plan_end=dt(18, 16, 20),
            airline="MU",
            aircraft_type="321",
            issue_tags=[],
            raw_payload={"fixture": "与上一航班重叠"},
        ),
        FlightPlan(
            batch_id=batch.id,
            flight_key="20994064@548",
            safeguard_code="20994064",
            inbound_flight_no="HU7801",
            outbound_flight_no="HU7802",
            stand="548",
            plan_start=dt(20, 4, 40),
            plan_end=dt(20, 7, 35),
            airline="HU",
            aircraft_type="738",
            issue_tags=[],
            raw_payload={"fixture": "结束节点语义错例"},
        ),
        FlightPlan(
            batch_id=batch.id,
            flight_key="20995020@548",
            safeguard_code="20995020",
            inbound_flight_no="MU2201",
            outbound_flight_no="MU2202",
            stand="548",
            plan_start=dt(20, 7, 20),
            plan_end=dt(20, 10, 50),
            airline="MU",
            aircraft_type="320",
            issue_tags=[],
            raw_payload={"fixture": "与上一航班重叠"},
        ),
        FlightPlan(
            batch_id=batch.id,
            flight_key="20989396@910L",
            safeguard_code="20989396",
            inbound_flight_no="Z7571",
            outbound_flight_no="Z7572",
            stand="910L",
            plan_start=dt(18, 17, 0),
            plan_end=datetime(2026, 6, 18, 20, 0),
            airline="Z7",
            aircraft_type="320",
            issue_tags=[],
            raw_payload={"fixture": "异常年份已修正"},
        ),
        FlightPlan(
            batch_id=batch.id,
            flight_key="OVL-A@506",
            safeguard_code="OVL-A",
            inbound_flight_no="3U8101",
            outbound_flight_no="3U8102",
            stand="506",
            plan_start=dt(19, 8, 0),
            plan_end=dt(19, 11, 0),
            airline="3U",
            aircraft_type="320",
            issue_tags=[],
            raw_payload={"fixture": "重叠候选"},
        ),
        FlightPlan(
            batch_id=batch.id,
            flight_key="OVL-B@506",
            safeguard_code="OVL-B",
            inbound_flight_no="CA4101",
            outbound_flight_no="CA4102",
            stand="506",
            plan_start=dt(19, 10, 45),
            plan_end=dt(19, 13, 30),
            airline="CA",
            aircraft_type="321",
            issue_tags=[],
            raw_payload={"fixture": "重叠候选"},
        ),
        FlightPlan(
            batch_id=batch.id,
            flight_key="COMBO-L@525L",
            safeguard_code="COMBO-L",
            inbound_flight_no="GS7101",
            outbound_flight_no="GS7102",
            stand="525L",
            plan_start=dt(21, 9, 0),
            plan_end=dt(21, 12, 0),
            airline="GS",
            aircraft_type="190",
            issue_tags=[],
            raw_payload={"fixture": "组合机位左右侧并行保障"},
        ),
        FlightPlan(
            batch_id=batch.id,
            flight_key="COMBO-R@525R",
            safeguard_code="COMBO-R",
            inbound_flight_no="GS7201",
            outbound_flight_no="GS7202",
            stand="525R",
            plan_start=dt(21, 9, 10),
            plan_end=dt(21, 12, 10),
            airline="GS",
            aircraft_type="190",
            issue_tags=[],
            raw_payload={"fixture": "组合机位左右侧并行保障"},
        ),
    ]
    db.add_all(plans)
    await db.flush()

    fixtures = [
        ("505", 18, 17, 9, "AircraftEntry", "algorithm_node", None),
        ("505", 18, 17, 13, "BridgeDocked", "algorithm_node", None),
        ("505", 18, 17, 26, "CargoDoorOpen", "manual_report", "MU2148"),
        ("505", 18, 19, 44, "CargoDoorClose", "algorithm_node", None),
        ("505", 18, 20, 47, "AircraftBeginsTaxi", "algorithm_node", None),
        ("505", 18, 20, 52, "AircraftLeave", "algorithm_node", None),
        ("589", 18, 10, 55, "AircraftEntry", "algorithm_node", None),
        ("589", 18, 11, 7, "BridgeDocked", "algorithm_node", None),
        ("589", 18, 12, 58, "CargoDoorClose", "algorithm_node", None),
        ("589", 18, 13, 7, "AircraftBeginsTaxi", "algorithm_node", None),
        ("589", 18, 13, 8, "AircraftLeave", "algorithm_node", None),
        ("589", 18, 13, 9, "TowEnd", "algorithm_node", None),
        ("589", 18, 13, 25, "AircraftEntry", "algorithm_node", None),
        ("589", 18, 13, 34, "BridgeDocked", "algorithm_node", None),
        ("589", 18, 16, 8, "AircraftLeave", "algorithm_node", None),
        ("548", 20, 4, 52, "AircraftEntry", "algorithm_node", None),
        ("548", 20, 6, 58, "CargoDoorClose", "algorithm_node", None),
        ("548", 20, 7, 28, "AircraftBeginsTaxi", "algorithm_node", None),
        ("548", 20, 7, 35, "AircraftLeave", "algorithm_node", None),
        ("548", 20, 7, 42, "AircraftEntry", "algorithm_node", None),
        ("548", 20, 10, 38, "AircraftLeave", "algorithm_node", None),
        ("963", 22, 8, 4, "AircraftEntry", "algorithm_node", None),
        ("963", 22, 8, 19, "BridgeDocked", "algorithm_node", None),
        ("963", 22, 10, 45, "AircraftLeave", "algorithm_node", None),
        ("910L", 18, 17, 18, "AircraftEntry", "algorithm_node", None),
        ("910L", 18, 19, 50, "AircraftLeave", "algorithm_node", None),
        ("506", 19, 10, 47, "AircraftEntry", "algorithm_node", "MU0000"),
        ("506", 19, 10, 55, "BridgeDocked", "algorithm_node", "MU0000"),
        ("506", 19, 13, 12, "AircraftLeave", "algorithm_node", "MU0000"),
        ("525L", 21, 9, 15, "AircraftEntry", "algorithm_node", None),
        ("525L", 21, 11, 52, "AircraftLeave", "algorithm_node", None),
        ("525R", 21, 9, 24, "AircraftEntry", "algorithm_node", None),
        ("525R", 21, 12, 0, "AircraftLeave", "algorithm_node", None),
    ]
    nodes = []
    for index, (stand, day, hour, minute, event_type, source_type, flight_no) in enumerate(
        fixtures, start=1
    ):
        nodes.append(
            NodeEvent(
                batch_id=batch.id,
                source_type=source_type,
                source_row_id=f"fixture-{index}",
                event_type=event_type,
                event_time=dt(day, hour, minute),
                stand=stand,
                reported_flight_no=flight_no,
                safeguard_code=None,
                is_anomaly=False,
                raw_payload={"fixture": True},
            )
        )
    db.add_all(nodes)
    await db.commit()
    await execute_run(db, batch, strategy)
