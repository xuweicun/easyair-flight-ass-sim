import { ArrowRight, CheckCircle2, Download, LockKeyhole, RefreshCw, ShieldCheck, XCircle } from "lucide-react";
import { API_BASE } from "../api";
import { statusLabel } from "../labels";
import type { Acceptance, AcdmValidationSummary, Dashboard, RegressionCase } from "../types";

type Props = {
  dashboard: Dashboard;
  acceptance: Acceptance;
  acdmValidation: AcdmValidationSummary | null;
  busy: boolean;
  onPublish: () => Promise<void>;
  onRerun: () => Promise<void>;
  onOpenGroup: (groupId: number, regressionCase?: RegressionCase) => void;
};

export function AcceptanceCenter({ dashboard, acceptance, acdmValidation, busy, onPublish, onRerun, onOpenGroup }: Props) {
  const regressionCases = acceptance.regression_cases ?? [];
  const reviewPercent = acceptance.required_reviews
    ? Math.round((acceptance.completed_reviews / acceptance.required_reviews) * 100)
    : 100;
  const closedLoopReady = Boolean(
    acdmValidation
    && acdmValidation.total_cases > 0
    && acdmValidation.pending_cases === 0
    && acdmValidation.review_errors === 0
    && acdmValidation.acdm_conflicts === 0
    && acdmValidation.regression_count === 0
    && acceptance.node_conservation
  );
  return (
    <div className="page-stack">
      <div className="page-heading">
        <div><h1>验收中心</h1><p>{dashboard.strategy.name} · 运行 #{acceptance.run_id}</p></div>
        <div className="heading-actions">
          <button className="button secondary" disabled={busy} onClick={onRerun}><RefreshCw size={17} />重跑当前策略</button>
          <button className="button primary" disabled={!acceptance.can_publish || dashboard.strategy.status === "published" || busy} onClick={onPublish}>
            <ShieldCheck size={17} />{dashboard.strategy.status === "published" ? "当前版本已发布" : "发布策略版本"}
          </button>
        </div>
      </div>

      <div className="metric-grid three">
        <div className="metric-card"><span>必审案例</span><strong>{acceptance.completed_reviews}/{acceptance.required_reviews}</strong><small>完成度 {reviewPercent}%</small></div>
        <div className="metric-card"><span>人工指出问题</span><strong className={acceptance.incorrect_reviews ? "danger-text" : "success-text"}>{acceptance.incorrect_reviews}</strong><small>发布要求为 0</small></div>
        <div className="metric-card"><span>节点守恒</span><strong className={acceptance.node_conservation ? "success-text" : "danger-text"}>{acceptance.node_conservation ? "通过" : "失败"}</strong><small>{dashboard.active_run.metrics.accounted_nodes}/{dashboard.active_run.metrics.total_nodes} 条</small></div>
      </div>

      <section className="surface gate-panel">
        <div className="section-heading">
          <div><h2>A-CDM 人机闭环验收</h2><span>仅针对已选歧义样本，不替代全量发布门禁</span></div>
          <span className={`status-dot ${closedLoopReady ? "ready" : "blocked"}`}>{closedLoopReady ? "闭环通过" : "等待审核"}</span>
        </div>
        <GateRow
          passed={Boolean(acdmValidation && acdmValidation.pending_cases === 0 && acdmValidation.total_cases > 0)}
          label="已选样本全部提交最终答案"
          detail={acdmValidation ? `${acdmValidation.reviewed_cases}/${acdmValidation.total_cases}` : "0/0"}
        />
        <GateRow passed={(acdmValidation?.review_errors || 0) === 0} label="最终审核无未修正错误" detail={`${acdmValidation?.review_errors || 0} 个`} />
        <GateRow passed={(acdmValidation?.acdm_conflicts || 0) === 0} label="A-CDM航班号与最终答案一致" detail={`${acdmValidation?.acdm_conflicts || 0} 个冲突`} />
        <GateRow passed={(acdmValidation?.regression_count || 0) === 0} label="当前策略无闭环回退" detail={`${acdmValidation?.regression_count || 0} 个回退`} />

        {acdmValidation && acdmValidation.cases.length > 0 && (
          <table className="data-table acdm-acceptance-table">
            <thead><tr><th>保障组</th><th>A-CDM航班号</th><th>录入前</th><th>当前策略</th><th>最终答案</th><th>状态</th></tr></thead>
            <tbody>
              {acdmValidation.cases.map((item) => (
                <tr key={item.temporary_code}>
                  <td><span className="group-code" title={item.temporary_code}>{item.temporary_code}</span></td>
                  <td><strong>{item.acdm_flight_no || "待录入"}</strong></td>
                  <td>{item.baseline_flight_no || item.baseline_status || "未关联"}</td>
                  <td>{item.current_flight_no || "未关联计划"}</td>
                  <td>{item.final_flight_no || "待人工提交"}</td>
                  <td>
                    {item.review_verdict
                      ? <span className={`table-status ${item.current_strategy_correct === false ? "danger" : "ok"}`}>
                          {item.is_regression ? "发生回退" : item.current_strategy_correct === false ? "仍需修正" : item.review_verdict === "incorrect" ? "已修复" : "已核验"}
                        </span>
                      : item.group_id && <button className="button secondary compact-button" onClick={() => onOpenGroup(item.group_id!)}>
                          {item.sample_status === "AWAITING_ACDM" ? "录入A-CDM" : "提交答案"}<ArrowRight size={14} />
                        </button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <div className="acceptance-grid">
        <section className="surface gate-panel">
          <div className="section-heading"><h2>全量策略发布门禁</h2><span className={`status-dot ${acceptance.can_publish ? "ready" : "blocked"}`}>{acceptance.can_publish ? "已通过" : "未通过"}</span></div>
          <GateRow passed={acceptance.completed_reviews >= acceptance.required_reviews} label="必审问题全部核验" detail={`${acceptance.completed_reviews}/${acceptance.required_reviews}`} />
          <GateRow passed={acceptance.incorrect_reviews === 0} label="本轮无人工指出问题" detail={`${acceptance.incorrect_reviews} 个错误`} />
          <GateRow passed={acceptance.regression_count === 0} label="历史正确案例无回退" detail={`${acceptance.regression_count} 个回退`} />
          <GateRow passed={acceptance.node_conservation} label="节点数量守恒" detail={`${dashboard.active_run.metrics.accounted_nodes} 条已归组`} />
          {!acceptance.can_publish && (
            <div className="blocker-list">
              <LockKeyhole size={17} />
              <div>{acceptance.blockers.map((blocker) => <span key={blocker}>{blocker}</span>)}</div>
            </div>
          )}
        </section>

        <section className="surface export-panel">
          <div className="section-heading"><h2>无航班号数据包</h2><span>预览与导出</span></div>
          <div className="payload-preview">
            <code>assignment_status</code><strong>UNASSIGNED</strong>
            <code>flight_no</code><strong>null</strong>
            <code>safeguard_code</code><strong>null</strong>
            <code>temporary_group_id</code><strong>TMP-XIY-...</strong>
          </div>
          <div className="export-actions">
            <a className="button secondary" href={`${API_BASE}/api/runs/${acceptance.run_id}/exports/unassigned.json`} target="_blank" rel="noreferrer"><Download size={16} />导出 JSON</a>
            <a className="button secondary" href={`${API_BASE}/api/runs/${acceptance.run_id}/exports/unassigned.xlsx`}><Download size={16} />导出 Excel</a>
          </div>
        </section>
      </div>

      <section className="surface regression-panel">
        <div className="section-heading"><h2>固定回归案例</h2><span>{regressionCases.length} 条历史人工结论 · 策略发布前必须全部通过</span></div>
        {regressionCases.length ? (
          <table className="data-table interactive-table">
            <thead><tr><th>保障组</th><th>机位</th><th>历史正确结果</th><th>当前策略结果</th><th>状态</th></tr></thead>
            <tbody>
              {regressionCases.map((item) => (
                <tr key={`${item.source_run_id}-${item.temporary_code}`} onClick={() => item.current_group_id && onOpenGroup(item.current_group_id, item)}>
                  <td><span className="group-code" title={item.temporary_code}>{item.temporary_code}</span><small>来源运行 #{item.source_run_id}</small></td>
                  <td>{item.stand}</td>
                  <td><strong>{displayRegressionResult(item.expected_result)}</strong></td>
                  <td>{displayRegressionResult(item.current_result)}</td>
                  <td><span className={`table-status ${item.passed ? "ok" : "danger"}`}>{item.passed ? "通过" : "发生回退"}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <div className="empty-state compact">提交并重跑首个人工最终答案后，将自动形成固定回归案例</div>}
      </section>
    </div>
  );
}

function GateRow({ passed, label, detail }: { passed: boolean; label: string; detail: string }) {
  const Icon = passed ? CheckCircle2 : XCircle;
  return <div className={`gate-row ${passed ? "passed" : "failed"}`}><Icon size={20} /><strong>{label}</strong><span>{detail}</span></div>;
}

function displayRegressionResult(value: string): string {
  return statusLabel(value) || value;
}
