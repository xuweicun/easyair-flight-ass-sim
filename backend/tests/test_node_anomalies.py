from datetime import datetime, timedelta
from types import SimpleNamespace

from app.node_anomalies import detect_node_anomalies, summarize_stand_node_issues


BASE = datetime(2026, 6, 18, 10, 0)


def node(node_id: int, event_type: str, minutes: int, source: str = "algorithm_node"):
    return SimpleNamespace(
        id=node_id,
        event_type=event_type,
        event_time=BASE + timedelta(minutes=minutes),
        source_type=source,
    )


def group(*nodes):
    return SimpleNamespace(
        id=7,
        temporary_code="TMP-XIY-505-20260618-001",
        stand="505",
        observed_start=BASE,
        observed_end=BASE + timedelta(hours=1),
        nodes=[SimpleNamespace(node=item) for item in nodes],
    )


def test_detects_rapid_repeated_algorithm_event() -> None:
    result = detect_node_anomalies(
        [
            group(
                node(1, "OpenCargoDoor", 0),
                node(2, "OpenCargoDoor", 3),
                node(3, "OpenCargoDoor", 12),
            )
        ]
    )

    assert len(result) == 1
    assert result[0]["problem_code"] == "RAPID_REPEAT"
    assert result[0]["affected_node_count"] == 2
    assert "开货舱门" in result[0]["reason"]


def test_detects_group_with_only_guide_car_nodes() -> None:
    result = detect_node_anomalies(
        [group(node(1, "GuideCarStart", 0), node(2, "GuideCarEnd", 2))]
    )

    assert {item["problem_code"] for item in result} == {"GUIDE_CAR_ONLY"}


def test_manual_nodes_do_not_create_algorithm_anomaly() -> None:
    result = detect_node_anomalies(
        [
            group(
                node(1, "OpenCargoDoor", 0),
                node(2, "OpenCargoDoor", 2, "manual_report"),
            )
        ]
    )

    assert result == []


def test_multi_vehicle_events_are_not_treated_as_repeat_anomalies() -> None:
    result = detect_node_anomalies(
        [
            group(
                node(1, "BaggageTractorInPosition", 0),
                node(2, "BaggageTractorInPosition", 2),
            )
        ]
    )

    assert result == []


def test_stand_report_lists_each_selected_node_type_separately() -> None:
    anomalies = detect_node_anomalies(
        [
            group(
                node(1, "OpenCargoDoor", 0),
                node(2, "OpenCargoDoor", 2),
                node(3, "CloseCargoDoor", 3),
                node(4, "CloseCargoDoor", 5),
            )
        ]
    )

    rows = summarize_stand_node_issues(
        anomalies,
        node_types={"OpenCargoDoor", "CloseCargoDoor"},
        minimum_quantity=2,
    )

    assert [(row["stand"], row["event_label"]) for row in rows] == [
        ("505", "关货舱门"),
        ("505", "开货舱门"),
    ]
    assert all(row["problem_flight_count"] == 1 for row in rows)
    assert all(row["anomaly_node_count"] == 2 for row in rows)

    assert summarize_stand_node_issues(anomalies, minimum_quantity=3) == []
