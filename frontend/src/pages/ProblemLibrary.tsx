import { useMemo, useState } from "react";
import { ArrowRight, Filter, Search } from "lucide-react";
import { issueLabel } from "../labels";
import { StatusBadge } from "../components/StatusBadge";
import type { Group } from "../types";

type Props = {
  groups: Group[];
  onSelect: (id: number) => void;
};

export function ProblemLibrary({ groups, onSelect }: Props) {
  const [query, setQuery] = useState("");
  const [issue, setIssue] = useState("ALL");
  const issues = useMemo(
    () => Array.from(new Set(groups.flatMap((group) => group.issue_tags))).sort(),
    [groups]
  );
  const filtered = groups.filter((group) => {
    const matchesIssue = issue === "ALL" || group.issue_tags.includes(issue);
    const text = `${group.temporary_code} ${group.stand}`.toLowerCase();
    return matchesIssue && text.includes(query.toLowerCase());
  });

  return (
    <div className="page-stack">
      <div className="page-heading">
        <div>
          <h1>问题航班库</h1>
          <p>{groups.filter((group) => group.issue_tags.length > 0).length} 个问题分组 · 历史错例持续保留</p>
        </div>
      </div>
      <div className="filter-bar">
        <label className="search-control">
          <Search size={17} aria-hidden="true" />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="临时组编号或机位" />
        </label>
        <label className="select-control">
          <Filter size={17} aria-hidden="true" />
          <select value={issue} onChange={(event) => setIssue(event.target.value)}>
            <option value="ALL">全部问题类型</option>
            {issues.map((value) => <option value={value} key={value}>{issueLabel(value)}</option>)}
          </select>
        </label>
      </div>
      <section className="surface table-surface">
        <table className="data-table interactive-table">
          <thead>
            <tr><th>临时航班组</th><th>机位</th><th>观测窗口</th><th>节点</th><th>问题</th><th>结果</th><th>核验</th><th /></tr>
          </thead>
          <tbody>
            {filtered.map((group) => (
              <tr key={group.id} onClick={() => onSelect(group.id)}>
                <td><strong>{group.temporary_code}</strong></td>
                <td>{group.stand}</td>
                <td>{formatTime(group.observed_start)} - {formatTime(group.observed_end)}</td>
                <td>{group.node_count}</td>
                <td>
                  <div className="tag-list">
                    {group.issue_tags.slice(0, 2).map((tag) => <span className="issue-tag" key={tag}>{issueLabel(tag)}</span>)}
                    {group.issue_tags.length > 2 && <span className="issue-tag muted">+{group.issue_tags.length - 2}</span>}
                  </div>
                </td>
                <td><StatusBadge status={group.assignment_status} /></td>
                <td><span className={`review-state ${group.review_status}`}>{reviewLabel(group.review_status)}</span></td>
                <td><button className="icon-button" aria-label={`核验 ${group.temporary_code}`}><ArrowRight size={17} /></button></td>
              </tr>
            ))}
          </tbody>
        </table>
        {!filtered.length && <div className="empty-state">没有符合条件的问题分组</div>}
      </section>
    </div>
  );
}

function formatTime(value: string): string {
  return new Date(value).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function reviewLabel(value: string): string {
  return value === "pending" ? "未核验" : value === "correct" ? "已确认" : value === "incorrect" ? "有问题" : "已处置";
}

