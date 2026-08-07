import type {
  Acceptance,
  AcdmReference,
  AcdmValidationSummary,
  AssociationGroup,
  Appearance,
  Dashboard,
  FlightAssociation,
  Group,
  GroupDetail,
  NodeAnomalyReport,
  ClusterReview,
  ClusterReviewInput,
  Review,
  Run,
  RecoveryGroupDetail,
  RecoveryPolicy,
  RecoveryPolicyConfig,
  RecoveryQueue,
  RecoveryReplayTask,
  Strategy,
  StrategyConfig,
  Suggestion
} from "./types";

const configuredBase = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "");
export const API_BASE =
  configuredBase || `${window.location.protocol}//${window.location.hostname}:8900`;

class ApiError extends Error {
  constructor(
    message: string,
    public status: number
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    const message = typeof detail === "string"
      ? detail
      : detail?.message || response.statusText;
    throw new ApiError(message, response.status);
  }
  return response.json() as Promise<T>;
}

export const api = {
  dashboard: () => request<Dashboard>("/api/dashboard"),
  groups: (runId?: number) => request<Group[]>(`/api/groups${runId ? `?run_id=${runId}` : ""}`),
  group: (id: number) => request<GroupDetail>(`/api/groups/${id}`),
  nodeAnomalies: (runId: number, problemCode?: string, stand?: string) => {
    const params = new URLSearchParams();
    if (problemCode) params.set("problem_code", problemCode);
    if (stand) params.set("stand", stand);
    const query = params.toString();
    return request<NodeAnomalyReport>(`/api/runs/${runId}/node-anomalies${query ? `?${query}` : ""}`);
  },
  strategies: () => request<Strategy[]>("/api/strategies"),
  recoveryGroups: (status?: string, offset = 0, limit = 100) =>
    request<RecoveryQueue>(`/api/recovery-groups?offset=${offset}&limit=${limit}${status ? `&status=${status}` : ""}`),
  recoveryGroup: (id: number) =>
    request<RecoveryGroupDetail>(`/api/recovery-groups/${id}`),
  recoveryPayloadPreview: (id: number) =>
    request<{ outbound_status: string; reason: string | null; payload: unknown }>(`/api/recovery-groups/${id}/payload-preview`),
  recoveryPolicy: () => request<RecoveryPolicy>("/api/recovery-policies/effective"),
  createRecoveryPolicyDraft: (policy: RecoveryPolicy, config: RecoveryPolicyConfig, idempotencyKey: string) =>
    request<RecoveryPolicy>("/api/recovery-policies/drafts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        airport_code: policy.airport_code,
        tenant_code: policy.tenant_code,
        destination: policy.destination,
        expected_version: policy.version,
        idempotency_key: idempotencyKey,
        config
      })
    }),
  replayRecoveryPolicy: (policyId: number, runId: number, idempotencyKey: string) =>
    request<RecoveryReplayTask>(`/api/recovery-policies/drafts/${policyId}/replays`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: runId, idempotency_key: idempotencyKey })
    }),
  approveRecoveryPolicy: (policyId: number, replayTaskId: number) =>
    request<RecoveryPolicy>(`/api/recovery-policies/drafts/${policyId}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ replay_task_id: replayTaskId })
    }),
  publishRecoveryPolicy: (policyId: number, expectedVersion: number) =>
    request<RecoveryPolicy>(`/api/recovery-policies/drafts/${policyId}/publish`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ idempotency_key: `publish-${policyId}`, expected_version: expectedVersion })
    }),
  suggestions: (runId: number) => request<Suggestion[]>(`/api/runs/${runId}/suggestions`),
  acceptance: (runId: number) => request<Acceptance>(`/api/runs/${runId}/acceptance`),
  acdmValidation: (runId: number) => request<AcdmValidationSummary>(`/api/runs/${runId}/acdm-validation`),
  sampleAcdmValidation: (runId: number, limit = 5) =>
    request<{ selected_codes: string[]; added: number }>(`/api/runs/${runId}/acdm-validation/samples?limit=${limit}`, {
      method: "POST"
    }),
  associationGroups: (runId: number, overrunOnly = false, groupId?: number) =>
    request<AssociationGroup[]>(`/api/runs/${runId}/associations/groups?overrun_only=${overrunOnly}${groupId ? `&group_id=${groupId}&include_nodes=true` : ""}`),
  associationFlights: (runId: number, overrunOnly = false, associationKey?: string) =>
    request<FlightAssociation[]>(`/api/runs/${runId}/associations/flights?overrun_only=${overrunOnly}${associationKey ? `&association_key=${encodeURIComponent(associationKey)}&include_nodes=true` : ""}`),
  review: (
    groupId: number,
    input: {
      verdict: string;
      error_type?: string;
      correct_flight_id?: number;
      correct_flight_no?: string;
      comment?: string;
    }
  ) =>
    request<Review>(`/api/groups/${groupId}/reviews`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input)
    }),
  clusterReview: (groupId: number, input: ClusterReviewInput) =>
    request<ClusterReview>(`/api/groups/${groupId}/cluster-reviews`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input)
    }),
  appearance: (input: {
    batch_id: number;
    temporary_code: string;
    airline: string;
    aircraft_type: string;
    aircraft_registration: string | null;
    registration_confidence: number | null;
    confidence: number;
    evidence_time: string;
  }) =>
    request<Appearance>("/api/features/appearance", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...input, source_type: "manual_simulation" })
    }),
  simulateAcdm: (input: { batch_id: number; temporary_code: string; flight_no: string; aircraft_entry_time: string; chock_on_time: string | null; stand_release_time: string | null }) =>
    request<AcdmReference>("/api/references/acdm/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input)
    }),
  clearAcdm: (batchId: number, temporaryCode: string) =>
    request<{ deleted: number }>(`/api/references/acdm/simulate?batch_id=${batchId}&temporary_code=${encodeURIComponent(temporaryCode)}`, {
      method: "DELETE"
    }),
  createStrategy: (name: string, basedOnId: number, config: StrategyConfig) =>
    request<Strategy>("/api/strategies", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, based_on_id: basedOnId, config })
    }),
  run: (batchId: number, strategyId: number) =>
    request<Run>("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ batch_id: batchId, strategy_version_id: strategyId })
    }),
  split: (groupId: number, nodeId: number) =>
    request<Group[]>(`/api/groups/${groupId}/split?split_node_id=${nodeId}`, {
      method: "POST"
    }),
  merge: (groupIds: number[]) =>
    request<Group>("/api/groups/merge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(groupIds)
    }),
  publish: (strategyId: number, runId: number) =>
    request<Strategy>(`/api/strategies/${strategyId}/publish?run_id=${runId}`, {
      method: "POST"
    }),
  importBatch: (form: FormData) =>
    request<Run>("/api/batches/import", { method: "POST", body: form })
};
