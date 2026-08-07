import { useRef, useState } from "react";
import { FileSpreadsheet, Play, UploadCloud } from "lucide-react";
import type { Dashboard } from "../types";

type Props = {
  dashboard: Dashboard;
  busy: boolean;
  onImport: (form: FormData) => Promise<void>;
};

const historicalIssues = [
  ["超长时间窗", "long_windows", 868],
  ["无候选节点", "no_candidate_nodes", 4815],
  ["多候选节点", "multi_candidate_nodes", 840],
  ["保障编码缺失", "missing_safeguard_code", 225],
  ["异常年份", "invalid_year_rows", 24],
  ["计划重叠", "overlap_pairs", 60]
] as const;

export function BatchCenter({ dashboard, busy, onImport }: Props) {
  const formRef = useRef<HTMLFormElement>(null);
  const [showImport, setShowImport] = useState(false);
  const stats = dashboard.batch.stats;
  const max = Math.max(...historicalIssues.map(([, key, fallback]) => stats[key] || fallback));

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onImport(new FormData(event.currentTarget));
    formRef.current?.reset();
    setShowImport(false);
  }

  return (
    <div className="page-stack">
      <div className="page-heading">
        <div>
          <h1>批次中心</h1>
          <p>{dashboard.batch.name} · {dashboard.batch.airport_code}</p>
        </div>
        <button className="button primary" onClick={() => setShowImport((value) => !value)}>
          <UploadCloud size={17} aria-hidden="true" />
          导入验证批次
        </button>
      </div>

      {showImport && (
        <form className="import-panel surface" ref={formRef} onSubmit={submit}>
          <div className="form-row">
            <label>
              批次名称
              <input name="name" defaultValue="西安机场验证批次" required />
            </label>
            <label>
              机场代码
              <input name="airport_code" defaultValue="XIY" required />
            </label>
          </div>
          <div className="file-grid">
            <label className="file-field">
              <FileSpreadsheet size={20} aria-hidden="true" />
              <span>航班计划 Excel</span>
              <input name="plan_file" type="file" accept=".xlsx" required />
            </label>
            <label className="file-field">
              <FileSpreadsheet size={20} aria-hidden="true" />
              <span>算法节点 Excel</span>
              <input name="node_file" type="file" accept=".xlsx" required />
            </label>
            <label className="file-field">
              <FileSpreadsheet size={20} aria-hidden="true" />
              <span>A-CDM现场节点 Excel（可选）</span>
              <input name="acdm_file" type="file" accept=".xlsx" />
            </label>
          </div>
          <div className="form-actions">
            <button type="button" className="button secondary" onClick={() => setShowImport(false)}>
              取消
            </button>
            <button className="button primary" disabled={busy}>
              <Play size={16} aria-hidden="true" />
              {busy ? "解析并运行中" : "导入并运行基线"}
            </button>
          </div>
        </form>
      )}

      <div className="metric-grid three">
        <div className="metric-card">
          <span>历史航班计划</span>
          <strong>{(stats.historical_plan_rows || stats.plan_groups || 0).toLocaleString()}</strong>
          <small>计划记录</small>
        </div>
        <div className="metric-card">
          <span>历史节点数据</span>
          <strong>{(stats.historical_node_rows || stats.nodes || 0).toLocaleString()}</strong>
          <small>算法与A-CDM现场节点</small>
        </div>
        <div className="metric-card">
          <span>当前仿真分组</span>
          <strong>{dashboard.active_run.metrics.group_count}</strong>
          <small>{dashboard.active_run.metrics.accounted_nodes} 条节点已归组</small>
        </div>
      </div>

      <section className="surface analysis-grid">
        <div className="section-heading">
          <div>
            <h2>历史问题数据画像</h2>
            <span>2026-06-01 至 06-22</span>
          </div>
        </div>
        <div className="horizontal-bars" role="img" aria-label="历史航班计划和节点问题数量">
          {historicalIssues.map(([label, key, fallback]) => {
            const value = stats[key] || fallback;
            return (
              <div className="bar-row" key={key}>
                <span>{label}</span>
                <div className="bar-track">
                  <i style={{ width: `${Math.max(2, (value / max) * 100)}%` }} />
                </div>
                <strong>{value.toLocaleString()}</strong>
              </div>
            );
          })}
        </div>
      </section>

      <section className="surface">
        <div className="section-heading">
          <h2>当前批次数据源</h2>
          <span className="status-dot ready">就绪</span>
        </div>
        <table className="data-table">
          <thead>
            <tr><th>数据源</th><th>状态</th><th>记录</th><th>用途</th></tr>
          </thead>
          <tbody>
            <tr><td>航班计划</td><td><span className="table-status ok">已载入</span></td><td>{stats.plan_groups || 10}</td><td>候选航班窗口</td></tr>
            <tr><td>算法节点</td><td><span className="table-status ok">已载入</span></td><td>{stats.nodes || 32}</td><td>聚类与匹配</td></tr>
            <tr><td>A-CDM现场节点</td><td><span className={`table-status ${stats.acdm_nodes ? "ok" : "muted"}`}>{stats.acdm_nodes ? "已导入" : "未提供"}</span></td><td>{stats.acdm_nodes || "-"}</td><td>现场填报与航班号证据</td></tr>
            <tr><td>A-CDM仿真</td><td><span className="table-status warning">可模拟</span></td><td>按保障组</td><td>验证缺失、一致与冲突场景</td></tr>
            <tr><td>外观识别</td><td><span className="table-status warning">人工模拟</span></td><td>按分组</td><td>航司/机型消歧</td></tr>
          </tbody>
        </table>
      </section>
    </div>
  );
}
