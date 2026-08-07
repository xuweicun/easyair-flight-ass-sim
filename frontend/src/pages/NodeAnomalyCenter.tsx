import { useEffect, useMemo, useState, type ReactNode } from "react";
import { AlertTriangle, ArrowRight, CarFront, Download, MapPin, Repeat2, Search } from "lucide-react";
import type { FlightMatchDataSource } from "../dataSources";
import { eventLabel } from "../eventLabels";
import type { NodeAnomaly, NodeAnomalyReport } from "../types";

export function NodeAnomalyCenter({
  dataSource,
  initialGroupId,
  initialStatus = "ALL",
  initialQuery = "",
  initialCursor = "100",
  initialStand = "ALL",
  initialNodeFilters = [],
  initialMinimumQuantity = 1,
  onNavigationStateChange,
  onOpenGroup
}: {
  dataSource: FlightMatchDataSource;
  initialGroupId?: number | null;
  initialStatus?: string;
  initialQuery?: string;
  initialCursor?: string;
  initialStand?: string;
  initialNodeFilters?: string[];
  initialMinimumQuantity?: number;
  onNavigationStateChange: (state: {
    groupId: number | null;
    status: string;
    query: string;
    cursor: string;
    anomalyStand: string;
    anomalyNodes: string[];
    anomalyMin: number;
  }) => void;
  onOpenGroup: (item: NodeAnomaly) => void;
}) {
  const [report, setReport] = useState<NodeAnomalyReport | null>(null);
  const [selected, setSelected] = useState<NodeAnomaly | null>(null);
  const [problemCode, setProblemCode] = useState(initialStatus);
  const [standFilter, setStandFilter] = useState(initialStand);
  const [nodeFilters, setNodeFilters] = useState<string[]>(initialNodeFilters);
  const [minimumQuantity, setMinimumQuantity] = useState(Math.max(1, initialMinimumQuantity));
  const [standQuery, setStandQuery] = useState(initialQuery);
  const [visibleCount, setVisibleCount] = useState(Math.max(100, Number(initialCursor) || 100));
  const [error, setError] = useState<string | null>(null);
  const [optionCatalog, setOptionCatalog] = useState<NonNullable<NodeAnomalyReport["statistics"]["by_stand_and_node"]>>([]);

  useEffect(() => {
    let active = true;
    dataSource.nodeAnomalies({
      status: "ALL",
      query: "",
      cursor: "0",
      limit: 1,
      stand: "ALL",
      eventNames: [],
      minCount: 1
    }).then((result) => {
      if (active) setOptionCatalog(result.statistics.by_stand_and_node || []);
    }).catch(() => {
      if (active) setOptionCatalog([]);
    });
    return () => { active = false; };
  }, [dataSource]);

  useEffect(() => {
    let active = true;
    setError(null);
    dataSource.nodeAnomalies({
      status: problemCode,
      query: standQuery,
      cursor: "0",
      limit: Math.max(100, visibleCount),
      stand: standFilter,
      eventNames: nodeFilters,
      minCount: minimumQuantity
    })
      .then((result) => {
        if (!active) return;
        setReport(result);
        setSelected((current) => result.items.find((item) => item.id === current?.id)
          || result.items.find((item) => item.group_id === initialGroupId) || result.items[0] || null);
      })
      .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : "节点异常载入失败"); });
    return () => { active = false; };
  }, [dataSource, minimumQuantity, nodeFilters, problemCode, standFilter, standQuery, visibleCount]);

  const standOptions = useMemo(() => [...new Set((optionCatalog.length
    ? optionCatalog.map((item) => item.stand)
    : report?.statistics.by_stand_and_node?.length
      ? report.statistics.by_stand_and_node.map((item) => item.stand)
    : (report?.items || []).map((item) => item.stand)))]
    .sort((left, right) => left.localeCompare(right, "zh-CN", { numeric: true })), [optionCatalog, report]);
  const nodeOptions = useMemo(() => [...new Set([
    ...nodeFilters,
    ...(optionCatalog.length
      ? optionCatalog.map((item) => item.node_type)
      : report?.statistics.by_stand_and_node?.length
        ? report.statistics.by_stand_and_node.map((item) => item.node_type)
        : (report?.items || []).flatMap((item) => item.event_types))
  ])].sort((left, right) => eventLabel(left).localeCompare(eventLabel(right), "zh-CN")),
  [nodeFilters, optionCatalog, report]);

  const baseFilteredItems = useMemo(() => (report?.items || []).filter((item) => {
    const matchesType = problemCode === "ALL" || item.problem_code === problemCode;
    const matchesStand = standFilter === "ALL" || item.stand === standFilter;
    const matchesNode = !nodeFilters.length || item.event_types.some((eventType) => nodeFilters.includes(eventType));
    const query = standQuery.trim().toUpperCase();
    return matchesType && matchesStand && matchesNode && (!query || item.stand.toUpperCase().includes(query) || item.temporary_code.toUpperCase().includes(query));
  }), [nodeFilters, problemCode, report, standFilter, standQuery]);

  const baseStandNodeStatistics = useMemo(() => {
    if (report?.statistics.by_stand_and_node?.length) {
      const byStand = new Map<string, Array<[string, number]>>();
      report.statistics.by_stand_and_node.forEach((item) => {
        const counts = byStand.get(item.stand) || [];
        counts.push([item.node_type, item.occurrence_count]);
        byStand.set(item.stand, counts);
      });
      return [...byStand.entries()].map(([stand, counts]) => ({
        stand,
        counts: counts.sort((left, right) => right[1] - left[1]),
        total: counts.reduce((sum, [, count]) => sum + count, 0)
      })).sort((left, right) => right.total - left.total
        || left.stand.localeCompare(right.stand, "zh-CN", { numeric: true }));
    }
    const byStand = new Map<string, Map<string, number>>();
    baseFilteredItems.forEach((item) => {
      const nodeCounts = byStand.get(item.stand) || new Map<string, number>();
      if (item.problem_code === "GUIDE_CAR_ONLY") {
        nodeCounts.set("GUIDE_ONLY", (nodeCounts.get("GUIDE_ONLY") || 0) + item.affected_node_count);
      } else if (item.occurrences.length) {
        item.occurrences.forEach((occurrence) => {
          if (nodeFilters.length && !nodeFilters.includes(occurrence.event_type)) return;
          nodeCounts.set(occurrence.event_type, (nodeCounts.get(occurrence.event_type) || 0) + 1);
        });
      } else {
        item.event_types.forEach((eventType) => {
          if (nodeFilters.length && !nodeFilters.includes(eventType)) return;
          nodeCounts.set(eventType, (nodeCounts.get(eventType) || 0) + item.affected_node_count);
        });
      }
      byStand.set(item.stand, nodeCounts);
    });
    return [...byStand.entries()].map(([stand, counts]) => ({
      stand,
      counts: [...counts.entries()].sort((left, right) => right[1] - left[1]),
      total: [...counts.values()].reduce((sum, count) => sum + count, 0)
    })).sort((left, right) => right.total - left.total || left.stand.localeCompare(right.stand, "zh-CN", { numeric: true }));
  }, [baseFilteredItems, nodeFilters, report]);

  const quantityMaximum = Math.max(minimumQuantity, 1,
    ...baseStandNodeStatistics.flatMap((row) => row.counts.map(([, count]) => count)));
  const standNodeStatistics = baseStandNodeStatistics.map((row) => {
    const counts = row.counts.filter(([, count]) => count >= minimumQuantity);
    return { ...row, counts, total: counts.reduce((sum, [, count]) => sum + count, 0) };
  }).filter((row) => row.counts.length > 0);
  const eligibleStandNodes = useMemo(() => new Map(standNodeStatistics.map((row) => [
    row.stand,
    new Set(row.counts.map(([eventType]) => eventType))
  ])), [standNodeStatistics]);
  const filteredItems = baseFilteredItems.filter((item) => item.event_types.some(
    (eventType) => eligibleStandNodes.get(item.stand)?.has(eventType)
  ));
  const items = filteredItems.slice(0, visibleCount);

  useEffect(() => {
    setVisibleCount(100);
    onNavigationStateChange(navigationState(selected?.group_id || null, "100"));
  }, [minimumQuantity, nodeFilters, problemCode, standFilter, standQuery]);

  useEffect(() => {
    if (selected && items.some((item) => item.id === selected.id)) return;
    const next = items.find((item) => item.group_id === initialGroupId) || items[0] || null;
    setSelected(next);
    onNavigationStateChange(navigationState(next?.group_id || null, String(visibleCount)));
  }, [items, selected]);

  function navigationState(groupId: number | null, cursor: string) {
    return {
      groupId,
      status: problemCode,
      query: standQuery,
      cursor,
      anomalyStand: standFilter,
      anomalyNodes: nodeFilters,
      anomalyMin: minimumQuantity
    };
  }

  const maxTypeCount = Math.max(1, ...Object.values(report?.statistics.by_type || {}));
  const standReportQuery = useMemo(() => {
    const params = new URLSearchParams();
    nodeFilters.forEach((eventType) => params.append("node_type", eventType));
    params.set("minimum_quantity", String(minimumQuantity));
    if (problemCode !== "ALL") params.set("problem_code", problemCode);
    if (standFilter !== "ALL") params.set("stand", standFilter);
    if (standQuery.trim()) params.set("query", standQuery.trim());
    return params.toString();
  }, [minimumQuantity, nodeFilters, problemCode, standFilter, standQuery]);
  const exportUrls = dataSource.nodeAnomalyExportUrls?.(standReportQuery);

  function toggleNodeFilter(eventType: string) {
    setNodeFilters((current) => current.includes(eventType)
      ? current.filter((value) => value !== eventType)
      : [...current, eventType]);
  }

  return (
    <div className="page-stack node-anomaly-page">
      <div className="page-heading">
        <div><h1>节点异常</h1><p>按机位汇总算法节点的重复上报与低信息保障链</p></div>
        {exportUrls && <div className="node-anomaly-export">
          {exportUrls.reportJson && <a className="button secondary" href={exportUrls.reportJson} target="_blank" rel="noreferrer"><Download size={16} />JSON报告</a>}
          <a className="button primary" href={exportUrls.reportExcel}><Download size={16} />导出机位问题报告</a>
        </div>}
      </div>

      {error && <div className="recovery-alert"><AlertTriangle size={17} />{error}</div>}
      {!report && !error ? <div className="surface empty-state">正在扫描节点异常</div> : report && <>
        <section className="node-anomaly-metrics" aria-label="节点异常统计">
          <Metric icon={<AlertTriangle size={18} />} label="异常记录" value={report.statistics.total} />
          <Metric icon={<MapPin size={18} />} label="涉及机位" value={report.statistics.affected_stands} />
          <Metric icon={<Repeat2 size={18} />} label="短时重复" value={report.statistics.rapid_repeat} />
          <Metric icon={<CarFront size={18} />} label="仅引导车" value={report.statistics.guide_car_only} />
        </section>

        <section className="surface node-anomaly-distribution">
          <div className="section-heading"><h2>问题类型分布</h2><span>重复阈值 {report.repeat_window_minutes} 分钟</span></div>
          <div className="node-anomaly-bars">
            {Object.entries(report.statistics.by_type).map(([label, count]) => <div key={label}>
              <span>{label}</span><i><b style={{ width: `${Math.max(4, count / maxTypeCount * 100)}%` }} /></i><strong>{count}</strong>
            </div>)}
          </div>
        </section>

        <div className="filter-bar node-anomaly-filter">
          <label><Search size={16} /><input value={standQuery} onChange={(event) => setStandQuery(event.target.value)} placeholder="搜索机位或临时保障组" /></label>
          <select value={standFilter} onChange={(event) => setStandFilter(event.target.value)} aria-label="机位筛选">
            <option value="ALL">全部机位</option>
            {standOptions.map((stand) => <option key={stand} value={stand}>{stand}</option>)}
          </select>
          <details className="node-anomaly-node-multiselect">
            <summary>{nodeFilters.length ? `已选 ${nodeFilters.length} 类节点` : "全部异常节点"}</summary>
            <div>
              <div className="node-multiselect-actions">
                <button type="button" onClick={() => setNodeFilters(nodeOptions)}>全选</button>
                <button type="button" onClick={() => setNodeFilters([])}>清空</button>
              </div>
              {nodeOptions.map((eventType) => <label key={eventType}>
                <input type="checkbox" checked={nodeFilters.includes(eventType)} onChange={() => toggleNodeFilter(eventType)} />
                <span>{eventLabel(eventType)}</span>
              </label>)}
            </div>
          </details>
          <div className="node-anomaly-quantity-filter">
            <span>最少异常节点 <strong>{minimumQuantity}</strong></span>
            <input type="range" min="1" max={quantityMaximum} value={minimumQuantity} onChange={(event) => setMinimumQuantity(Number(event.target.value))} aria-label={`最少异常节点数量 ${minimumQuantity}`} />
            <input type="number" min="1" max={quantityMaximum} value={minimumQuantity} onChange={(event) => setMinimumQuantity(Math.max(1, Math.min(quantityMaximum, Number(event.target.value) || 1)))} aria-label="最少异常节点数量输入" />
          </div>
          <select value={problemCode} onChange={(event) => setProblemCode(event.target.value)} aria-label="问题类型">
            <option value="ALL">全部问题类型</option>
            <option value="RAPID_REPEAT">短时间重复节点</option>
            <option value="GUIDE_CAR_ONLY">只有引导车节点</option>
          </select>
          <span>当前 {filteredItems.length} 条</span>
        </div>

        <section className="surface node-anomaly-stand-summary">
          <div className="section-heading"><h2>机位异常节点统计</h2><div className="node-anomaly-summary-actions"><span>{standNodeStatistics.length} 个机位</span>{exportUrls && <a className="button secondary compact-button" href={exportUrls.statisticsExcel}><Download size={14} />下载统计表</a>}</div></div>
          <div className="node-anomaly-stand-table">
            <div className="node-anomaly-stand-head"><span>机位号</span><span>有问题的节点类型与数量</span><span>异常节点</span></div>
            {standNodeStatistics.map((row) => <button key={row.stand} className={standFilter === row.stand ? "selected" : ""} onClick={() => setStandFilter(standFilter === row.stand ? "ALL" : row.stand)}>
              <strong>{row.stand}</strong>
              <span>{row.counts.map(([eventType, count]) => <b key={eventType}>{eventLabel(eventType)} <i>{count}</i></b>)}</span>
              <em>{row.total}</em>
            </button>)}
            {!standNodeStatistics.length && <div className="empty-state compact">当前条件下没有机位异常统计</div>}
          </div>
        </section>

        <div className="node-anomaly-layout">
          <section className="surface node-anomaly-table-wrap">
            <table className="data-table interactive-table node-anomaly-table">
              <thead><tr><th>机位号</th><th>问题类型</th><th>问题原因</th><th>发生时间</th><th>节点</th><th /></tr></thead>
              <tbody>{items.map((item) => <tr
                key={item.id}
                className={selected?.id === item.id ? "selected" : ""}
                onClick={() => {
                  setSelected(item);
                  onNavigationStateChange(navigationState(item.group_id, String(visibleCount)));
                }}
                onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelected(item); onNavigationStateChange(navigationState(item.group_id, String(visibleCount))); } }}
                tabIndex={0}
              >
                <td><strong>{item.stand}</strong><small>{item.temporary_code}</small></td>
                <td><span className={`node-anomaly-kind ${item.problem_code.toLowerCase()}`}>{item.problem_type}</span></td>
                <td>{item.reason}</td>
                <td>{formatWindow(item.window_start, item.window_end)}</td>
                <td>{item.affected_node_count}/{item.group_node_count}</td>
                <td><ArrowRight size={16} /></td>
              </tr>)}</tbody>
            </table>
            {!items.length && <div className="empty-state">当前筛选条件下没有节点异常</div>}
            {items.length < (dataSource.kind === "java-shadow" ? report.statistics.total : filteredItems.length) && <button className="button secondary node-anomaly-load-more" onClick={() => setVisibleCount((value) => {
              const next = value + 100;
              onNavigationStateChange(navigationState(selected?.group_id || null, String(next)));
              return next;
            })}>加载更多（{items.length}/{dataSource.kind === "java-shadow" ? report.statistics.total : filteredItems.length}）</button>}
          </section>

          <aside className="surface node-anomaly-detail">
            {!selected ? <div className="empty-state">选择一条异常查看节点明细</div> : <>
              <div className="section-heading"><div><span>{selected.temporary_code}</span><h2>{selected.stand} 机位</h2></div><span className={`node-anomaly-kind ${selected.problem_code.toLowerCase()}`}>{selected.problem_type}</span></div>
              <div className="node-anomaly-reason"><AlertTriangle size={17} /><span><strong>问题原因</strong>{selected.reason}</span></div>
              <dl className="node-anomaly-fields">
                <div><dt>异常时间</dt><dd>{formatWindow(selected.window_start, selected.window_end)}</dd></div>
                <div><dt>保障窗口</dt><dd>{formatWindow(selected.group_start, selected.group_end)}</dd></div>
                <div><dt>异常节点</dt><dd>{selected.affected_node_count} / {selected.group_node_count} 条</dd></div>
              </dl>
              <h3>发生记录</h3>
              <div className="node-anomaly-occurrences">{selected.occurrences.map((occurrence) => <div key={occurrence.node_id}>
                <i /><strong>{eventLabel(occurrence.event_type)}</strong><time>{formatDate(occurrence.event_time)}</time>
              </div>)}</div>
              <button className="button secondary node-anomaly-open-group" onClick={() => onOpenGroup(selected)}>进入聚类结果审核<ArrowRight size={16} /></button>
            </>}
          </aside>
        </div>
      </>}
    </div>
  );
}

function Metric({ icon, label, value }: { icon: ReactNode; label: string; value: number }) {
  return <div>{icon}<span>{label}</span><strong>{value}</strong></div>;
}

function formatDate(value: string) {
  return new Date(value).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function formatWindow(start: string, end: string) {
  return start === end ? formatDate(start) : `${formatDate(start)} - ${formatDate(end)}`;
}
