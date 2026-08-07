import { useEffect, useMemo, useRef, useState } from "react";
import {
  BaggageClaim,
  CarFront,
  DoorOpen,
  Fuel,
  Link2,
  List,
  Maximize2,
  Plane,
  ScanLine,
  Shapes,
  TrafficCone,
  Truck,
  Utensils,
  ZoomIn,
  ZoomOut,
  type LucideIcon
} from "lucide-react";
import type { Candidate, GroupDetail, NodeEvent } from "../types";
import { eventLabel } from "../eventLabels";
import { SOURCE_LABELS } from "../labels";

const WIDTH = 980;
const LEFT = 126;
const RIGHT = 30;
const MIN_WINDOW_MS = 5 * 60_000;
const MAX_ZOOM = 64;

type TimeWindow = { start: number; end: number };
type NodeDisplayMode = "compact" | "full";
type BoundaryRole = "start" | "end" | "point";

type NodeVisual = {
  icon?: LucideIcon;
  fallback?: string;
  state: "start" | "end" | "neutral";
};

const EVENT_FAMILIES: Record<string, [string, BoundaryRole]> = {
  AircraftStart: ["aircraft-entry", "start"],
  AircraftEntry: ["aircraft-entry", "end"],
  AircraftBeginsTaxi: ["aircraft-departure", "start"],
  AircraftLeave: ["aircraft-departure", "end"],
  GuideCarStart: ["guide-car", "start"],
  GuideCarEnd: ["guide-car", "end"],
  BaggageTractorInPosition: ["baggage-tractor", "start"],
  BaggageTractorDeparted: ["baggage-tractor", "end"],
  LuggageCarBegin: ["baggage-handling", "start"],
  LuggageCarEnd: ["baggage-handling", "end"],
  FirstPieceBaggage: ["first-baggage", "point"],
  FlightFoodArrival: ["catering-vehicle", "start"],
  FlightFoodLeave: ["catering-vehicle", "end"],
  FlightFoodStart: ["catering-operation", "start"],
  FlightFoodEnd: ["catering-operation", "end"],
  OilseedsCarArrival: ["fuel-vehicle", "start"],
  OilseedsCarLeave: ["fuel-vehicle", "end"],
  OilseedsStart: ["fuel-operation", "start"],
  OilseedsEnd: ["fuel-operation", "end"],
  AccessCorridorBridgeBegin: ["bridge-docking", "start"],
  AccessCorridorBridge: ["bridge-docking", "end"],
  RemoveCorridorBridgeBegin: ["bridge-removal", "start"],
  RemoveCorridorBridge: ["bridge-removal", "end"],
  OpenCabinDoor: ["cabin-door", "start"],
  CloseCabinDoor: ["cabin-door", "end"],
  OpenCargoDoor: ["cargo-door", "start"],
  CloseCargoDoor: ["cargo-door", "end"],
  PlaceChockBegin: ["place-chock", "start"],
  PlaceChockEnd: ["place-chock", "end"],
  RemoveWheelGearStart: ["remove-chock", "start"],
  RemoveWheelGearEnd: ["remove-chock", "end"],
  ReflectiveBucketPlacementStart: ["place-cone", "start"],
  ReflectiveBucketPlacementCompletion: ["place-cone", "end"],
  LadderCarNear: ["ladder-arrival", "start"],
  LadderCarEntry: ["ladder-arrival", "end"],
  LadderCarStartLeave: ["ladder-departure", "start"],
  LadderCarLeave: ["ladder-departure", "end"],
  TowShow: ["tow-vehicle", "start"],
  TowArrival: ["tow-vehicle", "start"],
  TractorInPosition: ["tow-vehicle", "start"],
  TowEnd: ["tow-vehicle", "end"]
};

function timeLabel(value: Date): string {
  return value.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function flightLabel(candidate: Candidate): string {
  const plan = candidate.flight_plan;
  return [plan.inbound_flight_no, plan.outbound_flight_no].filter(Boolean).join(" / ") || plan.flight_key;
}

function nodeVisual(eventType: string): NodeVisual {
  const state = /Leave|End|Close|Remove|Departed|BeginsTaxi|StartLeave/i.test(eventType)
    ? "end"
    : /Entry|Start|Begin|Arrival|InPosition|Open|AccessCorridorBridge/i.test(eventType)
      ? "start"
      : "neutral";

  if (/Aircraft/i.test(eventType)) return { icon: Plane, state };
  if (/Oilseeds|Fuel/i.test(eventType)) return { icon: Fuel, state };
  if (/Baggage|Luggage/i.test(eventType)) return { icon: BaggageClaim, state };
  if (/FlightFood|Catering/i.test(eventType)) return { icon: Utensils, state };
  if (/CorridorBridge/i.test(eventType)) return { icon: Link2, state };
  if (/CabinDoor|CargoDoor/i.test(eventType)) return { icon: DoorOpen, state };
  if (/Ladder/i.test(eventType)) return { icon: Truck, state };
  if (/Tow|Tractor/i.test(eventType)) return { fallback: "牵", state };
  if (/GuideCar/i.test(eventType)) return { icon: CarFront, state };
  if (/ReflectiveBucket|Cone/i.test(eventType)) return { icon: TrafficCone, state };
  if (/Chock|WheelGear/i.test(eventType)) return { fallback: "挡", state };
  if (/ClearWater|CleanWater|WaterSupply/i.test(eventType)) return { fallback: "清", state };
  if (/Sewage|WasteWater|Toilet/i.test(eventType)) return { fallback: "污", state };
  return { fallback: eventLabel(eventType) === "未命名节点" ? "?" : eventLabel(eventType).slice(0, 1), state };
}

function eventFamily(eventType: string): [string, BoundaryRole] {
  const known = EVENT_FAMILIES[eventType];
  if (known) return known;
  const role: BoundaryRole = /Completion|Completed|End|Leave|Close|Departed/i.test(eventType)
    ? "end"
    : /Start|Begin|Open|Arrival|Entry|InPosition/i.test(eventType)
      ? "start"
      : "point";
  const family = eventType.replace(
    /(PlacementCompletion|Completion|Completed|StartLeave|InPosition|Arrival|Departed|Begin|Start|Entry|Leave|End|Open|Close)$/i,
    ""
  );
  return [family || eventType, role];
}

function compactNodeIds(nodes: NodeEvent[]): Set<number> {
  const families = new Map<string, { start?: NodeEvent; end?: NodeEvent; point?: NodeEvent }>();
  const ordered = [...nodes].filter((node) => node.event_time).sort((left, right) =>
    new Date(left.event_time as string).getTime() - new Date(right.event_time as string).getTime()
  );
  for (const node of ordered) {
    const [family, role] = eventFamily(node.event_type);
    const state = families.get(family) || {};
    if (role === "start" && !state.start) state.start = node;
    if (role === "end") state.end = node;
    if (role === "point" && !state.point) state.point = node;
    families.set(family, state);
  }
  return new Set(
    [...families.values()].flatMap((state) => [state.start, state.end, state.point])
      .filter((node): node is NodeEvent => Boolean(node))
      .map((node) => node.id)
  );
}

function NodeMark({ node, x, y }: { node: NodeEvent; x: number; y: number }) {
  const source = node.source_type;
  if (source === "manual_report" || source === "acdm_reference" || source === "acdm_simulation") {
    const points = `${x},${y - 6} ${x + 6},${y} ${x},${y + 6} ${x - 6},${y}`;
    return <polygon className={`node-mark ${source}`} points={points} />;
  }
  return <circle className="node-mark algorithm_node" cx={x} cy={y} r="5" />;
}

function NodeIcon({ node, x, y }: { node: NodeEvent; x: number; y: number }) {
  const visual = nodeVisual(node.event_type);
  const Icon = visual.icon;
  const label = eventLabel(node.event_type);
  const time = node.event_time ? timeLabel(new Date(node.event_time)) : "时间异常";
  const source = SOURCE_LABELS[node.source_type] || node.source_type;
  return (
    <g className={`node-icon ${visual.state}`} role="img" aria-label={`${label}，${time}，${source}`}>
      <title>{label} · {time} · {source}</title>
      <rect x={x - 14} y={y - 14} width="28" height="28" rx="4" />
      {Icon ? (
        <Icon x={x - 9} y={y - 9} width={18} height={18} strokeWidth={2.2} aria-hidden="true" />
      ) : (
        <text x={x} y={y + 5} textAnchor="middle" aria-hidden="true">{visual.fallback}</text>
      )}
      <circle className={`node-source-dot ${node.source_type}`} cx={x + 11} cy={y - 11} r="3.2" />
    </g>
  );
}

export function FlightTimeline({
  group,
  selectedFlightPlanId,
  recoveryWindow
}: {
  group: GroupDetail;
  selectedFlightPlanId?: number | null;
  recoveryWindow?: { start: string; end: string } | null;
}) {
  const visibleSources = new Set(group.nodes.map((node) => node.source_type));
  const timelineCandidates = useMemo(
    () => group.candidates.filter((candidate) => recoveryWindow || !candidate.excluded_reason),
    [group.candidates, recoveryWindow]
  );
  const bounds = useMemo(() => {
    const candidateDates = timelineCandidates.flatMap((candidate) =>
      [candidate.flight_plan.plan_start, candidate.flight_plan.plan_end]
        .filter(Boolean)
        .map((value) => new Date(value as string).getTime())
    );
    const nodeDates = group.nodes
      .filter((node) => node.event_time)
      .map((node) => new Date(node.event_time as string).getTime());
    const allTimes = [
      new Date(group.observed_start).getTime(),
      new Date(group.observed_end).getTime(),
      ...(recoveryWindow ? [new Date(recoveryWindow.start).getTime(), new Date(recoveryWindow.end).getTime()] : []),
      ...candidateDates,
      ...nodeDates
    ];
    return {
      start: Math.min(...allTimes) - 20 * 60_000,
      end: Math.max(...allTimes) + 20 * 60_000
    };
  }, [timelineCandidates, group.nodes, group.observed_end, group.observed_start, recoveryWindow]);
  const [timeWindow, setTimeWindow] = useState<TimeWindow>(bounds);
  const [nodeDisplayMode, setNodeDisplayMode] = useState<NodeDisplayMode>("compact");
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef<{
    pointerId: number;
    startX: number;
    window: TimeWindow;
  } | null>(null);

  useEffect(() => {
    setTimeWindow(bounds);
  }, [group.id, bounds.start, bounds.end]);

  const fullSpan = Math.max(60_000, bounds.end - bounds.start);
  const minimumSpan = Math.max(MIN_WINDOW_MS, fullSpan / MAX_ZOOM);
  const span = Math.max(60_000, timeWindow.end - timeWindow.start);
  const minTime = timeWindow.start;
  const maxTime = timeWindow.end;
  const x = (value: string | Date) =>
    LEFT + ((new Date(value).getTime() - minTime) / span) * (WIDTH - LEFT - RIGHT);
  const laneHeight = 46;
  const candidateCount = Math.max(1, timelineCandidates.length);
  const nodeY = 66 + candidateCount * laneHeight + 54;
  const labelOffsets = [-24, 28, -52, 56, -80, 84];
  const laneLastX = labelOffsets.map(() => -Infinity);
  const compactIds = useMemo(() => compactNodeIds(group.nodes), [group.nodes]);
  const displayedNodes = nodeDisplayMode === "compact"
    ? group.nodes.filter((node) => compactIds.has(node.id))
    : group.nodes;
  const nodeLabels = displayedNodes.filter((node) => {
    if (!node.event_time) return false;
    const value = new Date(node.event_time).getTime();
    return value >= minTime && value <= maxTime;
  }).map((node) => {
    const markX = node.event_time ? x(node.event_time) : LEFT;
    const minimumGap = nodeDisplayMode === "compact" ? 30 : 72;
    let lane = laneLastX.findIndex((lastX) => markX - lastX >= minimumGap);
    if (lane < 0) lane = laneLastX.indexOf(Math.min(...laneLastX));
    laneLastX[lane] = markX;
    return { node, markX, offset: labelOffsets[lane] };
  });
  const height = nodeY + 92;
  const ticks = Array.from({ length: 7 }, (_, index) => new Date(minTime + (span * index) / 6));
  const zoomPercent = Math.round((fullSpan / span) * 100);
  const selectedCandidate = timelineCandidates.find((candidate) => candidate.flight_plan.id === selectedFlightPlanId);
  const canFocusSelected = Boolean(selectedCandidate?.flight_plan.plan_start && selectedCandidate?.flight_plan.plan_end);

  function clampWindow(nextStart: number, nextEnd: number): TimeWindow {
    const nextSpan = Math.min(fullSpan, Math.max(minimumSpan, nextEnd - nextStart));
    const start = Math.max(bounds.start, Math.min(nextStart, bounds.end - nextSpan));
    return { start, end: start + nextSpan };
  }

  function zoom(factor: number, anchor = 0.5) {
    setTimeWindow((current) => {
      const currentSpan = current.end - current.start;
      const nextSpan = currentSpan * factor;
      const anchorTime = current.start + currentSpan * anchor;
      const nextStart = anchorTime - nextSpan * anchor;
      return clampWindow(nextStart, nextStart + nextSpan);
    });
  }

  function pan(deltaRatio: number, sourceWindow = timeWindow) {
    const sourceSpan = sourceWindow.end - sourceWindow.start;
    const shift = sourceSpan * deltaRatio;
    setTimeWindow(clampWindow(sourceWindow.start + shift, sourceWindow.end + shift));
  }

  function focusSelectedFlight() {
    const plan = selectedCandidate?.flight_plan;
    if (!plan?.plan_start || !plan.plan_end) return;
    const start = new Date(plan.plan_start).getTime();
    const end = new Date(plan.plan_end).getTime();
    if (!Number.isFinite(start) || !Number.isFinite(end) || start >= end) return;
    setTimeWindow(clampWindow(start, end));
  }

  function plotGeometry(element: SVGSVGElement) {
    const rect = element.getBoundingClientRect();
    return {
      left: rect.left + (LEFT / WIDTH) * rect.width,
      width: ((WIDTH - LEFT - RIGHT) / WIDTH) * rect.width
    };
  }

  function handleWheel(event: React.WheelEvent<SVGSVGElement>) {
    event.preventDefault();
    const plot = plotGeometry(event.currentTarget);
    if (Math.abs(event.deltaX) > Math.abs(event.deltaY) || event.shiftKey) {
      pan((event.deltaX || event.deltaY) / plot.width);
      return;
    }
    const anchor = Math.max(0, Math.min(1, (event.clientX - plot.left) / plot.width));
    zoom(event.deltaY < 0 ? 0.82 : 1.22, anchor);
  }

  function handlePointerDown(event: React.PointerEvent<SVGSVGElement>) {
    if (event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = { pointerId: event.pointerId, startX: event.clientX, window: timeWindow };
    setDragging(true);
  }

  function handlePointerMove(event: React.PointerEvent<SVGSVGElement>) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const plot = plotGeometry(event.currentTarget);
    pan(-(event.clientX - drag.startX) / plot.width, drag.window);
  }

  function handlePointerEnd(event: React.PointerEvent<SVGSVGElement>) {
    if (dragRef.current?.pointerId !== event.pointerId) return;
    dragRef.current = null;
    setDragging(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  return (
    <div className="timeline-wrap">
      <div className="timeline-toolbar">
        <div className="timeline-mode-switch" role="group" aria-label="节点显示模式">
          <button
            type="button"
            className={nodeDisplayMode === "compact" ? "active" : ""}
            title="简洁模式：每类节点仅显示首次开始和末次结束"
            aria-label="节点简洁模式"
            aria-pressed={nodeDisplayMode === "compact"}
            onClick={() => setNodeDisplayMode("compact")}
          >
            <Shapes size={14} /><span>简洁</span>
          </button>
          <button
            type="button"
            className={nodeDisplayMode === "full" ? "active" : ""}
            title="完整模式：显示全部节点和中文名称"
            aria-label="节点完整模式"
            aria-pressed={nodeDisplayMode === "full"}
            onClick={() => setNodeDisplayMode("full")}
          >
            <List size={14} /><span>完整</span>
          </button>
        </div>
        <button
          type="button"
          className="timeline-focus-button"
          title="所选航班铺满时间轴"
          aria-label="所选航班铺满时间轴"
          disabled={!canFocusSelected}
          onClick={focusSelectedFlight}
        >
          <ScanLine size={15} /><span>铺满当前航班</span>
        </button>
        <div className="timeline-scale-controls">
          <span aria-live="polite">{zoomPercent}%</span>
          <button type="button" className="icon-button" title="缩小时间轴" aria-label="缩小时间轴" disabled={span >= fullSpan} onClick={() => zoom(1.25)}>
            <ZoomOut size={16} />
          </button>
          <button type="button" className="icon-button" title="放大时间轴" aria-label="放大时间轴" disabled={span <= minimumSpan} onClick={() => zoom(0.8)}>
            <ZoomIn size={16} />
          </button>
          <button type="button" className="icon-button" title="适应全部数据" aria-label="适应全部数据" disabled={span >= fullSpan} onClick={() => setTimeWindow(bounds)}>
            <Maximize2 size={16} />
          </button>
        </div>
      </div>
      <div className={`timeline-viewport ${dragging ? "dragging" : ""}`}>
        <svg
          className="flight-timeline"
          viewBox={`0 0 ${WIDTH} ${height}`}
          role="img"
          aria-label={`${group.stand}机位航班计划与节点时间轴`}
          onWheel={handleWheel}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerEnd}
          onPointerCancel={handlePointerEnd}
        >
        <title>{group.stand}机位航班计划与节点时间轴</title>
        <desc>候选航班显示为时间条，算法和A-CDM现场节点显示为不同形状的时间点。</desc>
        <defs>
          <pattern id="invalidPattern" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="8" height="8" className="invalid-pattern-bg" />
            <line x1="0" y1="0" x2="0" y2="8" className="invalid-pattern-line" />
          </pattern>
        </defs>
        {recoveryWindow && (
          <rect
            className="recovery-request-window"
            x={x(recoveryWindow.start)}
            y="30"
            width={Math.max(3, x(recoveryWindow.end) - x(recoveryWindow.start))}
            height={height - 58}
          />
        )}
        {ticks.map((tick) => (
          <g key={tick.toISOString()}>
            <line className="timeline-grid" x1={x(tick)} y1="30" x2={x(tick)} y2={height - 28} />
            <text className="timeline-tick" x={x(tick)} y="20" textAnchor="middle">
              {timeLabel(tick)}
            </text>
          </g>
        ))}

        {timelineCandidates.map((candidate, index) => {
          const plan = candidate.flight_plan;
          if (!plan.plan_start || !plan.plan_end) return null;
          const y = 48 + index * laneHeight;
          const planStart = new Date(plan.plan_start).getTime();
          const planEnd = new Date(plan.plan_end).getTime();
          const visibleStart = Math.max(planStart, minTime);
          const visibleEnd = Math.min(planEnd, maxTime);
          const visible = visibleStart < visibleEnd;
          const barX = LEFT + ((visibleStart - minTime) / span) * (WIDTH - LEFT - RIGHT);
          const barWidth = Math.max(5, ((visibleEnd - visibleStart) / span) * (WIDTH - LEFT - RIGHT));
          const selected = selectedFlightPlanId === plan.id || candidate.selected || group.assigned_flight_id === plan.id;
          const problem = Boolean(candidate.excluded_reason) || plan.issue_tags.includes("LONG_WINDOW") || plan.issue_tags.includes("INVALID_YEAR");
          return (
            <g key={candidate.id}>
              <text className="timeline-label" x="8" y={y + 18}>
                {flightLabel(candidate)}
              </text>
              {visible && (
                <>
                  <rect
                    className={`plan-bar ${selected ? "selected" : ""} ${problem ? "invalid" : ""}`}
                    x={barX}
                    y={y}
                    width={barWidth}
                    height="24"
                    rx="3"
                  />
                  <text className="plan-score" x={Math.min(barX + 8, WIDTH - 62)} y={y + 17}>
                    {candidate.score.toFixed(0)}分
                  </text>
                </>
              )}
            </g>
          );
        })}

        <rect
          className="observed-occupancy-window"
          x={x(group.observed_start)}
          y={nodeY - 6}
          width={Math.max(3, x(group.observed_end) - x(group.observed_start))}
          height="12"
          rx="3"
        />
        <line className="node-lane" x1={LEFT} y1={nodeY} x2={WIDTH - RIGHT} y2={nodeY} />
        <text className="timeline-label" x="8" y={nodeY + 4}>
          保障节点
        </text>
        {nodeLabels.map(({ node, markX, offset }) => {
          if (!node.event_time) return null;
          const markerY = nodeDisplayMode === "compact" ? nodeY + offset : nodeY;
          return (
            <g key={node.id}>
              <line className="node-stem" x1={markX} y1={nodeY} x2={markX} y2={nodeY + offset} />
              {nodeDisplayMode === "compact" ? (
                <NodeIcon node={node} x={markX} y={markerY} />
              ) : (
                <>
                  <NodeMark node={node} x={markX} y={nodeY} />
                  <text
                    className="node-label"
                    x={markX}
                    y={nodeY + offset + (offset < 0 ? -4 : 11)}
                    textAnchor="middle"
                  >
                    {eventLabel(node.event_type)}
                  </text>
                </>
              )}
            </g>
          );
        })}
        </svg>
      </div>
      <div className="timeline-legend" aria-label="节点来源图例">
        {recoveryWindow && <span><i className="legend-window request" aria-hidden="true" />补拉请求范围</span>}
        {recoveryWindow && <span><i className="legend-window observed" aria-hidden="true" />实际保障窗口</span>}
        {Object.entries(SOURCE_LABELS).filter(([source]) => visibleSources.has(source)).map(([source, label]) => (
          <span key={source}>
            <i className={`legend-mark ${source}`} aria-hidden="true" />
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}
