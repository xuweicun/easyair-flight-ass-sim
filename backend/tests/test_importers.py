from datetime import datetime
from io import BytesIO

from openpyxl import Workbook

from app.importers import parse_flight_plans, parse_nodes


def workbook_bytes(headers: list[str], rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_plan_rows_with_same_safeguard_and_stand_are_grouped() -> None:
    content = workbook_bytes(
        ["保障编码", "机位", "航班号", "计划开始时间", "计划结束时间"],
        [
            ["20993035", "505", "MU2148", datetime(2026, 6, 18, 16, 58), datetime(2026, 6, 18, 18, 0)],
            ["20993035", "505", "MU9969", datetime(2026, 6, 18, 18, 0), datetime(2026, 6, 18, 21, 10)],
        ],
    )

    plans = parse_flight_plans(content)

    assert len(plans) == 1
    assert plans[0]["inbound_flight_no"] == "MU2148"
    assert plans[0]["outbound_flight_no"] == "MU9969"
    assert plans[0]["plan_start"] == datetime(2026, 6, 18, 16, 58)
    assert plans[0]["plan_end"] == datetime(2026, 6, 18, 21, 10)


def test_manual_nodes_keep_their_source_and_reported_flight() -> None:
    content = workbook_bytes(
        ["记录ID", "机位", "节点类型", "节点时间", "航班号"],
        [["M-1", "505", "CargoDoorOpen", datetime(2026, 6, 18, 17, 26), "MU2148"]],
    )

    nodes = parse_nodes(content, "manual_report")

    assert nodes[0]["source_type"] == "manual_report"
    assert nodes[0]["reported_flight_no"] == "MU2148"
    assert nodes[0]["is_anomaly"] is False


def test_real_plan_rows_use_arrival_and_departure_direction() -> None:
    content = workbook_bytes(
        ["safeguard_code", "stand", "flight_no", "in_out", "real_start", "real_end"],
        [
            ["20993035", "505", "MU9969", "D", datetime(2026, 6, 18, 18), datetime(2026, 6, 18, 21, 10)],
            ["20993035", "505", "MU2148", "A", datetime(2026, 6, 18, 16, 58), datetime(2026, 6, 18, 18)],
        ],
    )

    plans = parse_flight_plans(content)

    assert plans[0]["inbound_flight_no"] == "MU2148"
    assert plans[0]["outbound_flight_no"] == "MU9969"


def test_complementary_rows_with_different_internal_ids_merge_by_occupancy() -> None:
    start = datetime(2026, 6, 17, 16, 37)
    end = datetime(2026, 6, 18, 10, 2)
    content = workbook_bytes(
        [
            "safeguard_code",
            "stand",
            "flight_no",
            "in_out",
            "real_start",
            "real_end",
            "aircraft_num",
        ],
        [
            ["20992159", "514", "MU2136", "A", start, end, "B6465"],
            [None, "514", "MU2259", "D", start, end, "B6465"],
        ],
    )

    plans = parse_flight_plans(content)

    assert len(plans) == 1
    assert plans[0]["flight_key"] == "OCC-B6465-20260617163700@514"
    assert plans[0]["inbound_flight_no"] == "MU2136"
    assert plans[0]["outbound_flight_no"] == "MU2259"
    assert plans[0]["raw_payload"]["internal_ids"] == ["20992159"]
    assert plans[0]["raw_payload"]["normalization"]["method"] == "physical_occupancy"


def test_departure_only_row_does_not_duplicate_flight_number_as_inbound() -> None:
    content = workbook_bytes(
        ["stand", "flight_no", "in_out", "real_start", "real_end", "aircraft_num"],
        [[
            "514",
            "MU2259",
            "D",
            datetime(2026, 6, 17, 16, 37),
            datetime(2026, 6, 18, 10, 2),
            "B6465",
        ]],
    )

    plan = parse_flight_plans(content)[0]

    assert plan["inbound_flight_no"] is None
    assert plan["outbound_flight_no"] == "MU2259"


def test_same_direction_rows_are_not_merged_as_one_occupancy() -> None:
    start = datetime(2026, 6, 17, 16, 37)
    end = datetime(2026, 6, 18, 10, 2)
    content = workbook_bytes(
        ["stand", "flight_no", "in_out", "real_start", "real_end", "aircraft_num"],
        [
            ["514", "MU2259", "D", start, end, "B6465"],
            ["514", "MU2260", "D", start, end, "B6465"],
        ],
    )

    assert len(parse_flight_plans(content)) == 2


def test_real_algorithm_message_json_is_parsed() -> None:
    content = workbook_bytes(
        ["id", "stand", "safeguard_code", "message_content", "create_time"],
        [
            [
                "2067140202390970369",
                "575",
                "20992956",
                '{"event_name":"OilseedsCarArrival","event_time":"20260617145953",'
                '"stand_name":"575","camera_id":"61010102331320811711"}',
                datetime(2026, 6, 17, 15, 0, 5),
            ]
        ],
    )

    nodes = parse_nodes(content, "algorithm_node")

    assert nodes[0]["source_row_id"] == "2067140202390970369"
    assert nodes[0]["event_type"] == "OilseedsCarArrival"
    assert nodes[0]["event_time"] == datetime(2026, 6, 17, 14, 59, 53)
    assert nodes[0]["stand"] == "575"
    assert nodes[0]["safeguard_code"] == "20992956"
    assert nodes[0]["raw_payload"]["message_content"]["camera_id"] == "61010102331320811711"
    assert nodes[0]["is_anomaly"] is False


def test_turnaround_flight_video_message_is_not_imported_as_a_node() -> None:
    content = workbook_bytes(
        ["id", "stand", "safeguard_code", "message_content"],
        [
            [
                "2067141120511533058",
                "521",
                "20992271",
                '{"type":"turnaround_flight","begin_time":"20260617122000",'
                '"end_time":"20260617150000","stand_name":"521"}',
            ]
        ],
    )

    assert parse_nodes(content, "algorithm_node") == []


def test_known_2076_date_typo_is_corrected_without_changing_flight_number() -> None:
    content = workbook_bytes(
        ["stand", "flight_no", "in_out", "real_start", "real_end", "aircraft_num"],
        [[
            "910L",
            "OQ2076",
            "D",
            datetime(2076, 6, 17, 17, 13),
            datetime(2076, 6, 17, 18, 28),
            "B5130",
        ]],
    )

    plan = parse_flight_plans(content)[0]

    assert plan["outbound_flight_no"] == "OQ2076"
    assert plan["plan_start"] == datetime(2026, 6, 17, 17, 13)
    assert plan["plan_end"] == datetime(2026, 6, 17, 18, 28)
    assert plan["raw_payload"]["rows"][0]["flight_no"] == "OQ2076"
    assert plan["raw_payload"]["rows"][0]["real_end"].startswith("2026-")


def test_known_2076_compact_node_date_is_corrected_without_global_replacement() -> None:
    content = workbook_bytes(
        ["id", "stand", "flight_no", "message_content"],
        [[
            "OQ2076-EVENT-1",
            "910L",
            "OQ2076",
            '{"event_name":"AircraftEntry","event_time":"20760617145953",'
            '"flight_no":"OQ2076"}',
        ]],
    )

    node = parse_nodes(content, "algorithm_node")[0]

    assert node["event_time"] == datetime(2026, 6, 17, 14, 59, 53)
    assert node["reported_flight_no"] == "OQ2076"
    assert node["source_row_id"] == "OQ2076-EVENT-1"
    assert node["raw_payload"]["message_content"]["event_time"] == "20260617145953"
    assert node["raw_payload"]["message_content"]["flight_no"] == "OQ2076"
