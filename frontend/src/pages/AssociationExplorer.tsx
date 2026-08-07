import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, Layers3, Plane, Search } from "lucide-react";
import { api } from "../api";
import { eventLabel } from "../eventLabels";
import { StatusBadge } from "../components/StatusBadge";
import type { AssociationGroup, FlightAssociation, NodePhase } from "../types";

type Mode = "group" | "flight";

type Props = {
  runId: number;
  onOpenGroup: (groupId: number) => void;
};

const PHASE_LABELS: Record<NodePhase, string> = {
  ARRIVAL: "进港航班 A",
  TURNAROUND: "过站/出港准备 B",
  DEPARTURE: "出港航班 B"
};

export function AssociationExplorer({ runId, onOpenGroup }: Props) {
  const [mode, setMode] = useState<Mode>("group");
  const [overrunOnly, setOverrunOnly] = useState(false);
  const [query, setQuery] = useState("");
  const [groups, setGroups] = useState<AssociationGroup[]>([]);
  const [flights, setFlights] = useState<FlightAssociation[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null);
  const [selectedFlightKey, setSelectedFlightKey] = useState<string | null>(null);
  const [groupDetail, setGroupDetail] = useState<AssociationGroup | null>(null);
  const [flightDetail, setFlightDetail] = useState<FlightAssociation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    Promise.all([
      api.associationGroups(runId, overrunOnly),
      api.associationFlights(runId, overrunOnly)
    ]).then(([nextGroups, nextFlights]) => {
      if (!active) return;
      setGroups(nextGroups);
      setFlights(nextFlights);
      setSelectedGroupId((current) => nextGroups.some((item) => item.group_id === current) ? current : nextGroups[0]?.group_id || null);
      setSelectedFlightKey((current) => nextFlights.some((item) => item.association_key === current) ? current : nextFlights[0]?.association_key || null);
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "关联数据载入失败");
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [runId, overrunOnly]);

  useEffect(() => {
    let active = true;
    if (mode === "group" && selectedGroupId) {
      api.associationGroups(runId, false, selectedGroupId).then((rows) => {
        if (active) setGroupDetail(rows[0] || null);
      }).catch(() => { if (active) setGroupDetail(null); });
    }
    if (mode === "flight" && selectedFlightKey) {
      api.associationFlights(runId, false, selectedFlightKey).then((rows) => {
        if (active) setFlightDetail(rows[0] || null);
      }).catch(() => { if (active) setFlightDetail(null); });
    }
    return () => { active = false; };
  }, [mode, runId, selectedFlightKey, selectedGroupId]);

  const filteredGroups = useMemo(() => {
    const text = query.trim().toUpperCase();
    return groups.filter((group) => !text || `${group.temporary_code} ${group.stand} ${group.aircraft_no || ""} ${group.inbound_flight_no || ""} ${group.outbound_flight_no || ""}`.toUpperCase().includes(text));
  }, [groups, query]);
  const filteredFlights = useMemo(() => {
    const text = query.trim().toUpperCase();
    return flights.filter((flight) => !text || `${flight.flight_no} ${flight.service_date} ${flight.stands.join(" ")} ${flight.aircraft.join(" ")}`.toUpperCase().includes(text));
  }, [flights, query]);
  const selectedGroup = groupDetail?.group_id === selectedGroupId ? groupDetail : null;
  const selectedFlight = flightDetail?.association_key === selectedFlightKey ? flightDetail : null;

  return (
    <div className="association-page page-stack">
      <div className="page-heading">
        <div>
          <h1>双维关联验证</h1>
          <p>航空器保障过程保持连续，航班航段允许跨机位、跨航空器查看</p>
        </div>
        <div className="association-actions">
          <div className="segmented-control" aria-label="关联查看维度">
            <button className={mode === "group" ? "active" : ""} onClick={() => setMode("group")}><Layers3 size={15} />按保障组</button>
            <button className={mode === "flight" ? "active" : ""} onClick={() => setMode("flight")}><Plane size={15} />按航班</button>
          </div>
          <label className="overrun-toggle">
            <input type="checkbox" checked={overrunOnly} onChange={(event) => setOverrunOnly(event.target.checked)} />
            只看实际结束晚于计划 20 分钟
          </label>
        </div>
      </div>

      <label className="search-control association-search">
        <Search size={17} aria-hidden="true" />
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={mode === "group" ? "搜索保障组、机位、航空器或航班" : "搜索航班、机位或航空器"} />
      </label>

      {loading && <div className="surface empty-state">正在生成双维关联索引</div>}
      {error && <div className="surface empty-state danger-text">{error}</div>}
      {!loading && !error && mode === "group" && (
        <div className="association-layout">
          <AssociationGroupQueue groups={filteredGroups.slice(0, 200)} total={filteredGroups.length} selectedId={selectedGroup?.group_id || null} onSelect={setSelectedGroupId} />
          {selectedGroup ? <GroupAssociationDetail group={selectedGroup} onOpenGroup={onOpenGroup} /> : <EmptyResult />}
        </div>
      )}
      {!loading && !error && mode === "flight" && (
        <div className="association-layout">
          <FlightQueue flights={filteredFlights.slice(0, 200)} total={filteredFlights.length} selectedKey={selectedFlight?.association_key || null} onSelect={setSelectedFlightKey} />
          {selectedFlight ? <FlightAssociationDetail flight={selectedFlight} onOpenGroup={onOpenGroup} /> : <EmptyResult />}
        </div>
      )}
    </div>
  );
}

function AssociationGroupQueue({ groups, total, selectedId, onSelect }: { groups: AssociationGroup[]; total: number; selectedId: number | null; onSelect: (id: number) => void }) {
  return (
    <aside className="surface association-queue">
      <div className="section-heading"><h2>保障组</h2><span>{total} 组</span></div>
      <div className="association-queue-list">
        {groups.map((group) => (
          <button className={group.group_id === selectedId ? "selected" : ""} key={group.group_id} onClick={() => onSelect(group.group_id)}>
            <strong>{group.stand} · {group.aircraft_no || "航空器未知"}</strong>
            <span>{group.inbound_flight_no || "无进港航班"} → {group.outbound_flight_no || "无出港航班"}</span>
            <small>{formatDateTime(group.occupancy_start)} · {group.node_count} 节点</small>
            {group.overrun_minutes > 20 && <i>+{group.overrun_minutes} 分</i>}
          </button>
        ))}
        {total > groups.length && <div className="queue-limit">当前显示前 {groups.length} 组，可搜索定位其余数据</div>}
      </div>
    </aside>
  );
}

function FlightQueue({ flights, total, selectedKey, onSelect }: { flights: FlightAssociation[]; total: number; selectedKey: string | null; onSelect: (key: string) => void }) {
  return (
    <aside className="surface association-queue">
      <div className="section-heading"><h2>航班</h2><span>{total} 班</span></div>
      <div className="association-queue-list">
        {flights.map((flight) => (
          <button className={flight.association_key === selectedKey ? "selected" : ""} key={flight.association_key} onClick={() => onSelect(flight.association_key)}>
            <strong>{flight.flight_no} · {flight.service_date.slice(5)}</strong>
            <span>{flight.stands.join(" / ")} · {flight.aircraft.join(" / ") || "航空器未知"}</span>
            <small>{flight.groups.length} 个保障片段</small>
            {flight.has_aircraft_change && <i className="change">疑似换机</i>}
          </button>
        ))}
        {total > flights.length && <div className="queue-limit">当前显示前 {flights.length} 班，可搜索定位其余数据</div>}
      </div>
    </aside>
  );
}

function GroupAssociationDetail({ group, onOpenGroup }: { group: AssociationGroup; onOpenGroup: (id: number) => void }) {
  return (
    <main className="association-detail">
      <section className="surface association-summary">
        <div className="section-heading">
          <div><span className="eyebrow">{group.temporary_code}</span><h2>{group.stand} 机位 · {group.aircraft_no || "航空器未知"}</h2></div>
          <div className="association-summary-actions"><StatusBadge status={group.assignment_status} /><button className="button secondary" onClick={() => onOpenGroup(group.group_id)}>进入人工核验<ArrowRight size={16} /></button></div>
        </div>
        <div className="flight-chain">
          <div><span>前半段 · 进港</span><strong>{group.inbound_flight_no || "待确认航班 A"}</strong></div>
          <ArrowRight size={20} />
          <div><span>后半段 · 出港</span><strong>{group.outbound_flight_no || "待确认航班 B"}</strong></div>
        </div>
        <ActualPlanComparison group={group} />
      </section>
      <NodeAttributionTable groups={[group]} />
    </main>
  );
}

function FlightAssociationDetail({ flight, onOpenGroup }: { flight: FlightAssociation; onOpenGroup: (id: number) => void }) {
  return (
    <main className="association-detail">
      <section className="surface association-summary">
        <div className="section-heading">
          <div><span className="eyebrow">航班维度 · {flight.service_date}</span><h2>{flight.flight_no}</h2></div>
          {flight.has_aircraft_change && <span className="aircraft-change"><AlertTriangle size={15} />疑似跨机位换机</span>}
        </div>
        <div className="flight-piece-grid">
          {flight.groups.map((group) => (
            <button key={`${group.group_id}-${group.nodes[0]?.phase}`} onClick={() => onOpenGroup(group.group_id)}>
              <span>{group.nodes[0]?.phase === "ARRIVAL" ? "进港段" : "出港保障段"}</span>
              <strong>{group.stand} 机位 · {group.aircraft_no || "航空器未知"}</strong>
              <small>{group.temporary_code} · {group.node_count} 节点</small>
              <ArrowRight size={16} />
            </button>
          ))}
        </div>
        {flight.max_overrun_minutes > 20 && <div className="overrun-callout"><AlertTriangle size={17} /><span>至少一个保障组的实际结束比计划晚 <strong>{flight.max_overrun_minutes} 分钟</strong>，请核验末端节点归属。</span></div>}
      </section>
      <NodeAttributionTable groups={flight.groups} />
    </main>
  );
}

function ActualPlanComparison({ group }: { group: AssociationGroup }) {
  const hasPlan = group.plan_start && group.plan_end;
  const planSpan = hasPlan ? Math.max(1, new Date(group.plan_end as string).getTime() - new Date(group.plan_start as string).getTime()) : 1;
  const actualEndDelta = hasPlan ? new Date(group.occupancy_end).getTime() - new Date(group.plan_start as string).getTime() : 0;
  const actualPercent = Math.max(2, Math.min(125, (actualEndDelta / planSpan) * 100));
  return (
    <div className="plan-actual-comparison">
      <div className="comparison-labels">
        <span>计划 {hasPlan ? `${formatTime(group.plan_start as string)} - ${formatTime(group.plan_end as string)}` : "缺失"}</span>
        <span>机位占用 {formatTime(group.occupancy_start)} - {formatTime(group.occupancy_end)}（{occupancySourceLabel(group.occupancy_start_source)} / {occupancySourceLabel(group.occupancy_end_source)}）</span>
      </div>
      <div className="comparison-track">
        <i className="planned-window" />
        <i className={`actual-window ${group.overrun_minutes > 20 ? "overrun" : ""}`} style={{ width: `${actualPercent}%` }} />
        <b title="计划结束" />
      </div>
      {group.overrun_minutes > 20 && <div className="overrun-callout"><AlertTriangle size={17} /><span>实际结束晚于计划 <strong>{group.overrun_minutes} 分钟</strong>。红色区间内的节点是本案例重点核验对象。</span></div>}
    </div>
  );
}

function NodeAttributionTable({ groups }: { groups: AssociationGroup[] }) {
  const rows = groups.flatMap((group) => group.nodes.map((node) => ({ group, node })));
  return (
    <section className="surface attribution-table-wrap">
      <div className="section-heading"><h2>节点归属明细</h2><span>{rows.length} 条</span></div>
      <table className="data-table attribution-table">
        <thead><tr><th>时间</th><th>节点</th><th>作业阶段</th><th>归属航班</th><th>机位 / 航空器</th><th>保障组</th></tr></thead>
        <tbody>
          {rows.map(({ group, node }) => (
            <tr className={group.plan_end && node.event_time && new Date(node.event_time) > new Date(group.plan_end) ? "after-plan" : ""} key={`${group.group_id}-${node.id}`}>
              <td>{node.event_time ? formatDateTime(node.event_time) : "时间异常"}</td>
              <td><strong title={node.event_type}>{eventLabel(node.event_type)}</strong></td>
              <td><span className={`phase-badge ${node.phase.toLowerCase()}`}>{PHASE_LABELS[node.phase]}</span></td>
              <td><strong>{node.attributed_flight_no || "待确认"}</strong></td>
              <td>{group.stand} / {group.aircraft_no || "未知"}</td>
              <td><span className="group-code" title={group.temporary_code}>{group.temporary_code}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function EmptyResult() {
  return <div className="surface empty-state">没有符合条件的关联数据</div>;
}

function formatTime(value: string): string {
  return new Date(value).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function occupancySourceLabel(source: string): string {
  const labels: Record<string, string> = {
    acdm_aircraft_entry: "人工入位锚点",
    algorithm_aircraft_entry: "算法入位",
    algorithm_terminal: "算法推出/牵引结束",
    acdm_stand_release: "人工释放兜底",
    observed_group_start: "分组首节点",
    observed_group_end: "分组末节点"
  };
  return labels[source] || source;
}
