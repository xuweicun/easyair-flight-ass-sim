import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ArrowRight, Clock3, FileSearch, RefreshCw, ScanSearch, Send, ShieldAlert } from "lucide-react";
import { StatusBadge } from "../components/StatusBadge";
import type { FlightMatchDataSource } from "../dataSources";
import { issueLabel } from "../labels";
import type { RecoveryGroup, RecoveryGroupDetail, RecoveryQueue as RecoveryQueueData } from "../types";

const statuses = ["ALL", "RECOVERY_PENDING", "UNASSIGNED_FINAL", "MATCHED_RECOVERED", "MATCHED", "DATA_ERROR"];

export function RecoveryQueue({
  dataSource,
  initialGroupId,
  initialStatus = "ALL",
  initialQuery = "",
  initialCursor = "0",
  onNavigationStateChange,
  onOpenVisualReview
}: {
  dataSource: FlightMatchDataSource;
  initialGroupId?: number | null;
  initialStatus?: string;
  initialQuery?: string;
  initialCursor?: string;
  onNavigationStateChange: (state: { groupId: number | null; status: string; query: string; cursor: string }) => void;
  onOpenVisualReview: (detail: RecoveryGroupDetail) => void;
}) {
  const [queue, setQueue] = useState<RecoveryQueueData | null>(null);
  const [detail, setDetail] = useState<RecoveryGroupDetail | null>(null);
  const [status, setStatus] = useState(initialStatus);
  const [query, setQuery] = useState(initialQuery);
  const [cursor, setCursor] = useState(initialCursor);
  const [preview, setPreview] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const rowRefs = useRef(new Map<number, HTMLTableRowElement>());
  const queryReady = useRef(false);
  const loadRequestId = useRef(0);

  async function load(nextStatus = status, preferredGroupId: number | null = detail?.group_id || null,
                      nextCursor = cursor, nextQuery = query) {
    const requestId = ++loadRequestId.current;
    setError(null);
    setLoading(true);
    setDetail(null);
    try {
      const result = await loadRecoveryPages(dataSource, nextStatus, nextQuery, nextCursor);
      if (requestId !== loadRequestId.current) return;
      setQueue(result);
      setCursor(nextCursor);
      const targetId = preferredGroupId;
      const target = result.items.find((item) => item.group_id === targetId) || result.items[0];
      setDetail(target
        ? await dataSource.recoveryGroup(target.group_id, target.item_version)
        : targetId ? await dataSource.recoveryGroup(targetId) : null);
      const selectedId = target?.group_id || targetId || null;
      onNavigationStateChange({ groupId: selectedId, status: nextStatus, query: nextQuery, cursor: nextCursor });
    } catch (reason) {
      if (requestId === loadRequestId.current) {
        setError(reason instanceof Error ? reason.message : "恢复队列载入失败");
      }
    } finally {
      if (requestId === loadRequestId.current) setLoading(false);
    }
  }

  useEffect(() => { load(initialStatus, initialGroupId || null, initialCursor); }, [dataSource]);

  useEffect(() => {
    if (!queryReady.current) {
      queryReady.current = true;
      return;
    }
    const timer = window.setTimeout(() => {
      setCursor("0");
      load(status, null, "0", query);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    if (!detail) return;
    rowRefs.current.get(detail.group_id)?.scrollIntoView({ block: "nearest" });
  }, [detail?.group_id]);

  const items = useMemo(() => (queue?.items || []).filter((item) => {
    const text = `${item.temporary_code} ${item.stand} ${item.reason_code}`.toLowerCase();
    return text.includes(query.trim().toLowerCase());
  }), [queue, query]);

  async function selectGroup(item: RecoveryGroup) {
    setPreview(null);
    setLoading(true);
    setDetail(null);
    try {
      setDetail(await dataSource.recoveryGroup(item.group_id, item.item_version));
      onNavigationStateChange({ groupId: item.group_id, status, query, cursor });
    }
    catch (reason) { setError(reason instanceof Error ? reason.message : "详情载入失败"); }
    finally { setLoading(false); }
  }

  async function showPreview() {
    if (!detail) return;
    try {
      const result = await dataSource.recoveryPayloadPreview(detail.group_id, detail.item_version);
      setPreview(result.outbound_status === "SUPPRESSED_BY_POLICY"
        ? "西安策略已抑制：不会向总线发送临时保障组"
        : JSON.stringify(result.payload, null, 2));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "载荷预览失败"); }
  }

  async function loadMore() {
    if (!queue || loading) return;
    setLoading(true);
    try {
      const nextCursor = queue.next_cursor || String(queue.offset + queue.items.length);
      const next = await dataSource.recoveryGroups({ status, query, cursor: nextCursor, limit: 100 });
      setQueue({ ...next, items: [...queue.items, ...next.items], offset: 0, cursor: queue.cursor || cursor });
      setCursor(nextCursor);
      onNavigationStateChange({ groupId: detail?.group_id || null, status, query, cursor: nextCursor });
    } catch (reason) { setError(reason instanceof Error ? reason.message : "加载更多失败"); }
    finally { setLoading(false); }
  }

  return (
    <div className="page-stack recovery-page">
      <div className="page-heading">
        <div><h1>航班恢复队列</h1><p>机器终态、计划补拉和出站处置统一巡检，不阻塞实时链路</p></div>
        <button className="button secondary" disabled={loading} onClick={() => load(status, detail?.group_id || null, cursor)}><RefreshCw className={loading ? "spin" : ""} size={16} />刷新</button>
      </div>

      {error && <div className="recovery-alert"><ShieldAlert size={17} />{error}</div>}
      <section className="recovery-metrics" aria-label="恢复队列统计">
        <Metric label="恢复中" value={loading ? "-" : queue?.statistics.RECOVERY_PENDING || 0} icon={<Clock3 size={17} />} />
        <Metric label="最终无航班号" value={loading ? "-" : queue?.statistics.UNASSIGNED_FINAL || 0} icon={<FileSearch size={17} />} />
        <Metric label="恢复后匹配" value={loading ? "-" : queue?.statistics.MATCHED_RECOVERED || 0} icon={<RefreshCw size={17} />} />
        <Metric label="策略抑制" value={loading ? "-" : queue?.statistics.outbound_suppressed || 0} icon={<Send size={17} />} />
        <Metric label="超时悬挂" value={loading ? "-" : queue?.statistics.unresolved || 0} icon={<ShieldAlert size={17} />} danger />
      </section>

      <div className="filter-bar recovery-filter">
        <input value={query} onChange={(event) => {
          const value = event.target.value;
          setQuery(value);
          onNavigationStateChange({ groupId: detail?.group_id || null, status, query: value, cursor });
        }} placeholder="搜索临时组、机位或原因" />
        <select value={status} onChange={(event) => {
          const value = event.target.value;
          setStatus(value);
          setCursor("0");
          load(value, null, "0");
        }}>
          {statuses.map((value) => <option key={value} value={value}>{statusText(value)}</option>)}
        </select>
        <span>统计截止 {queue ? formatDate(queue.as_of) : "-"}</span>
      </div>

      <div className="recovery-layout">
        <section className="surface recovery-table-wrap">
          <table className="data-table interactive-table recovery-table">
            <thead><tr><th>临时保障组</th><th>机位/窗口</th><th>节点</th><th>机器状态</th><th>原因</th><th>补拉</th><th>出站</th><th /></tr></thead>
            <tbody>
              {items.map((item) => (
                <tr ref={(element) => { if (element) rowRefs.current.set(item.group_id, element); else rowRefs.current.delete(item.group_id); }} key={item.group_id} className={detail?.group_id === item.group_id ? "selected" : ""} onClick={() => selectGroup(item)} tabIndex={0} aria-selected={detail?.group_id === item.group_id} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectGroup(item); } }}>
                  <td><strong>{item.temporary_code}</strong><small>v{item.group_version} · {item.member_hash.slice(0, 8)}</small></td>
                  <td><b>{item.stand}</b><small>{formatWindow(item.observed_start, item.observed_end)}</small></td>
                  <td>{item.node_count}</td>
                  <td><StatusBadge status={item.machine_status} /></td>
                  <td>{reasonText(item.reason_code)}</td>
                  <td>{item.attempt_count}/{item.max_attempts}</td>
                  <td><span className={`outbox-state ${item.outbox_status.toLowerCase()}`}>{outboundText(item.outbox_status)}</span></td>
                  <td><ArrowRight size={16} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {loading && <div className="empty-state recovery-loading"><RefreshCw className="spin" size={18} />正在生成恢复队列</div>}
          {!loading && !items.length && <div className="empty-state">当前筛选条件下没有保障组</div>}
          {!loading && queue && queue.items.length < queue.total && <button className="button secondary recovery-load-more" onClick={loadMore}>加载更多（{queue.items.length}/{queue.total}）</button>}
        </section>

        <aside className="surface recovery-detail">
          {!detail ? <div className="empty-state">选择一个保障组查看恢复审计</div> : <>
            <div className="section-heading"><div><span>{detail.temporary_code}</span><h2>{detail.stand} 机位</h2></div><StatusBadge status={detail.machine_status} /></div>
            <div className="recovery-detail-grid">
              <Field label="可信窗口" value={formatWindow(detail.observed_start, detail.observed_end)} />
              <Field label="原因" value={reasonText(detail.reason_code)} />
              <Field label="请求窗口" value={detail.request_window_start ? formatWindow(detail.request_window_start, detail.request_window_end || detail.request_window_start) : "不补拉"} />
              <Field label="恢复截止" value={detail.recovery_deadline ? formatDate(detail.recovery_deadline) : "已形成终态"} />
              <Field label="响应航班" value={`${detail.response_flight_count} 条`} />
              <Field label="Outbox" value={outboundText(detail.outbox_status)} />
            </div>
            <div className="recovery-visual-entry">
              <strong>需要判断能否关联航班？</strong>
              <span>在图形时间轴中对比节点、实际占位窗口、补拉范围和候选航班计划。</span>
              <button className="button primary" onClick={() => onOpenVisualReview(detail)}><ScanSearch size={16} />进入图形核验</button>
            </div>
            <h3>节点与聚类边界</h3>
            <div className="recovery-node-list">
              {detail.nodes.map((node) => <div key={node.id}><span>{node.event_type}</span><time>{node.event_time ? formatDate(node.event_time) : "无有效时间"}</time></div>)}
            </div>
            <h3>首次评估与候选</h3>
            <pre className="recovery-audit">{JSON.stringify({ first_evaluation: detail.first_evaluation, candidates: detail.candidates, cluster_boundary: detail.cluster_boundary }, null, 2)}</pre>
            <h3>补拉请求与响应</h3>
            {detail.attempts.length ? <div className="recovery-attempts">{detail.attempts.map((attempt, index) => <div key={index}><strong>第 {String(attempt.attempt_no)} 次 · {String(attempt.status)}</strong><span>请求 {String(attempt.request_id || "-")} · 响应 {String(attempt.response_flight_count || 0)} 条</span><pre>{JSON.stringify({ sent_at: attempt.sent_at, completed_at: attempt.completed_at, last_error: attempt.last_error, responses: attempt.responses || [] }, null, 2)}</pre></div>)}</div> : <div className="empty-state compact">该状态不触发航班补拉</div>}
            <h3>状态时间线</h3>
            <div className="recovery-timeline">
              {detail.status_timeline.map((item, index) => <div key={`${item.status}-${index}`}><i /><span><strong>{statusText(item.status)}</strong><small>{formatDate(item.at)} · {reasonText(item.reason)}</small></span></div>)}
            </div>
            <button className="button secondary recovery-preview-button" onClick={showPreview}><FileSearch size={16} />查看出站载荷</button>
            {preview && <pre className="recovery-preview">{preview}</pre>}
            <details className="recovery-raw-audit"><summary>原始审计记录</summary><pre>{JSON.stringify(detail.raw_audit, null, 2)}</pre></details>
          </>}
        </aside>
      </div>
    </div>
  );
}

async function loadRecoveryPages(dataSource: FlightMatchDataSource, status: string,
                                 query: string, throughCursor: string): Promise<RecoveryQueueData> {
  const targetOffset = Math.max(0, Number.parseInt(throughCursor, 10) || 0);
  let pageCursor = "0";
  let first: RecoveryQueueData | null = null;
  let last: RecoveryQueueData | null = null;
  const byId = new Map<number, RecoveryGroup>();
  const seenCursors = new Set<string>();

  while (!seenCursors.has(pageCursor)) {
    seenCursors.add(pageCursor);
    const page = await dataSource.recoveryGroups({ status, query, cursor: pageCursor, limit: 100 });
    first ||= page;
    last = page;
    page.items.forEach((item) => byId.set(item.group_id, item));
    const currentOffset = Math.max(0, Number.parseInt(pageCursor, 10) || 0);
    if (currentOffset >= targetOffset || !page.next_cursor) break;
    pageCursor = page.next_cursor;
  }

  if (!first || !last) throw new Error("恢复队列没有返回分页结果");
  return {
    ...last,
    run_id: first.run_id,
    as_of: first.as_of,
    total: first.total,
    offset: 0,
    cursor: "0",
    statistics: first.statistics,
    items: [...byId.values()]
  };
}

function Metric({ label, value, icon, danger = false }: { label: string; value: number | string; icon: ReactNode; danger?: boolean }) {
  return <div className={danger && typeof value === "number" && value > 0 ? "danger" : ""}>{icon}<span>{label}</span><strong>{value}</strong></div>;
}

function Field({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><strong>{value}</strong></div>; }
function formatDate(value: string) { return new Date(value).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }); }
function formatWindow(start: string, end: string) { return `${formatDate(start)} - ${formatDate(end)}`; }
function statusText(value: string) { return ({ ALL: "全部机器状态", RECOVERY_PENDING: "计划恢复中", UNASSIGNED_FINAL: "最终无航班号", MATCHED_RECOVERED: "恢复后匹配", MATCHED: "已匹配", DATA_ERROR: "数据隔离" } as Record<string, string>)[value] || value; }
function reasonText(value: string) { return ({ PLAN_MISSING: "航班计划缺失", CANDIDATE_AMBIGUOUS: "候选存在歧义", INCOMPLETE_FRAGMENT: "低信息片段", RAW_NODE_UNRECOVERABLE: "原始节点不可恢复", MATCH_CONFIRMED: "匹配已确认", NO_RELIABLE_CANDIDATE: "无可靠候选" } as Record<string, string>)[value] || value; }
function outboundText(value: string) { return ({ SUPPRESSED_BY_POLICY: "策略抑制", PENDING: "待发送", NOT_CREATED: "未创建", PREVIEWED: "仅预览", SENT: "已发送", ALREADY_SENT: "此前已发送", DEAD: "发送失败" } as Record<string, string>)[value] || value; }
