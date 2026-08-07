import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  ChevronRight,
  Clock3,
  GitMerge,
  RefreshCw,
  Scissors,
  Search,
  ShieldAlert
} from "lucide-react";
import { eventLabel } from "../eventLabels";
import { SOURCE_LABELS } from "../labels";
import type { ClusterReviewInput, Group, GroupDetail, NodeEvent } from "../types";

type Props = {
  groups: Group[];
  detail: GroupDetail | null;
  busy: boolean;
  onSelect: (id: number) => void;
  onReview: (groupId: number, input: ClusterReviewInput) => Promise<void>;
  onSplit: (groupId: number, nodeId: number, comment: string) => Promise<void>;
  onMerge: (groupId: number, groupIds: number[], comment: string) => Promise<void>;
  readOnly?: boolean;
  initialStatus?: string;
  initialQuery?: string;
  initialCursor?: string;
  onNavigationStateChange?: (state: { groupId: number | null; status: string; query: string; cursor: string }) => void;
  navigationContext?: { originLabel: string; helpText: string } | null;
  onReturnToOrigin?: () => void;
};

const START_EVENTS = new Set(["AircraftStart", "GuideCarStart", "AircraftEntry"]);
const STRONG_START_EVENTS = new Set(["AircraftEntry"]);
const END_EVENTS = new Set(["AircraftLeave", "TowEnd"]);
const STRUCTURAL_ISSUES = new Set(["INCOMPLETE_SEQUENCE", "ORPHAN_START_MARKER", "NODE_DATA_ERROR"]);
const DISTRIBUTION_HIT_SIZE = 32;

export function ClusterReviewWorkbench({
  groups,
  detail,
  busy,
  onSelect,
  onReview,
  onSplit,
  onMerge,
  readOnly = false,
  initialStatus = "pending",
  initialQuery = "",
  initialCursor = "100",
  onNavigationStateChange,
  navigationContext,
  onReturnToOrigin
}: Props) {
  const [filter, setFilter] = useState(initialStatus === "ALL" ? "all" : initialStatus);
  const [query, setQuery] = useState(initialQuery);
  const [splitNodeId, setSplitNodeId] = useState<number | null>(null);
  const [mergeTargetId, setMergeTargetId] = useState<number | null>(null);
  const [anomalyNodeIds, setAnomalyNodeIds] = useState<number[]>([]);
  const [selectedDistributionKey, setSelectedDistributionKey] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [queueLimit, setQueueLimit] = useState(Math.max(100, Number(initialCursor) || 100));
  const [distributionWidth, setDistributionWidth] = useState(0);
  const distributionRef = useRef<HTMLDivElement>(null);
  const distributionPopoverRef = useRef<HTMLDivElement>(null);
  const distributionTriggerRefs = useRef(new Map<string, HTMLButtonElement>());

  useEffect(() => {
    setSplitNodeId(null);
    setMergeTargetId(null);
    setAnomalyNodeIds([]);
    setSelectedDistributionKey(null);
    distributionTriggerRefs.current.clear();
    setComment("");
  }, [detail?.id]);

  useEffect(() => {
    if (!selectedDistributionKey) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        const trigger = distributionTriggerRefs.current.get(selectedDistributionKey);
        setSelectedDistributionKey(null);
        requestAnimationFrame(() => trigger?.focus());
      }
    };
    const closeOutsideTimeline = (event: PointerEvent) => {
      if (!distributionRef.current?.contains(event.target as Node)) setSelectedDistributionKey(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    document.addEventListener("pointerdown", closeOutsideTimeline);
    return () => {
      window.removeEventListener("keydown", closeOnEscape);
      document.removeEventListener("pointerdown", closeOutsideTimeline);
    };
  }, [selectedDistributionKey]);

  useEffect(() => {
    setQueueLimit(100);
    onNavigationStateChange?.({ groupId: detail?.id || null, status: filter, query, cursor: "100" });
  }, [filter, query]);

  useEffect(() => {
    const element = distributionRef.current;
    if (!element) return;
    const updateWidth = () => setDistributionWidth(Math.round(element.getBoundingClientRect().width));
    updateWidth();
    const observer = new ResizeObserver(updateWidth);
    observer.observe(element);
    return () => observer.disconnect();
  }, [detail?.id]);

  const reviewedCount = groups.filter((group) => group.cluster_review_status !== "pending").length;
  const errorCount = groups.filter((group) => !["pending", "correct"].includes(group.cluster_review_status)).length;
  const structuralCount = groups.filter(isStructurallySuspicious).length;
  const filteredGroups = useMemo(() => {
    const needle = query.trim().toUpperCase();
    return groups.filter((group) => {
      if (filter === "pending" && group.cluster_review_status !== "pending") return false;
      if (filter === "suspicious" && !isStructurallySuspicious(group)) return false;
      if (filter === "correct" && group.cluster_review_status !== "correct") return false;
      if (filter === "problem" && ["pending", "correct"].includes(group.cluster_review_status)) return false;
      return !needle || group.stand.toUpperCase().includes(needle) || group.temporary_code.toUpperCase().includes(needle);
    });
  }, [filter, groups, query]);
  const visibleGroups = filteredGroups.slice(0, queueLimit);

  const standGroups = useMemo(() => {
    if (!detail) return [];
    return groups
      .filter((group) => group.stand === detail.stand)
      .sort((left, right) => left.observed_start.localeCompare(right.observed_start));
  }, [detail, groups]);
  const standIndex = detail ? standGroups.findIndex((group) => group.id === detail.id) : -1;
  const previous = standIndex > 0 ? standGroups[standIndex - 1] : null;
  const next = standIndex >= 0 && standIndex < standGroups.length - 1 ? standGroups[standIndex + 1] : null;
  const latestReview = detail?.cluster_reviews.at(-1);
  const distributionPoints = useMemo(
    () => detail ? buildDistributionPoints(detail, anomalyNodeIds, distributionWidth) : [],
    [anomalyNodeIds, detail, distributionWidth]
  );

  useEffect(() => {
    if (selectedDistributionKey
      && !distributionPoints.some((point) => point.key === selectedDistributionKey)) {
      setSelectedDistributionKey(null);
    }
  }, [distributionPoints, selectedDistributionKey]);

  useEffect(() => {
    if (selectedDistributionKey) distributionPopoverRef.current?.focus();
  }, [selectedDistributionKey]);

  if (!detail) {
    return <div className="empty-page"><RefreshCw size={24} />正在载入聚类审核</div>;
  }

  const startBoundary = explainStart(detail, previous);
  const endBoundary = explainEnd(detail, next);
  const duration = minutesBetween(detail.observed_start, detail.observed_end);

  function toggleAnomaly(nodeId: number) {
    setAnomalyNodeIds((values) => values.includes(nodeId)
      ? values.filter((value) => value !== nodeId)
      : [...values, nodeId]);
  }

  function selectGroup(id: number) {
    onNavigationStateChange?.({ groupId: id, status: filter, query, cursor: String(queueLimit) });
    onSelect(id);
  }

  return (
    <div className={`cluster-review-page ${readOnly ? "read-only" : ""}`}>
      <div className="page-heading cluster-page-heading">
        <div>
          <h1>{readOnly ? "保障数据聚类结果" : "保障数据聚类结果审核"}</h1>
          <p>{readOnly ? "查看 Java 影子链路生成的分组边界与节点归组。" : "只审核保障组边界与节点归组，不判断航班匹配是否正确。"}</p>
        </div>
        <div className="cluster-metrics" aria-label="聚类审核进度">
          <span><b>{groups.length}</b>有效组</span>
          <span><b>{reviewedCount}</b>已审核</span>
          <span><b>{structuralCount}</b>结构可疑</span>
          <span className={errorCount ? "bad" : "ok"}><b>{errorCount}</b>人工指出问题</span>
        </div>
      </div>

      {readOnly && <div className="readonly-notice"><ShieldAlert size={17} /><span><strong>Java影子结果 / 只读</strong>这里展示生产 Java 链路的影子计算事实，不提供拆分、合并、异常标记或审核提交。</span></div>}

      <div className="cluster-review-layout">
        <aside className="surface cluster-queue">
          <div className="cluster-queue-controls">
            <label className="search-control"><Search size={15} /><input aria-label="搜索机位或分组" placeholder="机位 / 临时组" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
            <select aria-label="聚类审核筛选" value={filter} onChange={(event) => setFilter(event.target.value)}>
              <option value="pending">待审核</option>
              <option value="suspicious">结构可疑</option>
              <option value="problem">人工指出问题</option>
              <option value="correct">已确认正确</option>
              <option value="all">全部分组</option>
            </select>
          </div>
          <div className="cluster-queue-count">{filteredGroups.length} 组 · 已显示 {visibleGroups.length}</div>
          <div className="cluster-queue-list">
            {visibleGroups.map((group) => (
              <button className={group.id === detail.id ? "selected" : ""} key={group.id} onClick={() => selectGroup(group.id)}>
                <span><strong>{group.stand}</strong><small>{group.temporary_code.split("-").at(-1)}</small></span>
                <span><b>{formatTime(group.observed_start)}</b><small>{group.node_count} 节点 · {formatDuration(group)}</small></span>
                <i className={`cluster-review-dot ${group.cluster_review_status}`} title={clusterReviewLabel(group.cluster_review_status)} />
              </button>
            ))}
            {visibleGroups.length < filteredGroups.length && (
              <button className="cluster-load-more" onClick={() => setQueueLimit((value) => {
                const nextLimit = value + 100;
                onNavigationStateChange?.({ groupId: detail.id, status: filter, query, cursor: String(nextLimit) });
                return nextLimit;
              })}>
                再显示 {Math.min(100, filteredGroups.length - visibleGroups.length)} 组
              </button>
            )}
          </div>
        </aside>

        <main className="cluster-review-main">
          {navigationContext && onReturnToOrigin && <section className="recovery-review-context">
            <button className="button secondary" onClick={onReturnToOrigin}><ArrowLeft size={16} />返回{navigationContext.originLabel}</button>
            <div><strong>只读图形查看</strong><span>{navigationContext.helpText}</span></div>
          </section>}
          <section className="surface cluster-context-panel">
            <div className="section-heading">
              <div><h2>{detail.stand} 机位连续分组</h2><span>{detail.temporary_code}</span></div>
              <span>{formatFull(detail.observed_start)} - {formatFull(detail.observed_end)}</span>
            </div>
            <div className="stand-sequence">
              <GroupContextCard group={previous} label="前一组" onSelect={selectGroup} />
              <GapIndicator left={previous} right={detail} />
              <GroupContextCard group={detail} label="当前组" current onSelect={selectGroup} />
              <GapIndicator left={detail} right={next} />
              <GroupContextCard group={next} label="后一组" onSelect={selectGroup} />
            </div>
            <div ref={distributionRef} className="node-distribution" aria-label="当前组节点时间分布" onClick={() => setSelectedDistributionKey(null)}>
              {distributionPoints.map((point) => {
                const popoverId = distributionPopoverId(detail.id, point.key);
                return (
                <button
                  key={point.key}
                  ref={(element) => {
                    if (element) distributionTriggerRefs.current.set(point.key, element);
                    else distributionTriggerRefs.current.delete(point.key);
                  }}
                  className={`${point.kind} ${point.hasAnomaly ? "anomaly" : ""}`}
                  style={{ left: `${point.position}%` }}
                  aria-label={`查看${point.nodes.map((node) => eventLabel(node.event_type)).join("、")}详情`}
                  aria-expanded={selectedDistributionKey === point.key}
                  aria-controls={selectedDistributionKey === point.key ? popoverId : undefined}
                  aria-haspopup="dialog"
                  title={`${point.nodes.map((node) => eventLabel(node.event_type)).join("、")} ${formatTime(point.nodes[0].event_time)}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    setSelectedDistributionKey((current) => current === point.key ? null : point.key);
                  }}
                >
                  {point.nodes.length > 1 && <span className="node-distribution-count">{point.nodes.length}</span>}
                </button>
                );
              })}
              {distributionPoints.map((point) => selectedDistributionKey === point.key && (
                <div
                  className="node-distribution-popover"
                  key={`${point.key}-popover`}
                  id={distributionPopoverId(detail.id, point.key)}
                  ref={distributionPopoverRef}
                  style={{ left: `clamp(142px, ${point.position}%, calc(100% - 142px))` }}
                  role="dialog"
                  aria-label="节点详情"
                  tabIndex={-1}
                  onClick={(event) => event.stopPropagation()}
                >
                  <strong>{point.nodes.length > 1 ? `当前位置 ${point.nodes.length} 条节点` : "节点详情"}</strong>
                  {point.nodes.map((node) => (
                    <div className="node-distribution-popover-row" key={node.id}>
                      <span>{String(detail.nodes.findIndex((item) => item.id === node.id) + 1).padStart(2, "0")}</span>
                      <div><b>{eventLabel(node.event_type)}</b><small>{SOURCE_LABELS[node.source_type] || node.source_type}</small></div>
                      <time>{formatFullWithSeconds(node.event_time)}</time>
                    </div>
                  ))}
                </div>
              ))}
            </div>
            <div className="distribution-axis"><span>{formatTime(detail.observed_start)}</span><span>{duration} 分钟</span><span>{formatTime(detail.observed_end)}</span></div>
          </section>

          <section className="cluster-boundary-grid">
            <BoundaryCard side="start" title="开始边界" explanation={startBoundary} />
            <BoundaryCard side="end" title="结束边界" explanation={endBoundary} />
          </section>

          <section className="surface cluster-node-panel">
            <div className="section-heading">
              <div><h2>组内节点序列</h2><span>{readOnly ? "节点按 Java 影子分组结果顺序展示。" : "选择某节点可作为拆分位置；勾选节点可标记原始异常。"}</span></div>
              <span>{detail.nodes.length} 条</span>
            </div>
            <div className={`cluster-node-table ${readOnly ? "read-only" : ""}`} role="table" aria-label="组内节点序列">
              <div className="cluster-node-head" role="row">{!readOnly && <span>拆分前</span>}<span>序号</span><span>节点</span><span>来源</span><span>时间</span>{!readOnly && <span>异常</span>}</div>
              {detail.nodes.map((node, index) => (
                <div className={`cluster-node-record ${splitNodeId === node.id ? "split-selected" : ""} ${anomalyNodeIds.includes(node.id) ? "anomaly-selected" : ""}`} role="row" key={node.id}>
                  {!readOnly && <button className="icon-button" aria-label={`在${eventLabel(node.event_type)}前拆分`} title="在该节点前拆分" disabled={index === 0} onClick={() => setSplitNodeId(splitNodeId === node.id ? null : node.id)}><Scissors size={15} /></button>}
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <strong>{eventLabel(node.event_type)}</strong>
                  <span>{SOURCE_LABELS[node.source_type] || node.source_type}</span>
                  <time>{formatTime(node.event_time)}</time>
                  {!readOnly && <label title="标记原始节点异常"><input type="checkbox" checked={anomalyNodeIds.includes(node.id)} onChange={() => toggleAnomaly(node.id)} /></label>}
                </div>
              ))}
            </div>
          </section>
        </main>

        <aside className="surface cluster-decision-panel">
          <div className="section-heading"><h2>{readOnly ? "分组结论" : "聚类审核"}</h2><span>{clusterReviewLabel(detail.cluster_review_status)}</span></div>
          {latestReview && (
            <div className={`latest-cluster-review ${latestReview.verdict}`}>
              <strong>{clusterReviewLabel(latestReview.verdict)}</strong>
              <span>{latestReview.reviewer} · {formatAuditTime(latestReview.created_at)}</span>
              {latestReview.comment && <p>{latestReview.comment}</p>}
            </div>
          )}
          <div className="boundary-check-summary">
            <div><span>节点数</span><strong>{detail.nodes.length}</strong></div>
            <div><span>保障时长</span><strong>{duration} 分</strong></div>
            <div><span>开始证据</span><strong>{startBoundary.strength}</strong></div>
            <div><span>结束证据</span><strong>{endBoundary.strength}</strong></div>
          </div>

          {readOnly ? <div className="readonly-panel-copy"><ShieldAlert size={17} /><span><strong>不可编辑</strong>Java SHADOW 页面只用于核对分组结果；人工修正仍在“仿真数据”中完成。</span></div> : <>
          <label>审核说明<textarea rows={4} placeholder="记录视频、现场或节点顺序依据" value={comment} onChange={(event) => setComment(event.target.value)} /></label>

          <button className="button success cluster-action" disabled={busy} onClick={() => onReview(detail.id, { verdict: "correct", comment })}><Check size={16} />聚类正确</button>

          <div className="cluster-action-block">
            <div><Scissors size={16} /><strong>拆分当前组</strong></div>
            <p>{splitNodeId ? `将在节点 #${splitNodeId} 前拆分` : "先在节点序列中选择拆分位置"}</p>
            <button className="button danger" disabled={busy || !splitNodeId} onClick={() => splitNodeId && onSplit(detail.id, splitNodeId, comment)}>记录问题并执行拆分</button>
          </div>

          <div className="cluster-action-block">
            <div><GitMerge size={16} /><strong>合并相邻组</strong></div>
            <div className="merge-neighbor-options">
              {[previous, next].filter(Boolean).map((group) => group && (
                <label key={group.id}><input type="radio" name="merge-neighbor" checked={mergeTargetId === group.id} onChange={() => setMergeTargetId(group.id)} /><span>{group === previous ? "前一组" : "后一组"} · {formatTime(group.observed_start)} · {group.node_count} 节点</span></label>
              ))}
              {!previous && !next && <p>当前机位没有相邻组</p>}
            </div>
            <button className="button secondary" disabled={busy || !mergeTargetId} onClick={() => mergeTargetId && onMerge(detail.id, [detail.id, mergeTargetId], comment)}><GitMerge size={15} />记录问题并合并</button>
          </div>

          <div className="cluster-action-block">
            <div><ShieldAlert size={16} /><strong>异常节点</strong></div>
            <p>{anomalyNodeIds.length ? `已选择 ${anomalyNodeIds.length} 条节点` : "在下方节点序列中勾选"}</p>
            <button className="button secondary" disabled={busy || !anomalyNodeIds.length} onClick={() => onReview(detail.id, { verdict: "anomaly", anomaly_node_ids: anomalyNodeIds, comment })}><AlertTriangle size={15} />提交异常节点</button>
          </div>
          </>}
        </aside>
      </div>
    </div>
  );
}

type BoundaryExplanation = { strength: "强" | "中" | "弱"; title: string; detail: string };

function BoundaryCard({ side, title, explanation }: { side: "start" | "end"; title: string; explanation: BoundaryExplanation }) {
  return <section className={`surface boundary-card ${side}`}><div><Clock3 size={17} /><span>{title}</span><b className={`strength-${explanation.strength}`}>{explanation.strength}证据</b></div><strong>{explanation.title}</strong><p>{explanation.detail}</p></section>;
}

function GroupContextCard({ group, label, current = false, onSelect }: { group: Group | null; label: string; current?: boolean; onSelect: (id: number) => void }) {
  if (!group) return <div className="context-group empty"><span>{label}</span><strong>无</strong></div>;
  return <button className={`context-group ${current ? "current" : ""}`} onClick={() => onSelect(group.id)}><span>{label} · {group.temporary_code.split("-").at(-1)}</span><strong>{formatTime(group.observed_start)} - {formatTime(group.observed_end)}</strong><small>{group.node_count} 节点 · {formatDuration(group)}</small></button>;
}

function GapIndicator({ left, right }: { left: Group | null; right: Group | null }) {
  if (!left || !right) return <span className="context-arrow"><ChevronRight size={17} /></span>;
  const gap = minutesBetween(left.observed_end, right.observed_start);
  return <span className={`context-gap ${gap < 0 ? "overlap" : gap > 180 ? "long" : ""}`}><ChevronRight size={15} /><b>{gap < 0 ? `重叠 ${Math.abs(gap)} 分` : `${gap} 分`}</b></span>;
}

function explainStart(group: GroupDetail, previous: Group | null): BoundaryExplanation {
  const first = group.nodes[0];
  const entry = group.nodes.find((node) => STRONG_START_EVENTS.has(node.event_type));
  if (first && STRONG_START_EVENTS.has(first.event_type)) return { strength: "强", title: "飞机入位触发新组", detail: `${formatTime(first.event_time)} ${eventLabel(first.event_type)} 是航空器占位强边界。` };
  if (first && START_EVENTS.has(first.event_type) && entry) return { strength: "强", title: "入位前接近链并入当前组", detail: `${eventLabel(first.event_type)} 到 ${eventLabel(entry.event_type)} 相隔 ${minutesBetween(first.event_time, entry.event_time)} 分钟，在 30 分钟接近链内。` };
  if (previous) {
    const gap = minutesBetween(previous.observed_end, group.observed_start);
    if (gap > 180) return { strength: "中", title: "空闲间隔触发新组", detail: `与前一组间隔 ${gap} 分钟，超过当前 180 分钟空闲阈值。` };
    return { strength: "弱", title: "未发现飞机入位强边界", detail: `与前一组仅间隔 ${gap} 分钟，应重点检查是否被错误拆开。` };
  }
  return { strength: "弱", title: "机位数据首端", detail: "没有更早的同机位分组可用于验证开始边界。" };
}

function explainEnd(group: GroupDetail, next: Group | null): BoundaryExplanation {
  const last = group.nodes.at(-1);
  if (last && END_EVENTS.has(last.event_type)) return { strength: "强", title: `${eventLabel(last.event_type)}终止当前组`, detail: `${formatTime(last.event_time)} 的终止节点明确释放当前航空器保障链。` };
  if (next) {
    const gap = minutesBetween(group.observed_end, next.observed_start);
    if (gap > 180) return { strength: "中", title: "空闲间隔结束当前组", detail: `到后一组间隔 ${gap} 分钟，超过当前 180 分钟空闲阈值。` };
    return { strength: "弱", title: "未发现推出或牵引车结束", detail: `到后一组仅间隔 ${gap} 分钟，应检查两组是否需要合并。` };
  }
  return { strength: "弱", title: "机位数据尾端", detail: "没有后续同机位分组，且当前组缺少明确终止节点。" };
}

function isStructurallySuspicious(group: Group): boolean {
  return group.node_count <= 3 || group.issue_tags.some((issue) => STRUCTURAL_ISSUES.has(issue));
}

function clusterReviewLabel(value: string): string {
  return ({ pending: "待审核", correct: "聚类正确", split_required: "已确认应拆分", merge_required: "已确认应合并", anomaly: "存在异常节点" } as Record<string, string>)[value] || value;
}

function nodePosition(value: string | null, start: string, end: string): number {
  if (!value) return 0;
  const total = Math.max(1, new Date(end).getTime() - new Date(start).getTime());
  return Math.max(0, Math.min(100, ((new Date(value).getTime() - new Date(start).getTime()) / total) * 100));
}

type DistributionPoint = {
  key: string;
  nodes: NodeEvent[];
  position: number;
  kind: "start" | "end" | "normal";
  hasAnomaly: boolean;
};

function buildDistributionPoints(
  detail: GroupDetail,
  anomalyNodeIds: number[],
  distributionWidth: number
): DistributionPoint[] {
  const grouped = new Map<string, NodeEvent[]>();
  const slotCount = distributionWidth > 0
    ? Math.max(1, Math.floor(distributionWidth / DISTRIBUTION_HIT_SIZE))
    : 0;
  detail.nodes.forEach((node) => {
    const position = nodePosition(node.event_time, detail.observed_start, detail.observed_end);
    const bucket = distributionWidth > 0
      ? Math.min(slotCount - 1, Math.floor((position / 100) * slotCount))
      : null;
    const key = bucket === null
      ? node.event_time ? node.event_time.slice(0, 16) : `missing-${node.id}`
      : `position-${slotCount}-${bucket}`;
    grouped.set(key, [...(grouped.get(key) || []), node]);
  });
  return Array.from(grouped.entries()).map(([key, nodes]) => {
    const positionMatch = key.match(/^position-(\d+)-(\d+)$/);
    return {
      key,
      nodes,
      position: positionMatch
        ? ((Number(positionMatch[2]) + 0.5) / Number(positionMatch[1])) * 100
        : nodePosition(nodes[0].event_time, detail.observed_start, detail.observed_end),
      kind: nodes.some((node) => END_EVENTS.has(node.event_type))
        ? "end"
        : nodes.some((node) => START_EVENTS.has(node.event_type)) ? "start" : "normal",
      hasAnomaly: nodes.some((node) => anomalyNodeIds.includes(node.id))
    };
  });
}

function distributionPopoverId(groupId: number, key: string): string {
  return `cluster-node-details-${groupId}-${key.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
}

function minutesBetween(start: string | null, end: string | null): number {
  if (!start || !end) return 0;
  return Math.round((new Date(end).getTime() - new Date(start).getTime()) / 60000);
}

function formatDuration(group: Group): string {
  return `${minutesBetween(group.observed_start, group.observed_end)} 分`;
}

function formatTime(value: string | null): string {
  if (!value) return "--:--";
  return new Date(value).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function formatFull(value: string): string {
  return new Date(value).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
}

function formatFullWithSeconds(value: string | null): string {
  if (!value) return "时间缺失";
  return new Date(value).toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false
  });
}

function formatAuditTime(value: string): string {
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`;
  return new Date(normalized).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
}
