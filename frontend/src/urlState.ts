import type { DataSourceKind } from "./dataSources";

export type AppView = "batch" | "problems" | "cluster-review" | "node-anomalies" | "recovery" | "associations" | "review" | "strategy" | "acceptance";

export type AppUrlState = {
  source: DataSourceKind;
  view: AppView;
  groupId: number | null;
  status: string;
  query: string;
  cursor: string;
  anomalyStand: string;
  anomalyNodes: string[];
  anomalyMin: number;
};

export type DetailNavigationContext = {
  originView: AppView;
  originLabel: string;
  helpText: string;
  requestWindowStart?: string | null;
  requestWindowEnd?: string | null;
};

export type BrowserEntryState = {
  scrollY?: number;
  detailNavigation?: DetailNavigationContext | null;
};

const views = new Set<AppView>([
  "batch", "problems", "cluster-review", "node-anomalies", "recovery", "associations", "review", "strategy", "acceptance"
]);

export const JAVA_SHADOW_VIEWS = new Set<AppView>(["cluster-review", "node-anomalies", "recovery", "review"]);

export function readUrlState(search = window.location.search): AppUrlState {
  const params = new URLSearchParams(search);
  const source = params.get("source") === "java-shadow" ? "java-shadow" : "simulator";
  const requestedView = params.get("view") as AppView | null;
  const view = requestedView && views.has(requestedView) ? requestedView : "review";
  const groupId = positiveInteger(params.get("groupId"));
  return {
    source,
    view: source === "java-shadow" && !JAVA_SHADOW_VIEWS.has(view) ? "recovery" : view,
    groupId,
    status: params.get("status") || "ALL",
    query: params.get("query") || "",
    cursor: params.get("cursor") || "0",
    anomalyStand: params.get("stand") || "ALL",
    anomalyNodes: [...new Set(params.getAll("node").map((value) => value.trim()).filter(Boolean))],
    anomalyMin: positiveInteger(params.get("min")) || 1
  };
}

export function urlForState(state: AppUrlState): string {
  const params = new URLSearchParams();
  params.set("source", state.source);
  params.set("view", state.view);
  if (state.groupId) params.set("groupId", String(state.groupId));
  params.set("status", state.status || "ALL");
  params.set("query", state.query || "");
  params.set("cursor", state.cursor || "0");
  if (state.anomalyStand && state.anomalyStand !== "ALL") params.set("stand", state.anomalyStand);
  state.anomalyNodes.forEach((value) => params.append("node", value));
  if (state.anomalyMin > 1) params.set("min", String(state.anomalyMin));
  return `${window.location.pathname}?${params.toString()}${window.location.hash}`;
}

export function browserEntryState(value: unknown = window.history.state): BrowserEntryState {
  if (!value || typeof value !== "object") return {};
  return value as BrowserEntryState;
}

function positiveInteger(value: string | null): number | null {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}
