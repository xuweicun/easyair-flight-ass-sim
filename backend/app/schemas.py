from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class BatchOut(BaseModel):
    id: int
    name: str
    airport_code: str
    status: str
    source_files: dict[str, Any]
    stats: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class FlightPlanOut(BaseModel):
    id: int
    flight_key: str
    safeguard_code: str | None
    inbound_flight_no: str | None
    outbound_flight_no: str | None
    stand: str | None
    plan_start: datetime | None
    plan_end: datetime | None
    airline: str | None
    aircraft_type: str | None
    aircraft_no: str | None
    issue_tags: list[str]

    model_config = {"from_attributes": True}


class NodeOut(BaseModel):
    id: int
    source_type: str
    event_type: str
    event_time: datetime | None
    stand: str | None
    reported_flight_no: str | None
    safeguard_code: str | None
    is_anomaly: bool

    model_config = {"from_attributes": True}


class CandidateOut(BaseModel):
    id: int
    rank: int
    score: float
    score_breakdown: dict[str, float]
    excluded_reason: str | None
    selected: bool
    flight_plan: FlightPlanOut

    model_config = {"from_attributes": True}


class ReviewOut(BaseModel):
    id: int
    verdict: str
    error_type: str | None
    correct_flight_id: int | None
    correct_flight_no: str | None
    expected_flight_id: int | None
    expected_flight_no: str | None
    expected_assignment_status: str | None
    comment: str | None
    reviewer: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ClusterReviewIn(BaseModel):
    verdict: Literal["correct", "split_required", "merge_required", "anomaly"]
    split_node_id: int | None = None
    merge_group_ids: list[int] = Field(default_factory=list)
    anomaly_node_ids: list[int] = Field(default_factory=list)
    comment: str | None = Field(default=None, max_length=1000)
    reviewer: str = Field(default="本地核验员", min_length=1, max_length=100)


class ClusterReviewOut(BaseModel):
    id: int
    verdict: str
    split_node_id: int | None
    merge_group_ids: list[int]
    anomaly_node_ids: list[int]
    comment: str | None
    reviewer: str
    created_at: datetime

    model_config = {"from_attributes": True}


class GroupListOut(BaseModel):
    id: int
    temporary_code: str
    stand: str
    observed_start: datetime
    observed_end: datetime
    assignment_status: str
    assigned_flight_id: int | None
    confidence: float
    margin: float
    issue_tags: list[str]
    lineage: dict[str, Any]
    node_count: int
    review_status: str
    cluster_review_status: str


class AttributedNodeOut(NodeOut):
    phase: Literal["ARRIVAL", "TURNAROUND", "DEPARTURE"]
    attributed_flight_no: str | None


class RelatedFlightSegmentOut(BaseModel):
    group_id: int
    temporary_code: str
    flight_no: str
    phase: Literal["ARRIVAL", "OUTBOUND"]
    stand: str
    aircraft_no: str | None
    node_count: int
    current_group: bool


class GroupDetailOut(GroupListOut):
    nodes: list[AttributedNodeOut]
    candidates: list[CandidateOut]
    reviews: list[ReviewOut]
    cluster_reviews: list[ClusterReviewOut]
    related_segments: list[RelatedFlightSegmentOut] = Field(default_factory=list)
    appearance: AppearanceOut | None = None
    acdm_reference: AcdmReferenceOut | None = None


class AssociationGroupOut(BaseModel):
    group_id: int
    temporary_code: str
    service_date: str
    assignment_status: str
    safeguard_code: str | None
    stand: str
    aircraft_no: str | None
    aircraft_type: str | None
    inbound_flight_no: str | None
    outbound_flight_no: str | None
    observed_start: datetime
    observed_end: datetime
    occupancy_start: datetime
    occupancy_end: datetime
    occupancy_start_source: str
    occupancy_end_source: str
    plan_start: datetime | None
    plan_end: datetime | None
    overrun_minutes: int
    issue_tags: list[str]
    node_count: int
    nodes: list[AttributedNodeOut]


class FlightAssociationOut(BaseModel):
    association_key: str
    flight_no: str
    service_date: str
    groups: list[AssociationGroupOut]
    stands: list[str]
    aircraft: list[str]
    has_aircraft_change: bool
    max_overrun_minutes: int


class AppearanceIn(BaseModel):
    batch_id: int
    temporary_code: str
    airline: str | None = None
    aircraft_type: str | None = None
    aircraft_registration: str | None = Field(default=None, max_length=32)
    registration_confidence: float | None = Field(default=None, ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    evidence_time: datetime
    source_type: Literal["manual_simulation", "appearance_algorithm"] = "manual_simulation"


class AppearanceOut(AppearanceIn):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class RegistrationSimilarityIn(BaseModel):
    observed: str = Field(min_length=1, max_length=32)
    candidate: str = Field(min_length=1, max_length=32)


class RegistrationSimilarityOut(BaseModel):
    observed_normalized: str
    candidate_normalized: str
    similarity: float


class AcdmReferenceIn(BaseModel):
    batch_id: int
    temporary_code: str
    flight_no: str = Field(min_length=2, max_length=32)
    aircraft_entry_time: datetime
    chock_on_time: datetime | None = None
    stand_release_time: datetime | None = None


class AcdmReferenceOut(AcdmReferenceIn):
    id: int
    source_type: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AcdmValidationCaseOut(BaseModel):
    temporary_code: str
    group_id: int | None
    acdm_flight_no: str | None
    sample_status: Literal[
        "AWAITING_ACDM",
        "AWAITING_REVIEW",
        "NEEDS_STRATEGY_FIX",
        "REGRESSION",
        "VALIDATED",
    ]
    baseline_flight_id: int | None
    baseline_flight_no: str | None
    baseline_status: str | None
    current_flight_id: int | None
    current_flight_no: str | None
    final_flight_id: int | None
    final_flight_no: str | None
    final_status: str | None
    review_verdict: str | None
    acdm_matches_final: bool | None
    baseline_strategy_correct: bool | None
    current_strategy_correct: bool | None
    resolved_by_acdm: bool | None
    is_regression: bool


class AcdmValidationSummaryOut(BaseModel):
    run_id: int
    total_cases: int
    reviewed_cases: int
    pending_cases: int
    review_errors: int
    acdm_conflicts: int
    baseline_error_count: int
    resolved_by_acdm_count: int
    regression_count: int
    cases: list[AcdmValidationCaseOut]


class ReviewIn(BaseModel):
    verdict: Literal["correct", "incorrect", "unassigned", "data_error"]
    error_type: str | None = None
    correct_flight_id: int | None = None
    correct_flight_no: str | None = Field(default=None, min_length=2, max_length=32)
    comment: str | None = None
    reviewer: str = "本地核验员"


class StrategyOut(BaseModel):
    id: int
    name: str
    status: str
    based_on_id: int | None
    config: dict[str, Any]
    created_at: datetime
    published_at: datetime | None

    model_config = {"from_attributes": True}


class StrategyCreate(BaseModel):
    name: str
    based_on_id: int | None = None
    config: dict[str, Any]


class RunIn(BaseModel):
    batch_id: int
    strategy_version_id: int


class RunOut(BaseModel):
    id: int
    batch_id: int
    strategy_version_id: int
    status: str
    metrics: dict[str, Any]
    created_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class DashboardOut(BaseModel):
    batch: BatchOut
    active_run: RunOut
    strategy: StrategyOut
    issue_counts: dict[str, int]
    validation: dict[str, Any]


class SuggestionOut(BaseModel):
    key: str
    title: str
    evidence: str
    patch: dict[str, Any]
    affected_groups: int


class RegressionCaseOut(BaseModel):
    temporary_code: str
    source_run_id: int
    current_group_id: int | None
    stand: str
    expected_result: str
    current_result: str
    passed: bool


class AcceptanceOut(BaseModel):
    run_id: int
    required_reviews: int
    completed_reviews: int
    incorrect_reviews: int
    regression_count: int
    node_conservation: bool
    can_publish: bool
    blockers: list[str]
    regression_cases: list[RegressionCaseOut]


class RecoveryPolicyPatch(BaseModel):
    temporary_group_send_enabled: bool | None = None
    flight_recovery_enabled: bool | None = None
    max_attempts: int | None = Field(default=None, ge=1, le=8)
    request_window_before_minutes: int | None = Field(default=None, ge=30, le=360)
    request_window_after_minutes: int | None = Field(default=None, ge=30, le=360)
    recovery_deadline_minutes: int | None = Field(default=None, ge=30, le=360)
    terminal_scan_interval_seconds: int | None = Field(default=None, ge=15, le=300)
    outbox_max_wait_seconds: int | None = Field(default=None, ge=30, le=900)
    max_unassigned_rate: float | None = Field(default=None, ge=0, le=1)
    max_data_error_rate: float | None = Field(default=None, ge=0, le=1)
    recovery_exhausted_disposition: Literal["UNASSIGNED_FINAL"] | None = None
    data_error_recovery_enabled: Literal[False] | None = None
    destination_capability: Literal["UNKNOWN", "SUPPORTED", "UNSUPPORTED"] | None = None

    model_config = {"extra": "forbid"}


class RecoveryPolicyDraftIn(BaseModel):
    airport_code: str = Field(default="XIY", min_length=3, max_length=16)
    tenant_code: str = Field(default="default", min_length=1, max_length=32)
    destination: str = Field(default="xian_bus", min_length=1, max_length=64)
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=100)
    config: RecoveryPolicyPatch


class RecoveryReplayIn(BaseModel):
    run_id: int = Field(gt=0)
    idempotency_key: str = Field(min_length=1, max_length=100)


class RecoveryApproveIn(BaseModel):
    replay_task_id: int = Field(gt=0)


class RecoveryPublishIn(BaseModel):
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=100)
