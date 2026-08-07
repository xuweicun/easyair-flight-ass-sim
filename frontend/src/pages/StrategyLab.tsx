import { useEffect, useState } from "react";
import { FlaskConical, Play, RotateCcw, Save, ShieldCheck, Sparkles } from "lucide-react";
import { api } from "../api";
import { issueLabel, statusLabel } from "../labels";
import type { Dashboard, RecoveryPolicy, RecoveryPolicyConfig, RecoveryReplayTask, Strategy, StrategyConfig, Suggestion } from "../types";

type Props = {
  dashboard: Dashboard;
  strategies: Strategy[];
  suggestions: Suggestion[];
  busy: boolean;
  onRunDraft: (name: string, config: StrategyConfig) => Promise<void>;
};

const DEFAULT_TERMINAL_TAIL_EVENT_POLICY = {
  group_start_events: ["AircraftStart", "GuideCarStart", "TowStart", "飞机开始入位", "引导车开始", "牵引车开始"],
  aircraft_entry_events: ["AircraftEntry", "飞机入位", "入位"],
  aircraft_leave_events: ["AircraftLeave", "飞机推出", "推出"],
  tow_end_events: ["TowEnd", "牵引车结束", "拖曳结束"],
  allowed_tail_events: ["AircraftLeave", "AircraftBeginsTaxi", "TowEnd", "离位", "推出", "拖曳结束", "OpenCargoDoor", "CloseCargoDoor", "CloseCabinDoor", "RemoveCorridorBridgeBegin", "RemoveCorridorBridge", "RemoveWheelGearStart", "RemoveWheelGearEnd", "TowArrival", "TractorInPosition", "TowShow"]
};

export function StrategyLab({ dashboard, strategies, suggestions, busy, onRunDraft }: Props) {
  const [name, setName] = useState(`候选策略 v${strategies.length + 1}`);
  const [config, setConfig] = useState<StrategyConfig>(() => normalizeConfig(dashboard.strategy.config));
  const [mode, setMode] = useState<"matching" | "recovery">("matching");

  useEffect(() => setConfig(normalizeConfig(dashboard.strategy.config)), [dashboard.strategy.id]);

  function setNumber(key: keyof StrategyConfig, value: number) {
    setConfig((current) => ({ ...current, [key]: value }));
  }

  function setWeight(key: keyof StrategyConfig["weights"], value: number) {
    setConfig((current) => ({ ...current, weights: { ...current.weights, [key]: value } }));
  }

  function applySuggestion(suggestion: Suggestion) {
    setConfig((current) => ({
      ...current,
      ...suggestion.patch,
      weights: suggestion.patch.weights
        ? { ...current.weights, ...suggestion.patch.weights }
        : current.weights
    } as StrategyConfig));
  }

  const statuses = dashboard.active_run.metrics.status_counts;
  const total = Object.values(statuses).reduce((sum, value) => sum + value, 0) || 1;

  if (mode === "recovery") {
    return <RecoveryPolicyEditor dashboard={dashboard} onShowMatching={() => setMode("matching")} />;
  }

  return (
    <div className="page-stack">
      <div className="page-heading">
        <div><h1>策略实验室</h1><p>当前运行：{dashboard.strategy.name} · #{dashboard.active_run.id}</p></div>
        <div className="heading-actions">
          <div className="segmented-control" aria-label="策略类别">
            <button className="active">匹配策略</button>
            <button onClick={() => setMode("recovery")}>出站与恢复策略</button>
          </div>
          <button className="button secondary" onClick={() => setConfig(normalizeConfig(dashboard.strategy.config))}>
            <RotateCcw size={16} />恢复当前版本
          </button>
          <button className="button primary" disabled={busy || !name.trim()} onClick={() => onRunDraft(name, config)}>
            <FlaskConical size={17} />{busy ? "正在重跑" : "保存草稿并全量重跑"}
          </button>
        </div>
      </div>

      <section className="surface outcome-strip">
        <div className="section-heading"><h2>本轮归属结果</h2><span>{total} 个临时航班组</span></div>
        <div className="stacked-outcome" role="img" aria-label="匹配状态分布">
          {Object.entries(statuses).map(([status, value]) => (
            <i key={status} className={`outcome-${status.toLowerCase()}`} style={{ width: `${(value / total) * 100}%` }} title={`${statusLabel(status)} ${value}`} />
          ))}
        </div>
        <div className="outcome-legend">
          {Object.entries(statuses).map(([status, value]) => <span key={status}><i className={`outcome-${status.toLowerCase()}`} />{statusLabel(status)} <b>{value}</b></span>)}
        </div>
      </section>

      <div className="strategy-layout">
        <section className="surface strategy-form">
          <div className="section-heading"><h2>候选版本参数</h2><span>基于 #{dashboard.strategy.id}</span></div>
          <label>
            版本名称
            <input value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <h3>节点聚类</h3>
          <RangeField label="空闲分组阈值" unit="分钟" min={60} max={300} value={config.idle_gap_minutes} onChange={(value) => setNumber("idle_gap_minutes", value)} />
          <RangeField label="进位链回溯窗口" unit="分钟" min={5} max={60} value={config.approach_chain_minutes ?? 30} onChange={(value) => setNumber("approach_chain_minutes", value)} />
          <label className="toggle-field">
            <input
              type="checkbox"
              checked={config.terminal_tail_reattach_enabled ?? false}
              onChange={(event) => setConfig((current) => ({ ...current, terminal_tail_reattach_enabled: event.target.checked }))}
            />
            <span>启用结束链回接<small>仅用于仿真实验，节点类型规则随草稿版本保存</small></span>
          </label>
          <RangeField label="结束链最长回看" unit="分钟" min={180} max={600} value={config.terminal_tail_lookback_minutes ?? 480} onChange={(value) => setNumber("terminal_tail_lookback_minutes", value)} />
          <label className="toggle-field">
            <input
              type="checkbox"
              checked={config.combination_parent_guard_enabled ?? false}
              onChange={(event) => setConfig((current) => ({ ...current, combination_parent_guard_enabled: event.target.checked }))}
            />
            <span>启用组合主机位占用防护<small>按当日计划和左右机位实际占用阻止资源冲突</small></span>
          </label>
          <RangeField label="缺结束占用超时" unit="分钟" min={60} max={720} value={config.open_occupancy_timeout_minutes ?? 480} onChange={(value) => setNumber("open_occupancy_timeout_minutes", value)} />
          <RangeField label="外观可信阈值" unit="%" min={50} max={99} value={Math.round(config.appearance_confidence_threshold * 100)} onChange={(value) => setNumber("appearance_confidence_threshold", value / 100)} />
          <RangeField label="A-CDM节点时间容差" unit="分钟" min={1} max={15} value={config.acdm_time_tolerance_minutes ?? 10} onChange={(value) => setNumber("acdm_time_tolerance_minutes", value)} />
          <h3>计划窗口</h3>
          <RangeField label="时间偏差衰减范围" unit="分钟" min={60} max={360} value={config.time_decay_minutes ?? 180} onChange={(value) => setNumber("time_decay_minutes", value)} />
          <RangeField label="可信窗口上限" unit="小时" min={4} max={24} value={config.max_plan_hours} onChange={(value) => setNumber("max_plan_hours", value)} />
          <h3>自动归属</h3>
          <label className="toggle-field">
            <input
              type="checkbox"
              checked={config.sequence_resolution_enabled ?? false}
              onChange={(event) => setConfig((current) => ({ ...current, sequence_resolution_enabled: event.target.checked }))}
            />
            <span>启用同机位顺序消歧<small>仅在前序正常且计划窗口与节点时间重叠时使用</small></span>
          </label>
          <RangeField label="自动匹配分数" unit="分" min={40} max={120} value={config.auto_match_threshold} onChange={(value) => setNumber("auto_match_threshold", value)} />
          <RangeField label="候选领先分差" unit="分" min={0} max={40} value={config.minimum_margin} onChange={(value) => setNumber("minimum_margin", value)} />
          <h3>证据权重</h3>
          <div className="weight-grid">
            {Object.entries(config.weights).map(([key, value]) => (
              <label key={key}>{weightLabel(key)}<input type="number" min="0" max="60" value={value} onChange={(event) => setWeight(key as keyof StrategyConfig["weights"], Number(event.target.value))} /></label>
            ))}
          </div>
        </section>

        <div className="strategy-side">
          <section className="surface">
            <div className="section-heading"><h2>系统建议</h2><Sparkles size={18} /></div>
            <div className="suggestion-list">
              {suggestions.map((suggestion) => (
                <div className="suggestion-item" key={suggestion.key}>
                  <div><strong>{suggestion.title}</strong><span>{suggestion.affected_groups} 组受影响</span></div>
                  <p>{suggestion.evidence}</p>
                  <button className="button secondary" onClick={() => applySuggestion(suggestion)}><Save size={15} />应用到草稿</button>
                </div>
              ))}
              {!suggestions.length && <div className="empty-state compact">本轮没有新的参数建议</div>}
            </div>
          </section>

          <section className="surface">
            <div className="section-heading"><h2>问题影响</h2><span>当前运行</span></div>
            <div className="issue-impact-list">
              {Object.entries(dashboard.issue_counts).sort((a, b) => b[1] - a[1]).map(([key, value]) => (
                <div key={key}><span>{issueLabel(key)}</span><strong>{value}</strong></div>
              ))}
            </div>
          </section>

          <section className="surface">
            <div className="section-heading"><h2>版本记录</h2><span>{strategies.length} 个版本</span></div>
            <div className="version-list">
              {strategies.map((strategy) => (
                <div key={strategy.id}><span className={`version-state ${strategy.status}`} /> <strong>{strategy.name}</strong><small>#{strategy.id} · {strategy.status === "published" ? "已发布" : "草稿"}</small></div>
              ))}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

function RecoveryPolicyEditor({ dashboard, onShowMatching }: { dashboard: Dashboard; onShowMatching: () => void }) {
  const [policy, setPolicy] = useState<RecoveryPolicy | null>(null);
  const [config, setConfig] = useState<RecoveryPolicyConfig | null>(null);
  const [draft, setDraft] = useState<RecoveryPolicy | null>(null);
  const [task, setTask] = useState<RecoveryReplayTask | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    api.recoveryPolicy()
      .then((result) => { setPolicy(result); setConfig(result.config); })
      .catch((reason: unknown) => setMessage(reason instanceof Error ? reason.message : "生效策略载入失败"));
  }, []);

  function setNumber(key: keyof RecoveryPolicyConfig, value: number) {
    setConfig((current) => current ? ({ ...current, [key]: value }) : current);
  }

  async function act(action: () => Promise<void>) {
    setBusy(true);
    setMessage(null);
    try { await action(); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "操作失败"); } finally { setBusy(false); }
  }

  if (!policy || !config) return <div className="boot-state">{message ? <><ShieldCheck size={26} /><span>{message}</span></> : <><RotateCcw className="spin" size={26} /><span>正在读取生效策略</span></>}</div>;

  return (
    <div className="page-stack">
      <div className="page-heading">
        <div><h1>策略实验室</h1><p>出站与恢复策略 · {policy.airport_code}/{policy.destination} · v{policy.version}</p></div>
        <div className="segmented-control" aria-label="策略类别">
          <button onClick={onShowMatching}>匹配策略</button>
          <button className="active">出站与恢复策略</button>
        </div>
      </div>
      {message && <div className="recovery-alert">{message}</div>}
      <div className="recovery-policy-layout">
        <section className="surface strategy-form">
          <div className="section-heading"><h2>生效范围与出站能力</h2><span>{policy.status === "published" ? "当前生效" : policy.status}</span></div>
          <div className="form-row">
            <label>机场<input value={policy.airport_code} disabled /></label>
            <label>租户<input value={policy.tenant_code} disabled /></label>
            <label>目的端<input value={policy.destination} disabled /></label>
            <label>目的端能力<input value={config.destination_capability} disabled /></label>
          </div>
          <h3>临时保障组出站</h3>
          <label className="toggle-field locked-policy">
            <input type="checkbox" checked={config.temporary_group_send_enabled} disabled={policy.temporary_group_send_locked} onChange={(event) => setConfig({ ...config, temporary_group_send_enabled: event.target.checked })} />
            <span>发送无航班号临时保障组<small>{policy.temporary_group_send_locked ? "西安总线不接受临时保障组，此项固定关闭" : "仅在目的端能力明确支持时可开启"}</small></span>
          </label>
          <h3>航班计划恢复</h3>
          <label className="toggle-field"><input type="checkbox" checked={config.flight_recovery_enabled} onChange={(event) => setConfig({ ...config, flight_recovery_enabled: event.target.checked })} /><span>启用航班计划补拉<small>仅 PLAN_MISSING 进入恢复，DATA_ERROR 固定不补拉</small></span></label>
          <RangeField label="最大补拉次数" unit="次" min={1} max={8} value={config.max_attempts} onChange={(value) => setNumber("max_attempts", value)} />
          <RangeField label="请求窗向前" unit="分钟" min={30} max={360} value={config.request_window_before_minutes} onChange={(value) => setNumber("request_window_before_minutes", value)} />
          <RangeField label="请求窗向后" unit="分钟" min={30} max={360} value={config.request_window_after_minutes} onChange={(value) => setNumber("request_window_after_minutes", value)} />
          <RangeField label="恢复截止时间" unit="分钟" min={30} max={360} value={config.recovery_deadline_minutes} onChange={(value) => setNumber("recovery_deadline_minutes", value)} />
          <h3>运行门禁</h3>
          <RangeField label="终态扫描周期" unit="秒" min={15} max={300} value={config.terminal_scan_interval_seconds} onChange={(value) => setNumber("terminal_scan_interval_seconds", value)} />
          <RangeField label="Outbox最大等待" unit="秒" min={30} max={900} value={config.outbox_max_wait_seconds} onChange={(value) => setNumber("outbox_max_wait_seconds", value)} />
        </section>

        <aside className="surface recovery-policy-actions">
          <div className="section-heading"><h2>变更流程</h2><span>配置版本 {draft?.version || policy.version}</span></div>
          <ol><li className={draft ? "done" : "active"}>保存策略草稿</li><li className={task?.status === "SUCCEEDED" ? "done" : draft ? "active" : ""}>运行当前批次回放</li><li className={draft?.status === "approved" ? "done" : ""}>审批冻结参数</li><li className={draft?.status === "published" ? "done" : ""}>发布生效版本</li></ol>
          <button className="button primary" disabled={busy || Boolean(draft)} onClick={() => act(async () => { const result = await api.createRecoveryPolicyDraft(policy, config, `draft-${Date.now()}`); setDraft(result); setMessage(`草稿 v${result.version} 已保存`); })}><Save size={16} />保存草稿</button>
          <button className="button secondary" disabled={busy || !draft || Boolean(task)} onClick={() => act(async () => { const result = await api.replayRecoveryPolicy(draft!.id, dashboard.active_run.id, `replay-${draft!.id}-${Date.now()}`); setTask(result); setMessage(`回放完成：${String(result.evidence.group_count || 0)} 个保障组`); })}><Play size={16} />运行回放</button>
          <button className="button secondary" disabled={busy || !draft || task?.status !== "SUCCEEDED" || draft.status !== "draft"} onClick={() => act(async () => { const result = await api.approveRecoveryPolicy(draft!.id, task!.id); setDraft(result); setMessage("策略参数已冻结"); })}><ShieldCheck size={16} />审批冻结</button>
          <button className="button success" disabled={busy || draft?.status !== "approved"} onClick={() => act(async () => { const result = await api.publishRecoveryPolicy(draft!.id, policy.version); setDraft(result); setPolicy(result); setConfig(result.config); setMessage(`策略 v${result.version} 已发布`); })}>发布策略</button>
          {task && <div className="replay-evidence"><strong>{task.status}</strong><span>节点守恒：{task.evidence.node_conservation ? "通过" : "失败"}</span><span>历史回退：{String(task.evidence.historical_regressions || 0)}</span></div>}
          <p>恢复耗尽固定形成 UNASSIGNED_FINAL；合法终态不计入 unresolved，也不等待人工逐航班确认。</p>
        </aside>
      </div>
    </div>
  );
}

function RangeField({ label, unit, min, max, value, onChange }: { label: string; unit: string; min: number; max: number; value: number; onChange: (value: number) => void }) {
  return (
    <label className="range-field">
      <span>{label}<b>{value} {unit}</b></span>
      <input type="range" min={min} max={max} value={value} onChange={(event) => onChange(Number(event.target.value))} />
    </label>
  );
}

function clone(config: StrategyConfig): StrategyConfig {
  return JSON.parse(JSON.stringify(config)) as StrategyConfig;
}

function normalizeConfig(config: StrategyConfig): StrategyConfig {
  const copy = clone(config);
  delete (copy.weights as StrategyConfig["weights"] & { reference?: number }).reference;
  return {
    ...copy,
    sequence_resolution_enabled: copy.sequence_resolution_enabled ?? false,
    terminal_tail_reattach_enabled: copy.terminal_tail_reattach_enabled ?? false,
    terminal_tail_lookback_minutes: copy.terminal_tail_lookback_minutes ?? 480,
    terminal_tail_max_nodes: copy.terminal_tail_max_nodes ?? 3,
    terminal_tail_event_policy: copy.terminal_tail_event_policy ?? DEFAULT_TERMINAL_TAIL_EVENT_POLICY,
    combination_stand_families: copy.combination_stand_families ?? ["525"],
    combination_parent_guard_enabled: copy.combination_parent_guard_enabled ?? false,
    open_occupancy_timeout_minutes: copy.open_occupancy_timeout_minutes ?? 480,
    time_decay_minutes: copy.time_decay_minutes ?? 180,
    acdm_time_tolerance_minutes: copy.acdm_time_tolerance_minutes ?? 10,
    weights: {
      ...copy.weights,
      sequence_order: copy.weights.sequence_order ?? 40,
      appearance_registration: copy.weights.appearance_registration ?? 12
    }
  };
}

function weightLabel(key: string): string {
  const labels: Record<string, string> = { stand: "机位", time_window: "时间窗", node_semantics: "节点阶段", continuity: "连续性", sequence_order: "同机位顺序", appearance_airline: "外观航司", appearance_type: "外观机型", appearance_registration: "注册号OCR" };
  return labels[key] || key;
}
