from datetime import datetime

from app.engine import CandidateScore, GroupResult
from app.recovery import outbound_state
from app.services import _replay_structural_reviews


def group(code: str = "TMP-XIY-540-20260617-001") -> GroupResult:
    return GroupResult(
        temporary_code=code,
        stand="540",
        observed_start=datetime(2026, 6, 17, 15, 0),
        observed_end=datetime(2026, 6, 17, 16, 12),
        node_ids=[1, 2, 3],
        assignment_status="MATCHED",
        assigned_flight_id=10,
        confidence=0.9,
        margin=20,
        candidates=[CandidateScore(flight_plan_id=10, score=90, breakdown={}, selected=True)],
    )


def test_replays_review_for_disappeared_split_code_with_exact_node_set() -> None:
    result = group()

    _replay_structural_reviews(
        [result],
        [
            {
                "review_id": 8,
                "temporary_code": f"{result.temporary_code}-A",
                "node_ids": {1, 2, 3},
                "expected_flight_id": None,
                "expected_flight_no": None,
                "expected_assignment_status": "UNASSIGNED",
            }
        ],
    )

    assert result.assignment_status == "UNASSIGNED"
    assert result.assigned_flight_id is None
    assert result.candidates[0].selected is False
    assert result.lineage["structural_review_replay"]["matched_by"] == "exact_node_set"


def test_does_not_replay_when_reviewed_temporary_code_still_exists() -> None:
    result = group()

    _replay_structural_reviews(
        [result],
        [
            {
                "review_id": 9,
                "temporary_code": result.temporary_code,
                "node_ids": {1, 2, 3},
                "expected_flight_id": None,
                "expected_flight_no": None,
                "expected_assignment_status": "UNASSIGNED",
            }
        ],
    )

    assert result.assignment_status == "MATCHED"
    assert "structural_review_replay" not in result.lineage


def test_does_not_apply_old_review_when_same_code_has_different_members() -> None:
    result = group()
    result.node_ids = [1, 2, 3, 4]

    _replay_structural_reviews(
        [result],
        [
            {
                "review_id": 10,
                "temporary_code": result.temporary_code,
                "node_ids": {1, 2, 3},
                "expected_flight_id": None,
                "expected_flight_no": None,
                "expected_assignment_status": "UNASSIGNED",
            }
        ],
    )

    assert result.assignment_status == "MATCHED"
    assert "structural_review_replay" not in result.lineage


def test_immutable_sent_replay_never_creates_a_second_send_intent() -> None:
    assert outbound_state("MATCHED", False, already_sent=True) == (
        "NOOP_ALREADY_SENT",
        "ALREADY_SENT",
    )


def test_structural_review_cannot_override_an_immutable_sent_group() -> None:
    result = group()
    result.lineage["immutable_sent_replay"] = {
        "temporary_code": result.temporary_code,
        "node_id_set_sha256": "frozen",
    }

    _replay_structural_reviews(
        [result],
        [
            {
                "review_id": 11,
                "temporary_code": f"{result.temporary_code}-OLD",
                "node_ids": {1, 2, 3},
                "expected_flight_id": None,
                "expected_flight_no": None,
                "expected_assignment_status": "UNASSIGNED",
            }
        ],
    )

    assert result.assignment_status == "MATCHED"
    assert result.assigned_flight_id == 10
    assert "structural_review_replay" not in result.lineage
