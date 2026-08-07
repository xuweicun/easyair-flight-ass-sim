from __future__ import annotations

import re
from collections import defaultdict
from datetime import timedelta
from typing import Any, Iterable


GUIDE_CAR_EVENTS = {"GuideCarStart", "GuideCarEnd"}
REPEAT_SENSITIVE_EVENTS = {
    "AccessCorridorBridge",
    "AccessCorridorBridgeBegin",
    "CloseCabinDoor",
    "CloseCargoDoor",
    "OpenCabinDoor",
    "OpenCargoDoor",
    "RemoveCorridorBridge",
    "RemoveCorridorBridgeBegin",
}

EVENT_LABELS = {
    "AccessCorridorBridge": "完成靠接",
    "AccessCorridorBridgeBegin": "靠桥开始",
    "AircraftEntry": "飞机入位",
    "AircraftLeave": "飞机推出",
    "CloseCabinDoor": "关客舱门",
    "CloseCargoDoor": "关货舱门",
    "GuideCarEnd": "引导车结束",
    "GuideCarStart": "引导车开始",
    "OpenCabinDoor": "开客舱门",
    "OpenCargoDoor": "开货舱门",
    "RemoveCorridorBridge": "撤廊桥结束",
    "RemoveCorridorBridgeBegin": "撤廊桥开始",
    "TowArrival": "牵引车就位",
    "TowEnd": "牵引车结束",
    "TowShow": "牵引车出现",
}


def detect_node_anomalies(
    groups: Iterable[Any], repeat_window_minutes: int = 5
) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    repeat_window = timedelta(minutes=repeat_window_minutes)

    for group in groups:
        nodes = sorted(
            (
                item.node
                for item in group.nodes
                if item.node.source_type == "algorithm_node" and item.node.event_time
            ),
            key=lambda node: (node.event_time, node.id),
        )
        if not nodes:
            continue

        event_types = {node.event_type for node in nodes}
        if event_types.issubset(GUIDE_CAR_EVENTS):
            anomalies.append(
                _item(
                    group,
                    problem_code="GUIDE_CAR_ONLY",
                    problem_type="只有引导车节点",
                    reason="该保障组仅上报引导车开始/结束，缺少飞机入位及其他保障节点",
                    affected_nodes=nodes,
                )
            )

        by_type: dict[str, list[Any]] = defaultdict(list)
        for node in nodes:
            by_type[node.event_type].append(node)

        for event_type, same_type_nodes in by_type.items():
            if event_type not in REPEAT_SENSITIVE_EVENTS:
                continue
            rapid_nodes: dict[int, Any] = {}
            for previous, current in zip(same_type_nodes, same_type_nodes[1:]):
                if current.event_time - previous.event_time <= repeat_window:
                    rapid_nodes[previous.id] = previous
                    rapid_nodes[current.id] = current
            if len(rapid_nodes) < 2:
                continue
            affected = sorted(rapid_nodes.values(), key=lambda node: (node.event_time, node.id))
            label = EVENT_LABELS.get(event_type, event_type)
            anomalies.append(
                _item(
                    group,
                    problem_code="RAPID_REPEAT",
                    problem_type="短时间重复节点",
                    reason=(
                        f"{label}在相邻{repeat_window_minutes}分钟内重复上报，"
                        f"共涉及{len(affected)}条节点"
                    ),
                    affected_nodes=affected,
                )
            )

    return sorted(
        anomalies,
        key=lambda item: (item["stand"], item["window_start"], item["problem_code"]),
    )


def summarize_stand_node_issues(
    items: Iterable[dict[str, Any]],
    node_types: set[str] | None = None,
    minimum_quantity: int = 1,
) -> list[dict[str, Any]]:
    selected_types = node_types or set()
    by_stand: dict[str, dict[str, dict[str, Any]]] = defaultdict(
        lambda: defaultdict(
            lambda: {"node_count": 0, "group_ids": set(), "temporary_codes": set()}
        )
    )
    for item in items:
        occurrence_counts: dict[str, int] = defaultdict(int)
        for occurrence in item["occurrences"]:
            event_type = occurrence["event_type"]
            if selected_types and event_type not in selected_types:
                continue
            occurrence_counts[event_type] += 1
        for event_type, count in occurrence_counts.items():
            entry = by_stand[item["stand"]][event_type]
            entry["node_count"] += count
            entry["group_ids"].add(item["group_id"])
            entry["temporary_codes"].add(item["temporary_code"])

    rows: list[dict[str, Any]] = []
    for stand, event_counts in by_stand.items():
        stand_total = sum(
            entry["node_count"]
            for entry in event_counts.values()
            if entry["node_count"] >= minimum_quantity
        )
        for event_type, entry in event_counts.items():
            if entry["node_count"] < minimum_quantity:
                continue
            rows.append(
                {
                    "stand": stand,
                    "event_type": event_type,
                    "event_label": EVENT_LABELS.get(event_type, event_type),
                    "problem_flight_count": len(entry["group_ids"]),
                    "anomaly_node_count": entry["node_count"],
                    "temporary_codes": sorted(entry["temporary_codes"]),
                    "stand_total": stand_total,
                }
            )
    return sorted(
        rows,
        key=lambda row: (
            -row["stand_total"],
            _natural_key(row["stand"]),
            -row["anomaly_node_count"],
            row["event_label"],
        ),
    )


def _natural_key(value: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", value)]


def _item(
    group: Any,
    *,
    problem_code: str,
    problem_type: str,
    reason: str,
    affected_nodes: list[Any],
) -> dict[str, Any]:
    return {
        "id": f"{group.id}:{problem_code}:{affected_nodes[0].event_type}",
        "group_id": group.id,
        "temporary_code": group.temporary_code,
        "stand": group.stand,
        "problem_code": problem_code,
        "problem_type": problem_type,
        "reason": reason,
        "window_start": affected_nodes[0].event_time,
        "window_end": affected_nodes[-1].event_time,
        "group_start": group.observed_start,
        "group_end": group.observed_end,
        "group_node_count": len(group.nodes),
        "affected_node_count": len(affected_nodes),
        "event_types": sorted({node.event_type for node in affected_nodes}),
        "occurrences": [
            {
                "node_id": node.id,
                "event_type": node.event_type,
                "event_time": node.event_time,
            }
            for node in affected_nodes
        ],
    }
