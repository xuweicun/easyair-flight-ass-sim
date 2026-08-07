import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  Archive,
  ArrowLeftRight,
  Boxes,
  ClipboardCheck,
  Combine,
  Database,
  Eye,
  FlaskConical,
  Layers3,
  LockKeyhole,
  PanelLeftClose,
  RefreshCw,
  Route,
  ShieldCheck
} from "lucide-react";
import { api } from "./api";
import {
  createDataSource,
  JavaShadowSnapshotChangedError,
  type DataSourceContext,
  type DataSourceKind,
  type FlightMatchDataSource,
  type GroupPage
} from "./dataSources";
import { AcceptanceCenter } from "./pages/AcceptanceCenter";
import { AssociationExplorer } from "./pages/AssociationExplorer";
import { BatchCenter } from "./pages/BatchCenter";
import { ClusterReviewWorkbench } from "./pages/ClusterReviewWorkbench";
import { ProblemLibrary } from "./pages/ProblemLibrary";
import { NodeAnomalyCenter } from "./pages/NodeAnomalyCenter";
import { ReviewWorkbench } from "./pages/ReviewWorkbench";
import { RecoveryQueue } from "./pages/RecoveryQueue";
import { StrategyLab } from "./pages/StrategyLab";
import {
  browserEntryState,
  JAVA_SHADOW_VIEWS,
  readUrlState,
  urlForState,
  type AppUrlState,
  type AppView,
  type BrowserEntryState,
  type DetailNavigationContext
} from "./urlState";
import type {
  Acceptance,
  AcdmValidationSummary,
  ClusterReviewInput,
  Dashboard,
  Group,
  GroupDetail,
  RecoveryGroupDetail,
  RegressionCase,
  Strategy,
  StrategyConfig,
  Suggestion
} from "./types";

const navigation = [
  { key: "batch" as const, label: "批次中心", icon: Archive },
  { key: "problems" as const, label: "问题航班库", icon: Layers3 },
  { key: "cluster-review" as const, label: "聚类结果审核", icon: Combine },
  { key: "node-anomalies" as const, label: "节点异常", icon: AlertTriangle },
  { key: "recovery" as const, label: "航班恢复队列", icon: RefreshCw },
  { key: "associations" as const, label: "双维关联验证", icon: ArrowLeftRight },
  { key: "review" as const, label: "人机核验台", icon: Route },
  { key: "strategy" as const, label: "策略实验室", icon: FlaskConical },
  { key: "acceptance" as const, label: "验收中心", icon: ShieldCheck }
];

export default function App() {
  const [route, setRoute] = useState<AppUrlState>(() => readUrlState());
  const [detailNavigation, setDetailNavigation] = useState<DetailNavigationContext | null>(
    () => browserEntryState().detailNavigation || null
  );
  const [context, setContext] = useState<DataSourceContext | null>(null);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [groups, setGroups] = useState<Group[]>([]);
  const [detail, setDetail] = useState<GroupDetail | null>(null);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [acceptance, setAcceptance] = useState<Acceptance | null>(null);
  const [acdmValidation, setAcdmValidation] = useState<AcdmValidationSummary | null>(null);
  const [regressionFocus, setRegressionFocus] = useState<RegressionCase | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const routeRef = useRef(route);
  const groupsRef = useRef(groups);
  const selectRequestId = useRef(0);
  const pendingScrollY = useRef<number | null>(null);
  const dataSource = useMemo(() => createDataSource(route.source), [route.source]);

  useEffect(() => { routeRef.current = route; }, [route]);
  useEffect(() => { groupsRef.current = groups; }, [groups]);

  const commitRoute = useCallback((next: AppUrlState, mode: "replace" | "push" = "replace", state?: BrowserEntryState) => {
    routeRef.current = next;
    if (mode === "push") window.history.pushState(state || {}, "", urlForState(next));
    else window.history.replaceState(state || browserEntryState(), "", urlForState(next));
    setRoute(next);
  }, []);

  const patchRoute = useCallback((patch: Partial<AppUrlState>) => {
    const next = { ...routeRef.current, ...patch };
    commitRoute(next, "replace");
  }, [commitRoute]);

  useEffect(() => {
    window.history.replaceState(browserEntryState(), "", urlForState(routeRef.current));
    const onPopState = (event: PopStateEvent) => {
      const next = readUrlState();
      routeRef.current = next;
      setRoute(next);
      const entry = browserEntryState(event.state);
      setDetailNavigation(entry.detailNavigation || null);
      pendingScrollY.current = entry.scrollY ?? 0;
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    if (pendingScrollY.current === null) return;
    const target = pendingScrollY.current;
    pendingScrollY.current = null;
    const restore = () => window.scrollTo({ top: target, behavior: "auto" });
    requestAnimationFrame(() => requestAnimationFrame(restore));
  }, [route.view, context, groups.length]);

  const selectGroup = useCallback(async (groupId: number, updateUrl = true,
                                          expectedItemVersion?: string | null,
                                          expectedGroupVersion?: number | null,
                                          expectedMemberHash?: string | null) => {
    const requestId = ++selectRequestId.current;
    if (updateUrl) patchRoute({ groupId });
    setDetail(null);
    const row = groupsRef.current.find((group) => group.id === groupId);
    const itemVersion = expectedItemVersion
      || (typeof row?.lineage.item_version === "string" ? row.lineage.item_version : null);
    const selected = await dataSource.group(groupId, itemVersion,
      expectedGroupVersion, expectedMemberHash);
    if (requestId === selectRequestId.current) setDetail(selected);
  }, [dataSource, patchRoute]);

  const loadAll = useCallback(async (preferredCode?: string, preferredId?: number | null) => {
    const nextContext = await dataSource.context();
    const nextGroupPage = await loadEveryGroup(dataSource);
    setContext(nextContext);
    setGroups(nextGroupPage.items);
    groupsRef.current = nextGroupPage.items;

    if (nextContext.simulator_dashboard) {
      const nextDashboard = nextContext.simulator_dashboard;
      const [nextStrategies, nextSuggestions, nextAcceptance, nextAcdmValidation] = await Promise.all([
        api.strategies(),
        api.suggestions(nextDashboard.active_run.id),
        api.acceptance(nextDashboard.active_run.id),
        api.acdmValidation(nextDashboard.active_run.id)
      ]);
      setDashboard(nextDashboard);
      setStrategies(nextStrategies);
      setSuggestions(nextSuggestions);
      setAcceptance(nextAcceptance);
      setAcdmValidation(nextAcdmValidation);
    } else {
      setDashboard(null);
      setStrategies([]);
      setSuggestions([]);
      setAcceptance(null);
      setAcdmValidation(null);
    }

    const requestedId = preferredId || routeRef.current.groupId;
    const preferred = nextGroupPage.items.find((group) => group.id === requestedId)
      || nextGroupPage.items.find((group) => group.temporary_code === preferredCode)
      || nextGroupPage.items.find((group) => group.issue_tags.length > 0)
      || nextGroupPage.items[0];
    if (preferred) {
      patchRoute({ groupId: preferred.id });
      const itemVersion = typeof preferred.lineage.item_version === "string" ? preferred.lineage.item_version : null;
      setDetail(await dataSource.group(preferred.id, itemVersion));
    } else {
      patchRoute({ groupId: null });
      setDetail(null);
    }
  }, [dataSource, patchRoute]);

  useEffect(() => {
    setContext(null);
    setDashboard(null);
    setGroups([]);
    setDetail(null);
    setError(null);
    loadAll(undefined, routeRef.current.groupId).catch((reason: unknown) => setError(errorText(reason)));
  }, [dataSource, loadAll]);

  useEffect(() => {
    const groupId = route.groupId;
    if (!context || !groupId || detail?.id === groupId) return;
    selectGroup(groupId, false).catch((reason) => setError(errorText(reason)));
  }, [context, detail?.id, route.groupId, selectGroup]);

  function notify(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(null), 2800);
  }

  async function perform(action: () => Promise<void>, success: string) {
    if (dataSource.readOnly) {
      setError("Java影子结果为只读数据源，请切换到仿真数据后再执行修改操作");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await action();
      notify(success);
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  function switchSource(source: DataSourceKind) {
    if (source === routeRef.current.source) return;
    const current = routeRef.current;
    const nextView = source === "java-shadow" && !JAVA_SHADOW_VIEWS.has(current.view) ? "recovery" : current.view;
    const next: AppUrlState = {
      source,
      view: nextView,
      groupId: null,
      status: defaultStatus(nextView),
      query: "",
      cursor: defaultCursor(nextView),
      anomalyStand: "ALL",
      anomalyNodes: [],
      anomalyMin: 1
    };
    setDetailNavigation(null);
    commitRoute(next, "push");
  }

  function navigateView(view: AppView) {
    setRegressionFocus(null);
    setDetailNavigation(null);
    commitRoute({
      ...routeRef.current,
      view,
      status: defaultStatus(view),
      query: "",
      cursor: defaultCursor(view),
      anomalyStand: "ALL",
      anomalyNodes: [],
      anomalyMin: 1
    }, "push");
  }

  function openGroupFromList(groupId: number, view: "review" | "cluster-review",
                             navigationContext: DetailNavigationContext,
                             expectedItemVersion?: string | null,
                             expectedGroupVersion?: number | null,
                             expectedMemberHash?: string | null) {
    const current = routeRef.current;
    window.history.replaceState({ ...browserEntryState(), scrollY: window.scrollY }, "", urlForState(current));
    const next = { ...current, view, groupId };
    setDetailNavigation(navigationContext);
    commitRoute(next, "push", { detailNavigation: navigationContext });
    selectGroup(groupId, false, expectedItemVersion, expectedGroupVersion, expectedMemberHash)
      .catch((reason) => setError(errorText(reason)));
  }

  function returnToOrigin() {
    if (detailNavigation) window.history.back();
  }

  async function handleReview(groupId: number, input: { verdict: string; error_type?: string; correct_flight_id?: number; correct_flight_no?: string; comment?: string }) {
    await perform(async () => {
      await api.review(groupId, input);
      await loadAll(detail?.temporary_code, groupId);
    }, input.verdict === "correct" ? "已确认匹配结果" : "核验反馈已进入回归集");
  }

  async function handleClusterReview(groupId: number, input: ClusterReviewInput) {
    await perform(async () => {
      await api.clusterReview(groupId, input);
      await loadAll(detail?.temporary_code, groupId);
    }, input.verdict === "correct" ? "已确认当前聚类正确" : "聚类问题已记录");
  }

  async function handleClusterSplit(groupId: number, nodeId: number, comment: string) {
    await perform(async () => {
      await api.clusterReview(groupId, { verdict: "split_required", split_node_id: nodeId, comment });
      const created = await api.split(groupId, nodeId);
      await loadAll(created[0]?.temporary_code, created[0]?.id);
    }, "聚类问题已记录，分组已拆分并保留血缘");
  }

  async function handleClusterMerge(groupId: number, groupIds: number[], comment: string) {
    await perform(async () => {
      await api.clusterReview(groupId, { verdict: "merge_required", merge_group_ids: groupIds, comment });
      const merged = await api.merge(groupIds);
      await loadAll(merged.temporary_code, merged.id);
    }, "聚类问题已记录，相邻分组已合并");
  }

  async function handleAppearance(group: GroupDetail, airline: string, aircraftType: string, confidence: number, aircraftRegistration: string, registrationConfidence: number) {
    if (!dashboard) return;
    await perform(async () => {
      await api.appearance({
        batch_id: dashboard.batch.id,
        temporary_code: group.temporary_code,
        airline,
        aircraft_type: aircraftType,
        aircraft_registration: aircraftRegistration.trim().toUpperCase() || null,
        registration_confidence: aircraftRegistration.trim() ? registrationConfidence : null,
        confidence,
        evidence_time: group.observed_start
      });
      await api.run(dashboard.batch.id, dashboard.strategy.id);
      await loadAll(group.temporary_code, group.id);
    }, "外观特征已写入并完成策略重跑");
  }

  async function handleAcdm(group: GroupDetail, flightNo: string, entryTime: string, chockTime: string, releaseTime: string) {
    if (!dashboard) return;
    await perform(async () => {
      await api.simulateAcdm({
        batch_id: dashboard.batch.id,
        temporary_code: group.temporary_code,
        flight_no: flightNo,
        aircraft_entry_time: entryTime,
        chock_on_time: chockTime || null,
        stand_release_time: releaseTime || null
      });
      await api.run(dashboard.batch.id, dashboard.strategy.id);
      await loadAll(group.temporary_code, group.id);
    }, "A-CDM现场填报已模拟并完成策略重跑");
  }

  async function handleClearAcdm(group: GroupDetail) {
    if (!dashboard) return;
    await perform(async () => {
      await api.clearAcdm(dashboard.batch.id, group.temporary_code);
      await api.run(dashboard.batch.id, dashboard.strategy.id);
      await loadAll(group.temporary_code, group.id);
    }, "A-CDM仿真证据已清除并完成策略重跑");
  }

  async function handleSampleAcdm(limit: number) {
    if (!dashboard) return;
    await perform(async () => {
      const result = await api.sampleAcdmValidation(dashboard.active_run.id, limit);
      await loadAll(result.selected_codes[0] || detail?.temporary_code, detail?.id);
    }, "闭环歧义样本已持久保存");
  }

  async function handleRunDraft(name: string, config: StrategyConfig) {
    if (!dashboard) return;
    await perform(async () => {
      const strategy = await api.createStrategy(name, dashboard.strategy.id, config);
      await api.run(dashboard.batch.id, strategy.id);
      await loadAll(detail?.temporary_code, detail?.id);
    }, "候选策略已完成全量重跑");
  }

  if (error && !context) {
    return (
      <div className="boot-state error">
        <Boxes size={30} />
        <h1>无法载入{dataSource.label}</h1>
        <p>{error}</p>
        <DataSourceSwitcher source={route.source} onChange={switchSource} />
        <button className="button primary" onClick={() => loadAll(undefined, route.groupId).catch((reason) => setError(errorText(reason)))}><RefreshCw size={17} />重新连接</button>
      </div>
    );
  }
  if (!context || (route.source === "simulator" && (!dashboard || !acceptance))) {
    return <div className="boot-state"><RefreshCw className="spin" size={28} /><span>正在载入{dataSource.label}</span></div>;
  }

  const visibleNavigation = dataSource.readOnly
    ? navigation.filter((item) => JAVA_SHADOW_VIEWS.has(item.key))
    : navigation;
  const recoveryContext = detailNavigation?.originView === "recovery" && detail
    ? {
      groupId: detail.id,
      requestWindowStart: detailNavigation.requestWindowStart || null,
      requestWindowEnd: detailNavigation.requestWindowEnd || null
    }
    : null;
  const content = renderContent();

  function renderContent(): ReactNode {
    if (route.view === "cluster-review") return (
      <ClusterReviewWorkbench
        key={`${route.source}-cluster-review`}
        groups={groups}
        detail={detail}
        busy={busy}
        readOnly={dataSource.readOnly}
        initialStatus={route.status}
        initialQuery={route.query}
        initialCursor={route.cursor}
        onNavigationStateChange={(state) => patchRoute(state)}
        onSelect={(id) => selectGroup(id).catch((reason) => setError(errorText(reason)))}
        onReview={handleClusterReview}
        onSplit={handleClusterSplit}
        onMerge={handleClusterMerge}
        navigationContext={detailNavigation}
        onReturnToOrigin={detailNavigation ? returnToOrigin : undefined}
      />
    );
    if (route.view === "node-anomalies") return (
      <NodeAnomalyCenter
        key={`${route.source}-node-anomalies`}
        dataSource={dataSource}
        initialGroupId={route.groupId}
        initialStatus={route.status}
        initialQuery={route.query}
        initialCursor={route.cursor}
        initialStand={route.anomalyStand}
        initialNodeFilters={route.anomalyNodes}
        initialMinimumQuantity={route.anomalyMin}
        onNavigationStateChange={(state) => patchRoute(state)}
        onOpenGroup={(item) => openGroupFromList(item.group_id, "cluster-review", {
          originView: "node-anomalies",
          originLabel: "节点异常",
          helpText: "返回后将恢复节点异常筛选、选中记录和列表位置。"
        }, null, item.group_version, item.member_hash)}
      />
    );
    if (route.view === "recovery") return (
      <RecoveryQueue
        key={`${route.source}-recovery`}
        dataSource={dataSource}
        initialGroupId={route.groupId}
        initialStatus={route.status}
        initialQuery={route.query}
        initialCursor={route.cursor}
        onNavigationStateChange={(state) => patchRoute(state)}
        onOpenVisualReview={(recoveryDetail: RecoveryGroupDetail) => openGroupFromList(recoveryDetail.group_id, "review", {
          originView: "recovery",
          originLabel: "航班恢复队列",
          helpText: "淡蓝区域是计划补拉请求范围，深绿色条是算法节点形成的实际保障窗口。返回后恢复筛选、选中行和位置。",
          requestWindowStart: recoveryDetail.request_window_start,
          requestWindowEnd: recoveryDetail.request_window_end
        }, recoveryDetail.item_version, recoveryDetail.group_version, recoveryDetail.member_hash)}
      />
    );
    if (route.view === "review") return (
      <ReviewWorkbench
        groups={groups}
        detail={detail}
        regressionFocus={regressionFocus?.current_group_id === detail?.id ? regressionFocus : null}
        busy={busy}
        readOnly={dataSource.readOnly}
        onSelect={(id) => { setRegressionFocus(null); selectGroup(id).catch((reason) => setError(errorText(reason))); }}
        onReview={handleReview}
        onAppearance={handleAppearance}
        onAcdm={handleAcdm}
        onClearAcdm={handleClearAcdm}
        onSampleAcdm={handleSampleAcdm}
        acdmValidation={acdmValidation}
        onSplit={async (groupId, nodeId) => perform(async () => {
          const created = await api.split(groupId, nodeId);
          await loadAll(created[0]?.temporary_code, created[0]?.id);
        }, "分组已拆分并保留血缘")}
        onMerge={async (ids) => perform(async () => {
          const merged = await api.merge(ids);
          await loadAll(merged.temporary_code, merged.id);
        }, "相邻分组已合并")}
        recoveryContext={recoveryContext}
        navigationContext={detailNavigation}
        onReturnToOrigin={detailNavigation ? returnToOrigin : undefined}
      />
    );
    if (!dashboard || !acceptance) return <div className="empty-page"><LockKeyhole size={24} />该功能仅在仿真数据源中提供</div>;
    if (route.view === "batch") return <BatchCenter dashboard={dashboard} busy={busy} onImport={async (form) => perform(async () => { await api.importBatch(form); await loadAll(); }, "新批次已导入并完成基线运行")} />;
    if (route.view === "problems") return <ProblemLibrary groups={groups} onSelect={(id) => { navigateView("review"); selectGroup(id).catch((reason) => setError(errorText(reason))); }} />;
    if (route.view === "associations") return <AssociationExplorer runId={dashboard.active_run.id} onOpenGroup={(id) => { navigateView("review"); selectGroup(id).catch((reason) => setError(errorText(reason))); }} />;
    if (route.view === "strategy") return <StrategyLab dashboard={dashboard} strategies={strategies} suggestions={suggestions} busy={busy} onRunDraft={handleRunDraft} />;
    if (route.view === "acceptance") return <AcceptanceCenter dashboard={dashboard} acceptance={acceptance} acdmValidation={acdmValidation} busy={busy} onOpenGroup={(id, regressionCase) => { setRegressionFocus(regressionCase || null); navigateView("review"); selectGroup(id).catch((reason) => setError(errorText(reason))); }} onRerun={async () => perform(async () => { await api.run(dashboard.batch.id, dashboard.strategy.id); await loadAll(detail?.temporary_code, detail?.id); }, "当前策略已完成全量重跑")} onPublish={async () => perform(async () => { await api.publish(dashboard.strategy.id, dashboard.active_run.id); await loadAll(detail?.temporary_code, detail?.id); }, "策略版本已发布")} />;
    return null;
  }

  const outboundViolation = context.authoritative
    || context.temporary_group_outbound.enabled
    || !context.temporary_group_outbound.locked
    || context.temporary_group_outbound.destination_supported;

  return (
    <div className={`app-shell ${sidebarOpen ? "" : "sidebar-collapsed"}`}>
      <aside className="app-sidebar">
        <div className="brand-block">
          <div className="brand-mark"><Boxes size={22} /></div>
          <div><strong>航班节点仿真</strong><span>XIY MATCH LAB</span></div>
          <button className="icon-button sidebar-toggle" aria-label="收起侧栏" onClick={() => setSidebarOpen((value) => !value)}><PanelLeftClose size={17} /></button>
        </div>
        <nav>
          {visibleNavigation.map((item) => {
            const Icon = item.icon;
            return <button className={route.view === item.key ? "active" : ""} key={item.key} onClick={() => navigateView(item.key)}><Icon size={18} /><span>{item.label}</span>{item.key === "problems" && <b>{groups.filter((group) => group.issue_tags.length).length}</b>}</button>;
          })}
        </nav>
        <div className="sidebar-foot">
          <div className={`environment-state ${dataSource.readOnly ? "shadow" : ""}`}><i /><span>{dataSource.readOnly ? "Java影子结果 · 只读" : "本地仿真环境"}</span></div>
          <small>策略 {context.strategy_name}</small>
          {dataSource.readOnly && <small><LockKeyhole size={11} />临时组发送：关闭（锁定）</small>}
        </div>
      </aside>
      <div className="app-main">
        <header className="app-header">
          <div className="header-context"><ClipboardCheck size={18} /><span>{context.airport_name}</span><b>{dataSource.readOnly ? "Java SHADOW" : `运行 #${dashboard?.active_run.id || "-"}`}</b></div>
          <DataSourceSwitcher source={route.source} onChange={switchSource} />
          <div className="header-facts">
            {context.total_nodes !== null && <><span className="header-stat">节点守恒</span><strong className={context.total_nodes === context.accounted_nodes ? "ok" : "bad"}>{context.accounted_nodes ?? "-"}/{context.total_nodes}</strong></>}
            <span className="operator-avatar">{dataSource.readOnly ? "影" : "核"}</span>
          </div>
        </header>
        {dataSource.readOnly && <section className={`java-context-bar ${outboundViolation ? "danger" : ""}`}>
          <div><Eye size={17} /><span><strong>Java影子结果 / 只读</strong>截止 {formatDateTime(context.as_of)} · {context.authoritative ? "接口异常：结果被标记为权威" : "非生产权威结果"} · 发布 {context.release_key || "未绑定"}</span></div>
          <div><LockKeyhole size={16} /><span>西安临时组发送 <strong>{context.temporary_group_outbound.enabled ? "异常开启" : "关闭"}</strong> · {context.temporary_group_outbound.locked ? "配置锁定" : "未锁定"} · 目的端{context.temporary_group_outbound.destination_supported ? "标记支持" : "不支持"} · {context.temporary_group_outbound.disposition}</span></div>
        </section>}
        <div className="app-content">{content}</div>
      </div>
      {busy && <div className="busy-line" />}
      {error && <div className="toast error-toast"><button aria-label="关闭错误" onClick={() => setError(null)}>×</button>{error}</div>}
      {toast && <div className="toast success-toast"><ClipboardCheck size={17} />{toast}</div>}
    </div>
  );
}

async function loadEveryGroup(dataSource: FlightMatchDataSource): Promise<GroupPage> {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const items: Group[] = [];
    let cursor: string | undefined = "0";
    let first: GroupPage | null = null;
    let snapshotVersion: string | undefined;
    try {
      do {
        const page = await dataSource.groups({ limit: 200, cursor, snapshotVersion });
        if (!first) {
          first = page;
          snapshotVersion = page.snapshot_version || undefined;
        }
        items.push(...page.items);
        cursor = page.next_cursor || undefined;
        if (items.length >= page.total) cursor = undefined;
      } while (cursor);
      const base = first || {
        as_of: new Date().toISOString(), total: 0, cursor: "0", next_cursor: null,
        snapshot_version: null, items: []
      };
      return { ...base, total: Math.max(base.total, items.length), next_cursor: null, items };
    } catch (error) {
      if (!(error instanceof JavaShadowSnapshotChangedError) || attempt === 2) throw error;
    }
  }
  throw new Error("Java影子结果连续变化，稍后重试");
}

function DataSourceSwitcher({ source, onChange }: { source: DataSourceKind; onChange: (source: DataSourceKind) => void }) {
  return <div className="data-source-switcher" aria-label="数据源切换">
    <button className={source === "simulator" ? "active" : ""} aria-pressed={source === "simulator"} onClick={() => onChange("simulator")}><FlaskConical size={15} /><span>仿真数据</span></button>
    <button className={source === "java-shadow" ? "active" : ""} aria-pressed={source === "java-shadow"} onClick={() => onChange("java-shadow")}><Database size={15} /><span>Java影子结果</span><small>只读</small></button>
  </div>;
}

function defaultStatus(view: AppView): string {
  return view === "cluster-review" ? "pending" : "ALL";
}

function defaultCursor(view: AppView): string {
  return view === "cluster-review" || view === "node-anomalies" ? "100" : "0";
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "操作失败";
}
