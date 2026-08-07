import { api, API_BASE } from "./api";
import type {
  AttributedNode,
  Candidate,
  Dashboard,
  FlightPlan,
  Group,
  GroupDetail,
  NodeAnomaly,
  NodeAnomalyReport,
  NodeEvent,
  RecoveryGroup,
  RecoveryGroupDetail,
  RecoveryQueue
} from "./types";

export type DataSourceKind = "simulator" | "java-shadow";

export type TemporaryGroupOutboundContext = {
  enabled: boolean;
  locked: boolean;
  destination_supported: boolean;
  disposition: string;
  reason: string;
};

export type DataSourceContext = {
  source: DataSourceKind;
  data_source: string;
  label: string;
  read_only: boolean;
  authoritative: boolean;
  as_of: string;
  airport_code: string;
  airport_name: string;
  strategy_name: string;
  strategy_version: string;
  source_config_hash: string | null;
  rollout_config_version: string | null;
  release_key: string | null;
  total_nodes: number | null;
  accounted_nodes: number | null;
  temporary_group_outbound: TemporaryGroupOutboundContext;
  simulator_dashboard?: Dashboard;
};

export type PageRequest = {
  status?: string;
  query?: string;
  cursor?: string;
  limit?: number;
  stand?: string;
  eventNames?: string[];
  minCount?: number;
  snapshotVersion?: string;
};

export type GroupPage = {
  as_of: string;
  total: number;
  cursor: string;
  next_cursor: string | null;
  snapshot_version?: string | null;
  items: Group[];
};

export type RecoveryPayloadPreview = {
  outbound_status: string;
  reason: string | null;
  payload: unknown;
};

export type NodeAnomalyExportUrls = {
  reportJson?: string;
  reportExcel: string;
  statisticsExcel: string;
};

export interface FlightMatchDataSource {
  readonly kind: DataSourceKind;
  readonly label: string;
  readonly readOnly: boolean;
  context(): Promise<DataSourceContext>;
  groups(request?: PageRequest): Promise<GroupPage>;
  group(id: number, itemVersion?: string | null,
    expectedGroupVersion?: number | null, expectedMemberHash?: string | null): Promise<GroupDetail>;
  recoveryGroups(request?: PageRequest): Promise<RecoveryQueue>;
  recoveryGroup(id: number, itemVersion?: string | null): Promise<RecoveryGroupDetail>;
  recoveryPayloadPreview(id: number, itemVersion?: string | null): Promise<RecoveryPayloadPreview>;
  nodeAnomalies(request?: PageRequest): Promise<NodeAnomalyReport>;
  nodeAnomalyExportUrls?(query: string): NodeAnomalyExportUrls;
}

export class SimulatorDataSource implements FlightMatchDataSource {
  readonly kind = "simulator" as const;
  readonly label = "仿真数据";
  readonly readOnly = false;
  private dashboard: Dashboard | null = null;

  async context(): Promise<DataSourceContext> {
    const dashboard = await api.dashboard();
    this.dashboard = dashboard;
    return {
      source: this.kind,
      data_source: "SIMULATOR",
      label: this.label,
      read_only: false,
      authoritative: false,
      as_of: dashboard.active_run.completed_at || dashboard.active_run.created_at,
      airport_code: dashboard.batch.airport_code,
      airport_name: dashboard.batch.name,
      strategy_name: dashboard.strategy.name,
      strategy_version: String(dashboard.strategy.id),
      source_config_hash: null,
      rollout_config_version: null,
      release_key: null,
      total_nodes: dashboard.active_run.metrics.total_nodes,
      accounted_nodes: dashboard.active_run.metrics.accounted_nodes,
      temporary_group_outbound: {
        enabled: false,
        locked: true,
        destination_supported: false,
        disposition: "SUPPRESSED_BY_POLICY",
        reason: "西安总线不接收临时保障组"
      },
      simulator_dashboard: dashboard
    };
  }

  async groups(): Promise<GroupPage> {
    const dashboard = await this.ensureDashboard();
    const items = await api.groups(dashboard.active_run.id);
    return {
      as_of: dashboard.active_run.completed_at || dashboard.active_run.created_at,
      total: items.length,
      cursor: "0",
      next_cursor: null,
      snapshot_version: null,
      items
    };
  }

  group(id: number): Promise<GroupDetail> {
    return api.group(id);
  }

  async recoveryGroups(request: PageRequest = {}): Promise<RecoveryQueue> {
    const status = request.status && request.status !== "ALL" ? request.status : undefined;
    const offset = numberValue(request.cursor, 0);
    return api.recoveryGroups(status, offset, request.limit || 100);
  }

  recoveryGroup(id: number): Promise<RecoveryGroupDetail> {
    return api.recoveryGroup(id);
  }

  recoveryPayloadPreview(id: number): Promise<RecoveryPayloadPreview> {
    return api.recoveryPayloadPreview(id);
  }

  async nodeAnomalies(request: PageRequest = {}): Promise<NodeAnomalyReport> {
    const dashboard = await this.ensureDashboard();
    const status = request.status && request.status !== "ALL" ? request.status : undefined;
    return api.nodeAnomalies(dashboard.active_run.id, status);
  }

  nodeAnomalyExportUrls(query: string): NodeAnomalyExportUrls {
    if (!this.dashboard) throw new Error("仿真运行尚未载入");
    const prefix = `${API_BASE}/api/runs/${this.dashboard.active_run.id}/exports/node-anomaly-stand`;
    const suffix = query ? `?${query}` : "";
    return {
      reportJson: `${prefix}-report.json${suffix}`,
      reportExcel: `${prefix}-report.xlsx${suffix}`,
      statisticsExcel: `${prefix}-statistics.xlsx${suffix}`
    };
  }

  private async ensureDashboard(): Promise<Dashboard> {
    if (!this.dashboard) await this.context();
    return this.dashboard!;
  }
}

const configuredJavaBase = (import.meta.env.VITE_JAVA_SHADOW_API_BASE_URL as string | undefined)?.replace(/\/$/, "");
export const JAVA_SHADOW_API_BASE = configuredJavaBase || window.location.origin;
const JAVA_OPERATIONS_PREFIX = "/internal/xian/node-matching/operations";

export class JavaShadowDataSource implements FlightMatchDataSource {
  readonly kind = "java-shadow" as const;
  readonly label = "Java影子结果";
  readonly readOnly = true;

  async context(): Promise<DataSourceContext> {
    const raw = body(await this.get("/context"));
    const outbound = { ...raw, ...record(raw.temporary_group_outbound || raw.temporary_group_policy || raw.outbound_policy) };
    return {
      source: this.kind,
      data_source: stringValue(raw.data_source, "JAVA_SHADOW"),
      label: this.label,
      read_only: true,
      authoritative: booleanValue(raw.authoritative, false),
      as_of: stringValue(raw.as_of, new Date().toISOString()),
      airport_code: stringValue(raw.airport_code, "XIY"),
      airport_name: stringValue(raw.airport_name, "西安机场"),
      strategy_name: stringValue(raw.strategy_name || raw.strategy, "Java SHADOW"),
      strategy_version: stringValue(raw.strategy_version, "-") ,
      source_config_hash: nullableString(raw.source_config_hash || raw.config_hash),
      rollout_config_version: nullableString(raw.rollout_config_version),
      release_key: nullableString(raw.release_key),
      total_nodes: nullableNumber(raw.total_nodes),
      accounted_nodes: nullableNumber(raw.accounted_nodes),
      temporary_group_outbound: {
        enabled: booleanValue(outbound.enabled ?? outbound.temporary_group_send_enabled, false),
        locked: booleanValue(outbound.locked ?? outbound.temporary_group_send_locked, true),
        destination_supported: booleanValue(outbound.destination_supported, false),
        disposition: stringValue(outbound.disposition, "SUPPRESSED_BY_POLICY"),
        reason: stringValue(outbound.reason, "西安总线不接收临时保障组")
      }
    };
  }

  async groups(request: PageRequest = {}): Promise<GroupPage> {
    const raw = body(await this.get("/groups", javaPageParams(request, true)));
    const items = arrayValue(raw.items || raw.groups).map((item) => mapGroup(record(item)));
    const statistics = record(raw.statistics);
    return {
      as_of: stringValue(raw.as_of, new Date().toISOString()),
      total: numberValue(raw.total ?? statistics.total, items.length),
      cursor: String(numberValue(raw.offset, numberValue(request.cursor, 0))),
      next_cursor: items.length < numberValue(raw.limit, request.limit || 100)
        ? null : String(numberValue(raw.offset, numberValue(request.cursor, 0)) + items.length),
      snapshot_version: nullableString(raw.snapshot_version),
      items
    };
  }

  nodeAnomalyExportUrls(query: string): NodeAnomalyExportUrls {
    const source = new URLSearchParams(query);
    const params = new URLSearchParams();
    source.getAll("node_type").forEach((value) => params.append("eventNames", value));
    const minimum = source.get("minimum_quantity");
    if (minimum) params.set("minCount", minimum);
    const problem = source.get("problem_code");
    if (problem) params.set("problemCode", problem);
    for (const name of ["stand", "query"]) {
      const value = source.get(name);
      if (value) params.set(name, value);
    }
    const suffix = params.toString() ? `?${params}` : "";
    const base = `${JAVA_SHADOW_API_BASE}${JAVA_OPERATIONS_PREFIX}/node-anomalies/export`;
    return {
      reportExcel: `${base}/report.csv${suffix}`,
      statisticsExcel: `${base}/statistics.csv${suffix}`
    };
  }

  async group(id: number, itemVersion?: string | null,
              expectedGroupVersion?: number | null,
              expectedMemberHash?: string | null): Promise<GroupDetail> {
    const raw = body(await this.get(`/groups/${id}`,
      versionParams(itemVersion, expectedGroupVersion, expectedMemberHash)));
    return mapGroupDetail(record(raw));
  }

  async recoveryGroups(request: PageRequest = {}): Promise<RecoveryQueue> {
    const raw = body(await this.get("/recovery-groups", javaPageParams(request, true)));
    const items = arrayValue(raw.items || raw.groups).map((item) => mapRecoveryGroup(record(item)));
    const statistics = recoveryStatistics(record(raw.statistics));
    const offset = numberValue(raw.offset, numberValue(request.cursor, 0));
    const limit = numberValue(raw.limit, request.limit || 100);
    const total = numberValue(raw.total ?? record(raw.statistics).total, items.length);
    return {
      run_id: numberValue(raw.run_id, 0),
      as_of: stringValue(raw.as_of, new Date().toISOString()),
      total,
      offset,
      limit,
      cursor: stringValue(raw.cursor, String(offset)),
      next_cursor: raw.next_cursor == null
        ? offset + items.length < total ? String(offset + items.length) : null
        : nullableString(raw.next_cursor),
      statistics,
      items
    };
  }

  async recoveryGroup(id: number, itemVersion?: string | null): Promise<RecoveryGroupDetail> {
    const raw = body(await this.get(`/recovery-groups/${id}`, versionParams(itemVersion)));
    const group = record(raw.group);
    const intent = record(raw.recovery_intent);
    const currentResolution = record(arrayValue(raw.resolutions)[0]);
    const request = record(raw.request);
    const responses = arrayValue(raw.responses).map(record);
    const base = mapRecoveryGroup({
      ...group,
      ...currentResolution,
      ...intent,
      outbound_disposition: raw.outbound_disposition
    });
    const transitions = arrayValue(raw.resolution_transitions);
    const history = arrayValue(raw.candidate_history);
    return {
      ...base,
      nodes: arrayValue(raw.nodes).map((item) => mapNode(record(item))),
      cluster_boundary: Object.keys(record(raw.cluster_boundary)).length
        ? record(raw.cluster_boundary)
        : { observed_start: base.observed_start, observed_end: base.observed_end },
      first_evaluation: Object.keys(record(raw.first_evaluation)).length
        ? record(raw.first_evaluation) : record(history[0]),
      attempts: arrayValue(raw.attempts).map((item) => {
        const attempt = record(item);
        const attemptId = numberValue(attempt.attempt_id);
        const attemptResponses = responses.filter((response) => numberValue(response.attempt_id) === attemptId);
        return {
          ...attempt,
          request_id: request.request_id,
          response_flight_count: attemptResponses.length,
          responses: attemptResponses
        };
      }),
      status_timeline: arrayValue(raw.status_timeline || transitions).map((item) => {
        const row = record(item);
        return {
          status: stringValue(row.status || row.to_status, "UNKNOWN"),
          at: stringValue(row.at || row.create_time, base.observed_end),
          reason: stringValue(row.reason || row.reason_code, "-")
        };
      }),
      raw_audit: {
        ...record(raw.raw_audit || raw.audit),
        outbound: arrayValue(raw.outbound_audit),
        request,
        responses,
        request_outbox: arrayValue(raw.request_outbox)
      }
    };
  }

  async recoveryPayloadPreview(id: number, itemVersion?: string | null): Promise<RecoveryPayloadPreview> {
    const raw = body(await this.get(`/recovery-groups/${id}/payload-preview`, versionParams(itemVersion)));
    const payloads = arrayValue(raw.payloads);
    const suppressed = booleanValue(raw.suppressed, true);
    return {
      outbound_status: stringValue(raw.outbound_status,
        suppressed ? "SUPPRESSED_BY_POLICY" : stringValue(record(payloads[0]).status, "PREVIEW")),
      reason: nullableString(raw.reason || raw.suppression_reason),
      payload: raw.payload ?? (payloads.length ? payloads : null)
    };
  }

  async nodeAnomalies(request: PageRequest = {}): Promise<NodeAnomalyReport> {
    const requestedLimit = Math.max(1, request.limit || 100);
    const startOffset = Math.max(0, numberValue(request.cursor, 0));
    let raw: Record<string, unknown> | null = null;
    const rows: unknown[] = [];
    while (rows.length < requestedLimit) {
      const pageLimit = Math.min(200, requestedLimit - rows.length);
      const pageRequest = { ...request, cursor: String(startOffset + rows.length), limit: pageLimit };
      const page = body(await this.get("/node-anomalies", javaNodeAnomalyParams(pageRequest)));
      if (!raw) raw = page;
      const pageRows = arrayValue(page.items || page.anomalies);
      rows.push(...pageRows);
      const total = numberValue(record(page.statistics).total, rows.length);
      if (pageRows.length < pageLimit || startOffset + rows.length >= total) break;
    }
    raw = raw || {};
    raw.items = rows;
    const statistics = record(raw.statistics);
    const items = arrayValue(raw.items || raw.anomalies).map((item) => mapNodeAnomaly(record(item)));
    const byStandAndNode = arrayValue(statistics.by_stand_and_node).map((item) => {
      const row = record(item);
      return {
        stand: stringValue(row.stand, "-"),
        node_type: stringValue(row.node_type, "Unknown"),
        affected_group_count: numberValue(row.affected_group_count),
        occurrence_count: numberValue(row.occurrence_count)
      };
    });
    const byType = numberRecord(statistics.by_type);
    if (!Object.keys(byType).length) {
      arrayValue(statistics.by_stand_and_node).forEach((item) => {
        const row = record(item);
        const nodeType = stringValue(row.node_type, "Unknown");
        const label = nodeType === "GUIDE_ONLY" ? "只有引导车节点" : nodeType;
        byType[label] = (byType[label] || 0) + numberValue(row.affected_group_count, 0);
      });
      if (!Object.keys(byType).length) {
        items.forEach((item) => { byType[item.problem_type] = (byType[item.problem_type] || 0) + 1; });
      }
    }
    return {
      run_id: numberValue(raw.run_id, 0),
      repeat_window_minutes: numberValue(raw.repeat_window_minutes, 5),
      statistics: {
        total: numberValue(statistics.total, items.length),
        affected_stands: numberValue(statistics.affected_stands ?? statistics.affected_stand_count,
          new Set(items.map((item) => item.stand)).size),
        rapid_repeat: numberValue(statistics.rapid_repeat,
          items.filter((item) => item.problem_code === "RAPID_REPEAT").length),
        guide_car_only: numberValue(statistics.guide_car_only,
          items.filter((item) => item.problem_code === "GUIDE_CAR_ONLY").length),
        by_type: byType,
        by_stand_and_node: byStandAndNode
      },
      items
    };
  }

  private async get(path: string, params?: URLSearchParams): Promise<unknown> {
    const query = params?.toString();
    const response = await fetch(`${JAVA_SHADOW_API_BASE}${JAVA_OPERATIONS_PREFIX}${path}${query ? `?${query}` : ""}`, {
      method: "GET",
      headers: { Accept: "application/json" }
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => null) as Record<string, unknown> | null;
      const detail = payload?.detail || payload?.message;
      if (response.status === 409) throw new JavaShadowSnapshotChangedError();
      throw new Error(typeof detail === "string" ? detail : `Java影子接口请求失败（${response.status}）`);
    }
    return normalizeKeys(await response.json());
  }
}

export class JavaShadowSnapshotChangedError extends Error {
  constructor() {
    super("Java影子结果已更新，请刷新后重新查看");
    this.name = "JavaShadowSnapshotChangedError";
  }
}

export function createDataSource(kind: DataSourceKind): FlightMatchDataSource {
  return kind === "java-shadow" ? new JavaShadowDataSource() : new SimulatorDataSource();
}

function mapGroup(row: Record<string, unknown>): Group {
  const latest = record(row.latest_evaluation || row.evaluation || row.resolution);
  return {
    id: numberValue(row.id || row.group_id),
    temporary_code: stringValue(row.temporary_code || row.group_code || row.group_key,
      `GROUP-${stringValue(row.id || row.group_id, "-")}`),
    stand: stringValue(row.stand || row.stand_code, "-") ,
    observed_start: stringValue(row.observed_start || row.window_start, new Date(0).toISOString()),
    observed_end: stringValue(row.observed_end || row.window_end, new Date(0).toISOString()),
    assignment_status: stringValue(row.assignment_status || row.machine_status || latest.assignment_status || latest.status, "NEEDS_REVIEW"),
    assigned_flight_id: nullableNumber(row.assigned_flight_id || latest.assigned_flight_id || latest.flight_plan_id),
    confidence: confidenceValue(row.confidence ?? latest.confidence),
    margin: numberValue(row.margin ?? latest.margin, 0),
    issue_tags: stringArray(row.issue_tags || row.problem_tags || row.reason_code),
    lineage: {
      ...record(row.lineage),
      item_version: nullableString(row.item_version),
      member_hash: nullableString(row.member_hash),
      group_version: nullableNumber(row.group_version || row.current_version),
      as_of: nullableString(row.as_of)
    },
    node_count: numberValue(row.node_count, arrayValue(row.nodes).length),
    review_status: stringValue(row.review_status, "pending"),
    cluster_review_status: stringValue(row.cluster_review_status, "pending")
  };
}

function mapGroupDetail(row: Record<string, unknown>): GroupDetail {
  row = { ...record(row.group), ...row };
  const resolution = record(row.current_resolution || row.latest_resolution || row.resolution || arrayValue(row.resolutions)[0]);
  const base = mapGroup({ ...row, resolution });
  const nodes = arrayValue(row.nodes || row.node_timeline).map((item) => mapAttributedNode(record(item)));
  const candidates = arrayValue(row.candidates || row.candidate_snapshots || resolution.candidates).map((item, index) => mapCandidate(record(item), index));
  return {
    ...base,
    node_count: numberValue(row.node_count, nodes.length),
    nodes,
    candidates,
    reviews: arrayValue(row.reviews).map((item) => {
      const value = record(item);
      return {
        id: numberValue(value.id),
        verdict: stringValue(value.verdict),
        error_type: nullableString(value.error_type),
        correct_flight_id: nullableNumber(value.correct_flight_id),
        correct_flight_no: nullableString(value.correct_flight_no),
        expected_flight_id: nullableNumber(value.expected_flight_id),
        expected_flight_no: nullableString(value.expected_flight_no),
        expected_assignment_status: nullableString(value.expected_assignment_status),
        comment: nullableString(value.comment),
        reviewer: stringValue(value.reviewer, "system"),
        created_at: stringValue(value.created_at, base.observed_end)
      };
    }),
    cluster_reviews: [],
    related_segments: arrayValue(row.related_segments).map((item) => {
      const value = record(item);
      return {
        group_id: numberValue(value.group_id),
        temporary_code: stringValue(value.temporary_code),
        flight_no: stringValue(value.flight_no),
        phase: stringValue(value.phase, "OUTBOUND") === "ARRIVAL" ? "ARRIVAL" : "OUTBOUND",
        stand: stringValue(value.stand),
        aircraft_no: nullableString(value.aircraft_no || value.aircraft_registration),
        node_count: numberValue(value.node_count),
        current_group: booleanValue(value.current_group, false)
      };
    }),
    appearance: null,
    acdm_reference: null
  };
}

function mapCandidate(row: Record<string, unknown>, index: number): Candidate {
  const snapshot = snapshotRecord(row.candidate_snapshot_json || row.candidate_snapshot || row.snapshot_json || row.snapshot);
  const planRow = record(row.flight_plan || snapshot.flight_plan || snapshot.plan || snapshot);
  const flightPlan = mapFlightPlan(planRow, row, index);
  return {
    id: numberValue(row.id || row.candidate_id, index + 1),
    rank: numberValue(row.rank || row.rank_no, index + 1),
    score: numberValue(row.score ?? row.total_score),
    score_breakdown: numberRecord(row.score_breakdown || row.evidence || parseJson(row.score_breakdown_json || row.evidence_json)),
    excluded_reason: nullableString(row.excluded_reason || firstString(row.exclusions)),
    selected: booleanValue(row.selected, false),
    flight_plan: flightPlan
  };
}

function mapFlightPlan(plan: Record<string, unknown>, candidate: Record<string, unknown>, index: number): FlightPlan {
  const arrival = record(plan.arrival);
  const departure = record(plan.departure);
  const inbound = nullableString(plan.inbound_flight_no || plan.arrival_flight_no || plan.inbound_no || arrival.flight_no);
  const outbound = nullableString(plan.outbound_flight_no || plan.departure_flight_no || plan.outbound_no || departure.flight_no);
  const stands = stringArray(plan.normalized_stands || plan.stands);
  const aircraftModels = stringArray(plan.aircraft_models);
  const registrations = stringArray(plan.aircraft_registrations);
  const issueTags = [...new Set([...stringArray(plan.issue_tags || plan.problem_flags), ...stringArray(plan.quality_flags)])];
  return {
    id: numberValue(plan.id || plan.flight_plan_id || candidate.flight_plan_id || arrival.leg_id || departure.leg_id, index + 1),
    flight_key: stringValue(plan.flight_key || plan.turnaround_key || plan.candidate_key, `${inbound || "?"}/${outbound || "?"}`),
    safeguard_code: nullableString(plan.safeguard_code),
    inbound_flight_no: inbound,
    outbound_flight_no: outbound,
    stand: nullableString(plan.stand || plan.stand_code || stands[0]),
    plan_start: nullableString(plan.plan_start || plan.planned_start || plan.scheduled_start || plan.arrival_time || arrival.plan_time),
    plan_end: nullableString(plan.plan_end || plan.planned_end || plan.scheduled_end || plan.departure_time || departure.plan_time),
    airline: nullableString(plan.airline || plan.airline_code),
    aircraft_type: nullableString(plan.aircraft_type || plan.aircraft_model || aircraftModels[0] || arrival.aircraft_model || departure.aircraft_model),
    aircraft_no: nullableString(plan.aircraft_no || plan.aircraft_registration || plan.registration || registrations[0] || arrival.aircraft_registration || departure.aircraft_registration),
    issue_tags: issueTags.length ? issueTags : stringArray(plan.problem_tags)
  };
}

function mapAttributedNode(row: Record<string, unknown>): AttributedNode {
  const value = { ...record(row.node), ...row };
  const disposition = record(value.disposition || value.node_disposition);
  const node = mapNode(value);
  const phase = stringValue(value.phase || value.node_phase || disposition.phase, inferPhase(node.event_type));
  return {
    ...node,
    phase: phase === "ARRIVAL" || phase === "TURNAROUND" ? phase : "DEPARTURE",
    attributed_flight_no: nullableString(value.attributed_flight_no || value.attribution_flight_no
      || disposition.attributed_flight_no || disposition.flight_no || value.disposition_flight_no || value.flight_no)
  };
}

function mapNode(row: Record<string, unknown>): NodeEvent {
  return {
    id: numberValue(row.id || row.node_id),
    source_type: sourceType(row.source_type),
    event_type: stringValue(row.event_type || row.event_name || row.node_type, "Unknown"),
    event_time: nullableString(row.event_time || row.occurred_at),
    stand: nullableString(row.stand || row.stand_code || row.normalized_stand),
    reported_flight_no: nullableString(row.reported_flight_no || row.flight_no),
    safeguard_code: nullableString(row.safeguard_code),
    is_anomaly: booleanValue(row.is_anomaly, false)
  };
}

function mapRecoveryGroup(row: Record<string, unknown>): RecoveryGroup {
  const outboundStatus = normalizeOutboundStatus(
    stringValue(row.outbox_status || row.outbound_policy || row.outbound_disposition || row.delivery_status,
      "SUPPRESSED_BY_POLICY")
  );
  return {
    id: numberValue(row.id || row.recovery_id || row.group_id),
    group_id: numberValue(row.group_id || row.id),
    temporary_code: stringValue(row.temporary_code || row.group_code || row.group_key),
    airport_code: stringValue(row.airport_code, "XIY"),
    stand: stringValue(row.stand || row.stand_code, "-"),
    observed_start: stringValue(row.observed_start || row.window_start, new Date(0).toISOString()),
    observed_end: stringValue(row.observed_end || row.window_end, new Date(0).toISOString()),
    node_count: numberValue(row.node_count),
    group_version: numberValue(row.group_version || row.current_version, 1),
    member_hash: stringValue(row.member_hash, ""),
    machine_status: stringValue(row.machine_status || row.status, "UNASSIGNED_FINAL"),
    reason_code: stringValue(row.reason_code || row.reason, "NO_RELIABLE_CANDIDATE"),
    attempt_count: numberValue(row.attempt_count),
    max_attempts: numberValue(row.max_attempts),
    recovery_deadline: nullableString(row.recovery_deadline),
    next_attempt_at: nullableString(row.next_attempt_at),
    last_attempt_at: nullableString(row.last_attempt_at),
    recovery_request_id: nullableString(row.recovery_request_id),
    request_window_start: nullableString(row.request_window_start),
    request_window_end: nullableString(row.request_window_end),
    response_flight_count: numberValue(row.response_flight_count || row.response_item_count),
    candidates: arrayValue(row.candidates).map((item) => {
      const value = record(item);
      return {
        flight_plan_id: numberValue(value.flight_plan_id),
        rank: numberValue(value.rank),
        score: numberValue(value.score)
      };
    }),
    outbound_policy: outboundStatus,
    outbox_status: outboundStatus,
    config_version: numberValue(row.config_version || row.rollout_config_version),
    strategy_version: numberValue(row.strategy_version),
    finalized_at: nullableString(row.finalized_at || row.terminal_at),
    issue_tags: stringArray(row.issue_tags),
    item_version: nullableString(row.item_version)
  };
}

function recoveryStatistics(row: Record<string, unknown>): Record<string, number> {
  return {
    ...numberRecord(row),
    RECOVERY_PENDING: numberValue(row.RECOVERY_PENDING ?? row.recovery_pending),
    UNASSIGNED_FINAL: numberValue(row.UNASSIGNED_FINAL ?? row.unassigned_final),
    MATCHED_RECOVERED: numberValue(row.MATCHED_RECOVERED ?? row.matched_recovered),
    DATA_ERROR: numberValue(row.DATA_ERROR ?? row.data_error),
    outbound_suppressed: numberValue(row.outbound_suppressed ?? row.suppressed),
    unresolved: numberValue(row.unresolved ?? row.overdue)
  };
}

function normalizeOutboundStatus(value: string): string {
  return value === "POLICY_SUPPRESSED" ? "SUPPRESSED_BY_POLICY" : value;
}

function mapNodeAnomaly(row: Record<string, unknown>): NodeAnomaly {
  const anomalyType = stringValue(row.anomaly_type || row.problem_code, "REPEATED_NODE");
  const nodeType = stringValue(row.node_type, "Unknown");
  const occurrences = arrayValue(row.occurrences).map((item) => {
    const value = record(item);
    return {
      node_id: numberValue(value.node_id || value.id),
      event_type: stringValue(value.event_type || value.node_type, "Unknown"),
      event_time: stringValue(value.event_time || value.occurred_at, new Date(0).toISOString())
    };
  });
  return {
    id: stringValue(row.id || row.anomaly_id,
      `${stringValue(row.group_id)}:${anomalyType}:${nodeType}`),
    group_id: numberValue(row.group_id),
    temporary_code: stringValue(row.temporary_code || row.group_code || row.group_key),
    stand: stringValue(row.stand || row.stand_code, "-"),
    problem_code: anomalyType === "GUIDE_ONLY" ? "GUIDE_CAR_ONLY" : "RAPID_REPEAT",
    problem_type: stringValue(row.problem_type, anomalyType === "GUIDE_ONLY" ? "只有引导车节点" : nodeType),
    reason: stringValue(row.reason, anomalyType === "GUIDE_ONLY"
      ? "保障组只有引导车节点" : `${nodeType}短时间重复出现`),
    window_start: stringValue(row.window_start || row.first_time, occurrences[0]?.event_time || new Date(0).toISOString()),
    window_end: stringValue(row.window_end || row.last_time, occurrences.at(-1)?.event_time || new Date(0).toISOString()),
    group_start: stringValue(row.group_start || row.observed_start, new Date(0).toISOString()),
    group_end: stringValue(row.group_end || row.observed_end, new Date(0).toISOString()),
    group_node_count: numberValue(row.group_node_count),
    affected_node_count: numberValue(row.affected_node_count || row.occurrence_count, occurrences.length),
    event_types: stringArray(row.event_types).length ? stringArray(row.event_types)
      : nodeType === "Unknown" ? [...new Set(occurrences.map((item) => item.event_type))] : [nodeType],
    occurrences,
    group_version: nullableNumber(row.current_version || row.group_version),
    member_hash: nullableString(row.member_hash)
  };
}

function javaPageParams(request: PageRequest, includeMachineStatus: boolean): URLSearchParams {
  const params = new URLSearchParams();
  if (includeMachineStatus && request.status && request.status !== "ALL") {
    params.set("machineStatus", request.status);
  }
  if (request.query?.trim()) params.set("query", request.query.trim());
  if (request.cursor && request.cursor !== "0") params.set("offset", request.cursor);
  if (request.snapshotVersion) params.set("snapshotVersion", request.snapshotVersion);
  params.set("limit", String(request.limit || 100));
  return params;
}

function javaNodeAnomalyParams(request: PageRequest): URLSearchParams {
  const params = new URLSearchParams();
  if (request.status && request.status !== "ALL") params.set("problemCode", request.status);
  if (request.query?.trim()) params.set("query", request.query.trim());
  if (request.stand && request.stand !== "ALL") params.set("stand", request.stand);
  request.eventNames?.forEach((value) => params.append("eventNames", value));
  if (request.minCount && request.minCount > 0) params.set("minCount", String(request.minCount));
  params.set("offset", request.cursor && request.cursor !== "0" ? request.cursor : "0");
  params.set("limit", String(Math.min(200, request.limit || 100)));
  return params;
}

function versionParams(itemVersion?: string | null, expectedGroupVersion?: number | null,
                       expectedMemberHash?: string | null): URLSearchParams | undefined {
  if (!itemVersion && !expectedGroupVersion && !expectedMemberHash) return undefined;
  const params = new URLSearchParams();
  if (itemVersion) params.set("expectedItemVersion", itemVersion);
  if (expectedGroupVersion) params.set("expectedGroupVersion", String(expectedGroupVersion));
  if (expectedMemberHash) params.set("expectedMemberHash", expectedMemberHash);
  return params;
}

function body(value: unknown): Record<string, unknown> {
  const root = record(value);
  const meta = record(root.meta || root.metadata);
  const content = record(root.data || root.result || root);
  return { ...root, ...meta, ...content };
}

function normalizeKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(normalizeKeys);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, item]) => [
    key.replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase(),
    normalizeKeys(item)
  ]));
}

function snapshotRecord(value: unknown): Record<string, unknown> {
  return record(typeof value === "string" ? parseJson(value) : value);
}

function parseJson(value: unknown): unknown {
  if (typeof value !== "string") return value;
  try { return normalizeKeys(JSON.parse(value)); }
  catch { return {}; }
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function stringValue(value: unknown, fallback = ""): string {
  return typeof value === "string" && value.length ? value : value == null ? fallback : String(value);
}

function nullableString(value: unknown): string | null {
  return value == null || value === "" ? null : String(value);
}

function numberValue(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function nullableNumber(value: unknown): number | null {
  return value == null || value === "" ? null : numberValue(value);
}

function booleanValue(value: unknown, fallback: boolean): boolean {
  if (typeof value === "boolean") return value;
  if (value === 1 || value === "1" || value === "true") return true;
  if (value === 0 || value === "0" || value === "false") return false;
  return fallback;
}

function confidenceValue(value: unknown): number {
  const parsed = numberValue(value);
  return parsed > 1 ? parsed / 100 : parsed;
}

function stringArray(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((item) => String(item));
  if (typeof value === "string" && value.trim()) {
    const parsed = parseJson(value);
    if (Array.isArray(parsed)) return parsed.map((item) => String(item));
    return value.split(",").map((item) => item.trim()).filter(Boolean);
  }
  return [];
}

function firstString(value: unknown): string | null {
  return stringArray(value)[0] || null;
}

function numberRecord(value: unknown): Record<string, number> {
  return Object.fromEntries(Object.entries(record(value)).map(([key, item]) => [key, numberValue(item)]));
}

function sourceType(value: unknown): string {
  const normalized = stringValue(value, "algorithm_node").toLowerCase();
  if (normalized === "algorithm" || normalized === "algorithmnode") return "algorithm_node";
  if (normalized === "acdm" || normalized === "acdmreference") return "acdm_reference";
  return normalized;
}

function inferPhase(eventType: string): "ARRIVAL" | "TURNAROUND" | "DEPARTURE" {
  if (["GuideCarStart", "GuideCarEnd", "AircraftStart", "AircraftEntry", "PlaceChockStart", "PlaceChockEnd", "BridgeStart", "BridgeEnd", "OpenCabinDoor", "OpenCargoDoor"].includes(eventType)) return "ARRIVAL";
  if (["AircraftLeave", "TowStart", "TowEnd", "RemoveChockStart", "RemoveChockEnd", "CloseCabinDoor", "CloseCargoDoor"].includes(eventType)) return "DEPARTURE";
  return "TURNAROUND";
}
