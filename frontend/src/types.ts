export type Batch = {
  id: number;
  name: string;
  airport_code: string;
  status: string;
  source_files: Record<string, unknown>;
  stats: Record<string, number>;
  created_at: string;
};

export type Run = {
  id: number;
  batch_id: number;
  strategy_version_id: number;
  status: string;
  metrics: {
    group_count: number;
    status_counts: Record<string, number>;
    issue_counts: Record<string, number>;
    total_nodes: number;
    accounted_nodes: number;
    node_conservation: boolean;
  };
  created_at: string;
  completed_at: string | null;
};

export type Strategy = {
  id: number;
  name: string;
  status: "draft" | "published";
  based_on_id: number | null;
  config: StrategyConfig;
  created_at: string;
  published_at: string | null;
};

export type StrategyConfig = {
  idle_gap_minutes: number;
  approach_chain_minutes: number;
  terminal_tail_reattach_enabled?: boolean;
  terminal_tail_lookback_minutes?: number;
  terminal_tail_max_nodes?: number;
  terminal_tail_event_policy?: {
    group_start_events: string[];
    aircraft_entry_events: string[];
    aircraft_leave_events: string[];
    tow_end_events: string[];
    allowed_tail_events: string[];
  };
  combination_stand_families?: string[];
  combination_parent_guard_enabled?: boolean;
  open_occupancy_timeout_minutes?: number;
  window_grace_minutes: number;
  sequence_resolution_enabled?: boolean;
  time_decay_minutes?: number;
  plan_end_overrun_minutes: number;
  candidate_radius_hours: number;
  max_plan_hours: number;
  hard_reject_plan_hours: number;
  auto_match_threshold: number;
  minimum_margin: number;
  appearance_confidence_threshold: number;
  acdm_time_tolerance_minutes?: number;
  weights: {
    stand: number;
    time_window: number;
    node_semantics: number;
    continuity: number;
    sequence_order?: number;
    appearance_airline: number;
    appearance_type: number;
    appearance_registration?: number;
  };
};

export type Dashboard = {
  batch: Batch;
  active_run: Run;
  strategy: Strategy;
  issue_counts: Record<string, number>;
  validation: {
    required_reviews: number;
    completed_reviews: number;
    incorrect_reviews: number;
    node_conservation: boolean;
  };
};

export type Group = {
  id: number;
  temporary_code: string;
  stand: string;
  observed_start: string;
  observed_end: string;
  assignment_status: string;
  assigned_flight_id: number | null;
  confidence: number;
  margin: number;
  issue_tags: string[];
  lineage: Record<string, unknown>;
  node_count: number;
  review_status: string;
  cluster_review_status: string;
};

export type ClusterReviewInput = {
  verdict: "correct" | "split_required" | "merge_required" | "anomaly";
  split_node_id?: number | null;
  merge_group_ids?: number[];
  anomaly_node_ids?: number[];
  comment?: string;
  reviewer?: string;
};

export type ClusterReview = ClusterReviewInput & {
  id: number;
  split_node_id: number | null;
  merge_group_ids: number[];
  anomaly_node_ids: number[];
  comment: string | null;
  reviewer: string;
  created_at: string;
};

export type FlightPlan = {
  id: number;
  flight_key: string;
  safeguard_code: string | null;
  inbound_flight_no: string | null;
  outbound_flight_no: string | null;
  stand: string | null;
  plan_start: string | null;
  plan_end: string | null;
  airline: string | null;
  aircraft_type: string | null;
  aircraft_no: string | null;
  issue_tags: string[];
};

export type NodeEvent = {
  id: number;
  source_type: string;
  event_type: string;
  event_time: string | null;
  stand: string | null;
  reported_flight_no: string | null;
  safeguard_code: string | null;
  is_anomaly: boolean;
};

export type Candidate = {
  id: number;
  rank: number;
  score: number;
  score_breakdown: Record<string, number>;
  excluded_reason: string | null;
  selected: boolean;
  flight_plan: FlightPlan;
};

export type Review = {
  id: number;
  verdict: string;
  error_type: string | null;
  correct_flight_id: number | null;
  correct_flight_no: string | null;
  expected_flight_id: number | null;
  expected_flight_no: string | null;
  expected_assignment_status: string | null;
  comment: string | null;
  reviewer: string;
  created_at: string;
};

export type Appearance = {
  id: number;
  batch_id: number;
  temporary_code: string;
  airline: string | null;
  aircraft_type: string | null;
  aircraft_registration: string | null;
  registration_confidence: number | null;
  confidence: number;
  evidence_time: string;
  source_type: string;
  created_at: string;
};

export type AcdmReference = {
  id: number;
  batch_id: number;
  temporary_code: string;
  flight_no: string;
  aircraft_entry_time: string;
  chock_on_time: string | null;
  stand_release_time: string | null;
  source_type: string;
  created_at: string;
};

export type AcdmValidationCase = {
  temporary_code: string;
  group_id: number | null;
  acdm_flight_no: string | null;
  sample_status: "AWAITING_ACDM" | "AWAITING_REVIEW" | "NEEDS_STRATEGY_FIX" | "REGRESSION" | "VALIDATED";
  baseline_flight_id: number | null;
  baseline_flight_no: string | null;
  baseline_status: string | null;
  current_flight_id: number | null;
  current_flight_no: string | null;
  final_flight_id: number | null;
  final_flight_no: string | null;
  final_status: string | null;
  review_verdict: string | null;
  acdm_matches_final: boolean | null;
  baseline_strategy_correct: boolean | null;
  current_strategy_correct: boolean | null;
  resolved_by_acdm: boolean | null;
  is_regression: boolean;
};

export type AcdmValidationSummary = {
  run_id: number;
  total_cases: number;
  reviewed_cases: number;
  pending_cases: number;
  review_errors: number;
  acdm_conflicts: number;
  baseline_error_count: number;
  resolved_by_acdm_count: number;
  regression_count: number;
  cases: AcdmValidationCase[];
};

export type GroupDetail = Group & {
  nodes: AttributedNode[];
  candidates: Candidate[];
  reviews: Review[];
  cluster_reviews: ClusterReview[];
  related_segments: RelatedFlightSegment[];
  appearance: Appearance | null;
  acdm_reference: AcdmReference | null;
};

export type NodePhase = "ARRIVAL" | "TURNAROUND" | "DEPARTURE";

export type AttributedNode = NodeEvent & {
  phase: NodePhase;
  attributed_flight_no: string | null;
};

export type RelatedFlightSegment = {
  group_id: number;
  temporary_code: string;
  flight_no: string;
  phase: "ARRIVAL" | "OUTBOUND";
  stand: string;
  aircraft_no: string | null;
  node_count: number;
  current_group: boolean;
};

export type AssociationGroup = {
  group_id: number;
  temporary_code: string;
  service_date: string;
  assignment_status: string;
  safeguard_code: string | null;
  stand: string;
  aircraft_no: string | null;
  aircraft_type: string | null;
  inbound_flight_no: string | null;
  outbound_flight_no: string | null;
  observed_start: string;
  observed_end: string;
  occupancy_start: string;
  occupancy_end: string;
  occupancy_start_source: string;
  occupancy_end_source: string;
  plan_start: string | null;
  plan_end: string | null;
  overrun_minutes: number;
  issue_tags: string[];
  node_count: number;
  nodes: AttributedNode[];
};

export type FlightAssociation = {
  association_key: string;
  flight_no: string;
  service_date: string;
  groups: AssociationGroup[];
  stands: string[];
  aircraft: string[];
  has_aircraft_change: boolean;
  max_overrun_minutes: number;
};

export type Suggestion = {
  key: string;
  title: string;
  evidence: string;
  patch: Partial<StrategyConfig> & { weights?: Partial<StrategyConfig["weights"]> };
  affected_groups: number;
};

export type Acceptance = {
  run_id: number;
  required_reviews: number;
  completed_reviews: number;
  incorrect_reviews: number;
  regression_count: number;
  node_conservation: boolean;
  can_publish: boolean;
  blockers: string[];
  regression_cases: RegressionCase[];
};

export type RegressionCase = {
  temporary_code: string;
  source_run_id: number;
  current_group_id: number | null;
  stand: string;
  expected_result: string;
  current_result: string;
  passed: boolean;
};

export type RecoveryGroup = {
  id: number;
  group_id: number;
  temporary_code: string;
  airport_code: string;
  stand: string;
  observed_start: string;
  observed_end: string;
  node_count: number;
  group_version: number;
  member_hash: string;
  machine_status: string;
  reason_code: string;
  attempt_count: number;
  max_attempts: number;
  recovery_deadline: string | null;
  next_attempt_at: string | null;
  last_attempt_at: string | null;
  recovery_request_id: string | null;
  request_window_start: string | null;
  request_window_end: string | null;
  response_flight_count: number;
  candidates: Array<{ flight_plan_id: number; rank: number; score: number }>;
  outbound_policy: string;
  outbox_status: string;
  config_version: number;
  strategy_version: number;
  finalized_at: string | null;
  issue_tags: string[];
  item_version?: string | null;
};

export type RecoveryQueue = {
  run_id: number;
  as_of: string;
  total: number;
  offset: number;
  limit: number;
  statistics: Record<string, number>;
  items: RecoveryGroup[];
  cursor?: string;
  next_cursor?: string | null;
};

export type RecoveryGroupDetail = RecoveryGroup & {
  nodes: NodeEvent[];
  cluster_boundary: Record<string, unknown>;
  first_evaluation: Record<string, unknown>;
  attempts: Array<Record<string, unknown>>;
  status_timeline: Array<{ status: string; at: string; reason: string }>;
  raw_audit: Record<string, unknown>;
};

export type RecoveryPolicyConfig = {
  temporary_group_send_enabled: boolean;
  flight_recovery_enabled: boolean;
  max_attempts: number;
  request_window_before_minutes: number;
  request_window_after_minutes: number;
  recovery_deadline_minutes: number;
  terminal_scan_interval_seconds: number;
  outbox_max_wait_seconds: number;
  max_unassigned_rate: number;
  max_data_error_rate: number;
  recovery_exhausted_disposition: "UNASSIGNED_FINAL";
  data_error_recovery_enabled: false;
  destination_capability: "UNKNOWN" | "SUPPORTED" | "UNSUPPORTED";
};

export type RecoveryPolicy = {
  id: number;
  airport_code: string;
  tenant_code: string;
  destination: string;
  version: number;
  status: string;
  config: RecoveryPolicyConfig;
  temporary_group_send_locked: boolean;
  created_at: string;
  approved_at: string | null;
  published_at: string | null;
};

export type RecoveryReplayTask = {
  id: number;
  policy_id: number;
  status: "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED";
  progress: number;
  evidence: Record<string, unknown>;
  error: string | null;
  created_at: string;
  completed_at: string | null;
};

export type NodeAnomalyOccurrence = {
  node_id: number;
  event_type: string;
  event_time: string;
};

export type NodeAnomaly = {
  id: string;
  group_id: number;
  temporary_code: string;
  stand: string;
  problem_code: "RAPID_REPEAT" | "GUIDE_CAR_ONLY" | string;
  problem_type: string;
  reason: string;
  window_start: string;
  window_end: string;
  group_start: string;
  group_end: string;
  group_node_count: number;
  affected_node_count: number;
  event_types: string[];
  occurrences: NodeAnomalyOccurrence[];
  group_version?: number | null;
  member_hash?: string | null;
};

export type NodeAnomalyReport = {
  run_id: number;
  repeat_window_minutes: number;
  statistics: {
    total: number;
    affected_stands: number;
    rapid_repeat: number;
    guide_car_only: number;
    by_type: Record<string, number>;
    by_stand_and_node?: Array<{
      stand: string;
      node_type: string;
      affected_group_count: number;
      occurrence_count: number;
    }>;
  };
  items: NodeAnomaly[];
};
