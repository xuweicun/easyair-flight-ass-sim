from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    airport_code: Mapped[str] = mapped_column(String(16), nullable=False, default="XIY")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    source_files: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    plans: Mapped[list[FlightPlan]] = relationship(back_populates="batch", cascade="all, delete-orphan")
    nodes: Mapped[list[NodeEvent]] = relationship(back_populates="batch", cascade="all, delete-orphan")


class FlightPlan(Base):
    __tablename__ = "flight_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"))
    flight_key: Mapped[str] = mapped_column(String(100), nullable=False)
    safeguard_code: Mapped[str | None] = mapped_column(String(100))
    inbound_flight_no: Mapped[str | None] = mapped_column(String(32))
    outbound_flight_no: Mapped[str | None] = mapped_column(String(32))
    stand: Mapped[str | None] = mapped_column(String(32), index=True)
    plan_start: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    plan_end: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    airline: Mapped[str | None] = mapped_column(String(32))
    aircraft_type: Mapped[str | None] = mapped_column(String(32))
    aircraft_no: Mapped[str | None] = mapped_column(String(32))
    issue_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    batch: Mapped[Batch] = relationship(back_populates="plans")

    __table_args__ = (Index("ix_flight_plans_batch_stand", "batch_id", "stand"),)


class NodeEvent(Base):
    __tablename__ = "node_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"))
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_row_id: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    event_time: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    stand: Mapped[str | None] = mapped_column(String(32), index=True)
    reported_flight_no: Mapped[str | None] = mapped_column(String(32))
    safeguard_code: Mapped[str | None] = mapped_column(String(100))
    is_anomaly: Mapped[bool] = mapped_column(default=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    batch: Mapped[Batch] = relationship(back_populates="nodes")

    __table_args__ = (
        UniqueConstraint("batch_id", "source_type", "source_row_id", name="uq_node_source_row"),
        Index("ix_node_events_batch_stand_time", "batch_id", "stand", "event_time"),
    )


class StrategyVersion(Base):
    __tablename__ = "strategy_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    based_on_id: Mapped[int | None] = mapped_column(ForeignKey("strategy_versions.id"))
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)


class SimulationRun(Base):
    __tablename__ = "simulation_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"))
    strategy_version_id: Mapped[int] = mapped_column(ForeignKey("strategy_versions.id"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class FlightGroup(Base):
    __tablename__ = "flight_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("simulation_runs.id", ondelete="CASCADE"))
    temporary_code: Mapped[str] = mapped_column(String(100), nullable=False)
    stand: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    observed_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    assignment_status: Mapped[str] = mapped_column(String(32), nullable=False)
    assigned_flight_id: Mapped[int | None] = mapped_column(ForeignKey("flight_plans.id"))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    margin: Mapped[float] = mapped_column(Float, default=0.0)
    issue_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    lineage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    nodes: Mapped[list[GroupNode]] = relationship(cascade="all, delete-orphan")
    candidates: Mapped[list[MatchCandidate]] = relationship(cascade="all, delete-orphan")
    reviews: Mapped[list[Review]] = relationship(cascade="all, delete-orphan")
    cluster_reviews: Mapped[list[ClusterReview]] = relationship(cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("run_id", "temporary_code", name="uq_run_temporary_code"),
        Index("ix_groups_run_status", "run_id", "assignment_status"),
    )


class AcdmReferenceFeature(Base):
    __tablename__ = "acdm_reference_features"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"))
    temporary_code: Mapped[str] = mapped_column(String(100), nullable=False)
    flight_no: Mapped[str] = mapped_column(String(32), nullable=False)
    node_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_type: Mapped[str] = mapped_column(String(32), default="acdm_simulation")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (Index("ix_acdm_reference_batch_group", "batch_id", "temporary_code"),)

    @property
    def aircraft_entry_time(self) -> datetime:
        return datetime.fromisoformat(self.node_payload["aircraft_entry_time"])

    @property
    def chock_on_time(self) -> datetime | None:
        value = self.node_payload.get("chock_on_time")
        return datetime.fromisoformat(value) if value else None

    @property
    def stand_release_time(self) -> datetime | None:
        value = self.node_payload.get("stand_release_time")
        return datetime.fromisoformat(value) if value else None


class ValidationSample(Base):
    __tablename__ = "validation_samples"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"))
    temporary_code: Mapped[str] = mapped_column(String(100), nullable=False)
    source_run_id: Mapped[int] = mapped_column(Integer, nullable=False)
    node_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    selected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("batch_id", "temporary_code", name="uq_validation_sample_batch_code"),
        Index("ix_validation_samples_batch_selected", "batch_id", "selected_at"),
    )


class GroupNode(Base):
    __tablename__ = "group_nodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("flight_groups.id", ondelete="CASCADE"))
    node_id: Mapped[int] = mapped_column(ForeignKey("node_events.id"))
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)

    node: Mapped[NodeEvent] = relationship()

    __table_args__ = (UniqueConstraint("group_id", "node_id", name="uq_group_node"),)


class MatchCandidate(Base):
    __tablename__ = "match_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("flight_groups.id", ondelete="CASCADE"))
    flight_plan_id: Mapped[int] = mapped_column(ForeignKey("flight_plans.id"))
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    score_breakdown: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    excluded_reason: Mapped[str | None] = mapped_column(String(200))
    selected: Mapped[bool] = mapped_column(default=False)

    flight_plan: Mapped[FlightPlan] = relationship()


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("flight_groups.id", ondelete="CASCADE"))
    verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(64))
    correct_flight_id: Mapped[int | None] = mapped_column(ForeignKey("flight_plans.id"))
    correct_flight_no: Mapped[str | None] = mapped_column(String(32))
    expected_flight_id: Mapped[int | None] = mapped_column(ForeignKey("flight_plans.id"))
    expected_flight_no: Mapped[str | None] = mapped_column(String(32))
    expected_assignment_status: Mapped[str | None] = mapped_column(String(32))
    comment: Mapped[str | None] = mapped_column(Text)
    reviewer: Mapped[str] = mapped_column(String(100), default="本地核验员")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ClusterReview(Base):
    __tablename__ = "cluster_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("flight_groups.id", ondelete="CASCADE"))
    verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    split_node_id: Mapped[int | None] = mapped_column(ForeignKey("node_events.id"))
    merge_group_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    anomaly_node_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    comment: Mapped[str | None] = mapped_column(Text)
    reviewer: Mapped[str] = mapped_column(String(100), default="本地核验员")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (Index("ix_cluster_reviews_group_created", "group_id", "created_at"),)


class AppearanceFeature(Base):
    __tablename__ = "appearance_features"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"))
    temporary_code: Mapped[str] = mapped_column(String(100), nullable=False)
    airline: Mapped[str | None] = mapped_column(String(32))
    aircraft_type: Mapped[str | None] = mapped_column(String(32))
    aircraft_registration: Mapped[str | None] = mapped_column(String(32))
    registration_confidence: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="manual_simulation")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RecoveryPolicy(Base):
    __tablename__ = "recovery_policies"

    id: Mapped[int] = mapped_column(primary_key=True)
    airport_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    tenant_code: Mapped[str] = mapped_column(String(32), nullable=False, default="default")
    destination: Mapped[str] = mapped_column(String(64), nullable=False, default="xian_bus")
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    publish_idempotency_key: Mapped[str | None] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint(
            "airport_code", "tenant_code", "destination", "version",
            name="uq_recovery_policy_scope_version",
        ),
    )


class RecoveryResolution(Base):
    __tablename__ = "recovery_resolutions"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("flight_groups.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    group_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    member_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    machine_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    recovery_deadline: Mapped[datetime | None] = mapped_column(DateTime)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    request_window_start: Mapped[datetime | None] = mapped_column(DateTime)
    request_window_end: Mapped[datetime | None] = mapped_column(DateTime)
    response_flight_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recovery_request_id: Mapped[str | None] = mapped_column(String(100))
    candidate_summary: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    status_timeline: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    outbound_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    outbox_status: Mapped[str] = mapped_column(String(32), nullable=False)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False)
    strategy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    group: Mapped[FlightGroup] = relationship()


class RecoveryAttempt(Base):
    __tablename__ = "recovery_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    resolution_id: Mapped[int] = mapped_column(
        ForeignKey("recovery_resolutions.id", ondelete="CASCADE"), nullable=False
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[str] = mapped_column(String(100), nullable=False)
    request_window_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    request_window_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    response_flight_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    candidates_before: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    candidates_after: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("resolution_id", "attempt_no", name="uq_recovery_attempt_no"),
    )


class RecoveryReplayTask(Base):
    __tablename__ = "recovery_replay_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    policy_id: Mapped[int] = mapped_column(
        ForeignKey("recovery_policies.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class RecoveryNodeDisposition(Base):
    __tablename__ = "recovery_node_dispositions"

    id: Mapped[int] = mapped_column(primary_key=True)
    resolution_id: Mapped[int] = mapped_column(
        ForeignKey("recovery_resolutions.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[int] = mapped_column(
        ForeignKey("flight_groups.id", ondelete="CASCADE"), nullable=False
    )
    node_id: Mapped[int] = mapped_column(ForeignKey("node_events.id"), nullable=False)
    disposition: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("group_id", "node_id", name="uq_recovery_node_disposition"),
    )


class RecoveryDelivery(Base):
    __tablename__ = "recovery_deliveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    resolution_id: Mapped[int] = mapped_column(
        ForeignKey("recovery_resolutions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    group_id: Mapped[int] = mapped_column(
        ForeignKey("flight_groups.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    policy_action: Mapped[str] = mapped_column(String(32), nullable=False)
    outbox_status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    suppression_reason: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
