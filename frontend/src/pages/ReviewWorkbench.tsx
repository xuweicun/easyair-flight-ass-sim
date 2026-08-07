import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  GitMerge,
  GitPullRequestArrow,
  Plane,
  RefreshCw,
  Save,
  ScanSearch,
  Split,
  Unlink
} from "lucide-react";
import { FlightTimeline } from "../components/FlightTimeline";
import { StatusBadge } from "../components/StatusBadge";
import { eventLabel } from "../eventLabels";
import { issueLabel, SCORE_LABELS, SOURCE_LABELS, statusLabel } from "../labels";
import type { AcdmValidationSummary, Candidate, Group, GroupDetail, RegressionCase } from "../types";

type ReviewInput = {
  verdict: string;
  error_type?: string;
  correct_flight_id?: number;
  correct_flight_no?: string;
  comment?: string;
};

type Props = {
  groups: Group[];
  detail: GroupDetail | null;
  regressionFocus: RegressionCase | null;
  busy: boolean;
  onSelect: (id: number) => void;
  onReview: (groupId: number, input: ReviewInput) => Promise<void>;
  onAppearance: (
    group: GroupDetail,
    airline: string,
    aircraftType: string,
    confidence: number,
    aircraftRegistration: string,
    registrationConfidence: number
  ) => Promise<void>;
  onAcdm: (group: GroupDetail, flightNo: string, entryTime: string, chockTime: string, releaseTime: string) => Promise<void>;
  onClearAcdm: (group: GroupDetail) => Promise<void>;
  onSampleAcdm: (limit: number) => Promise<void>;
  acdmValidation: AcdmValidationSummary | null;
  onSplit: (groupId: number, nodeId: number) => Promise<void>;
  onMerge: (groupIds: number[]) => Promise<void>;
  recoveryContext?: {
    groupId: number;
    requestWindowStart: string | null;
    requestWindowEnd: string | null;
  } | null;
  onReturnToRecovery?: () => void;
  readOnly?: boolean;
  navigationContext?: { originLabel: string; helpText: string } | null;
  onReturnToOrigin?: () => void;
};

export function ReviewWorkbench({
  groups,
  detail,
  regressionFocus,
  busy,
  onSelect,
  onReview,
  onAppearance,
  onAcdm,
  onClearAcdm,
  onSampleAcdm,
  acdmValidation,
  onSplit,
  onMerge,
  recoveryContext,
  onReturnToRecovery,
  readOnly = false,
  navigationContext,
  onReturnToOrigin
}: Props) {
  const [candidateId, setCandidateId] = useState<number | null>(null);
  const [errorType, setErrorType] = useState("flight_match_error");
  const [comment, setComment] = useState("");
  const [airline, setAirline] = useState("MU");
  const [aircraftType, setAircraftType] = useState("320");
  const [confidence, setConfidence] = useState(90);
  const [aircraftRegistration, setAircraftRegistration] = useState("");
  const [registrationConfidence, setRegistrationConfidence] = useState(85);
  const [acdmFlightNo, setAcdmFlightNo] = useState("");
  const [finalFlightNo, setFinalFlightNo] = useState("");
  const [acdmEntryTime, setAcdmEntryTime] = useState("");
  const [acdmChockTime, setAcdmChockTime] = useState("");
  const [acdmReleaseTime, setAcdmReleaseTime] = useState("");
  const [splitNodeId, setSplitNodeId] = useState<number | null>(null);
  const [mergeIds, setMergeIds] = useState<number[]>([]);
  const [showValidationSamples, setShowValidationSamples] = useState(true);

  useEffect(() => {
    const selectableCandidates = detail?.candidates.filter((candidate) => !candidate.excluded_reason) || [];
    const assignedCandidate = selectableCandidates.find(
      (candidate) => candidate.flight_plan.id === detail?.assigned_flight_id
    );
    setCandidateId(assignedCandidate?.flight_plan.id || selectableCandidates[0]?.flight_plan.id || null);
    setAirline(detail?.appearance?.airline || "MU");
    setAircraftType(detail?.appearance?.aircraft_type || "320");
    setConfidence(Math.round((detail?.appearance?.confidence || 0.9) * 100));
    setAircraftRegistration(detail?.appearance?.aircraft_registration || "");
    setRegistrationConfidence(Math.round((detail?.appearance?.registration_confidence || 0.85) * 100));
    setAcdmFlightNo(detail?.acdm_reference?.flight_no || firstFlightNumber(detail));
    setFinalFlightNo(finalAnswer(detail));
    setAcdmEntryTime(toLocalInput(detail?.acdm_reference?.aircraft_entry_time || eventTime(detail, "AircraftEntry") || detail?.observed_start));
    setAcdmChockTime(toLocalInput(detail?.acdm_reference?.chock_on_time || eventTime(detail, "PlaceChockEnd") || detail?.observed_start));
    setAcdmReleaseTime(toLocalInput(detail?.acdm_reference?.stand_release_time || terminalEventTime(detail) || detail?.observed_end));
    setSplitNodeId(null);
  }, [detail]);

  const currentIndex = detail ? groups.findIndex((group) => group.id === detail.id) : -1;
  const adjacent = useMemo(() => {
    if (!detail) return [];
    return groups.filter((group) => group.stand === detail.stand && group.id !== detail.id);
  }, [detail, groups]);
  const validationCodes = acdmValidation?.cases.map((item) => item.temporary_code) || [];
  const reviewGroups = showValidationSamples && validationCodes.length
    ? groups.filter((group) => validationCodes.includes(group.temporary_code))
    : groups;
  const nextValidationCase = acdmValidation?.cases.find(
    (item) => item.group_id !== detail?.id
      && item.group_id !== null
      && ["AWAITING_ACDM", "AWAITING_REVIEW"].includes(item.sample_status)
  );
  const comparison = reviewComparison(detail);
  const acdmTimeIssue = acdmTimeWarning(detail, acdmEntryTime, acdmChockTime);
  const validationCase = acdmValidation?.cases.find((item) => item.temporary_code === detail?.temporary_code);
  const structuralReplay = detail?.lineage.structural_review_replay;
  const selectableCandidates = detail?.candidates.filter((candidate) => !candidate.excluded_reason) || [];
  const excludedCandidateCount = (detail?.candidates.length || 0) - selectableCandidates.length;
  const selectedCandidate = selectableCandidates.find((candidate) => candidate.flight_plan.id === candidateId);
  const selectedPlan = selectedCandidate?.flight_plan;
  const relatedSegments = detail?.related_segments ?? [];
  const canConfirmStrategy = Boolean(detail && [
    "MATCHED",
    "MATCHED_REFERENCE",
    "MATCHED_REFERENCE_NO_PLAN",
    "MATCHED_MANUAL"
  ].includes(detail.assignment_status));

  if (!detail) {
    return <div className="empty-page"><RefreshCw size={24} />正在载入核验工作台</div>;
  }

  function toggleMerge(id: number) {
    setMergeIds((values) => values.includes(id) ? values.filter((value) => value !== id) : [...values, id]);
  }

  return (
    <div className={`review-layout ${readOnly ? "read-only" : ""}`}>
      <aside className="case-queue surface">
        <div className="queue-heading">
          <div><strong>{showValidationSamples && validationCodes.length ? "闭环核验样本" : "核验队列"}</strong><span>{reviewGroups.length} 组</span></div>
          {!readOnly && mergeIds.length >= 2 && (
            <button className="icon-button" aria-label="合并选中分组" onClick={() => onMerge(mergeIds)} disabled={busy}>
              <GitMerge size={17} />
            </button>
          )}
        </div>
        {!readOnly && <button
          className="button secondary sample-button"
          onClick={async () => {
            if (showValidationSamples && validationCodes.length >= 5) {
              setShowValidationSamples(false);
              return;
            }
            if (validationCodes.length < 5) await onSampleAcdm(5);
            setShowValidationSamples(true);
          }}
          disabled={busy}
        >
          <ScanSearch size={15} />{
            showValidationSamples && validationCodes.length >= 5
              ? "返回全部核验队列"
              : validationCodes.length
                ? "补足5组歧义样本"
                : "抽取5组歧义样本"
          }
        </button>}
        {acdmValidation && acdmValidation.total_cases > 0 && (
          <div className="validation-progress">
            <span>已录A-CDM（可选） <b>{acdmValidation.cases.filter((item) => item.acdm_flight_no).length}</b> / {acdmValidation.total_cases}</span>
            <span>已审核 <b>{acdmValidation.reviewed_cases}</b> / {acdmValidation.total_cases}</span>
            <span>审核错误 <b className={acdmValidation.review_errors ? "bad" : "ok"}>{acdmValidation.review_errors}</b></span>
            <span>A-CDM冲突 <b className={acdmValidation.acdm_conflicts ? "bad" : "ok"}>{acdmValidation.acdm_conflicts}</b></span>
            <span>基线错误 <b className={acdmValidation.baseline_error_count ? "bad" : "ok"}>{acdmValidation.baseline_error_count}</b></span>
            <span>A-CDM修复 <b className="ok">{acdmValidation.resolved_by_acdm_count}</b></span>
            <span>历史回退 <b className={acdmValidation.regression_count ? "bad" : "ok"}>{acdmValidation.regression_count}</b></span>
            {showValidationSamples && nextValidationCase?.group_id && (
              <button className="next-validation" onClick={() => onSelect(nextValidationCase.group_id!)}>
                下一待办<ArrowRight size={13} />
              </button>
            )}
          </div>
        )}
        <div className="queue-list">
          {reviewGroups.map((group) => {
            const sampleCase = acdmValidation?.cases.find((item) => item.group_id === group.id);
            return (
            <div className={`queue-item ${group.id === detail.id ? "selected" : ""}`} key={group.id}>
              {!readOnly && <label className="merge-check" title="选择相邻分组合并">
                <input
                  type="checkbox"
                  checked={mergeIds.includes(group.id)}
                  onChange={() => toggleMerge(group.id)}
                  disabled={group.stand !== detail.stand}
                />
              </label>}
              <button onClick={() => onSelect(group.id)}>
                <span><b>{group.stand}</b>{group.temporary_code.split("-").slice(-1)}</span>
                <small>{formatTime(group.observed_start)} · {group.node_count} 节点</small>
                {sampleCase
                  ? <em className={`sample-stage ${sampleCase.sample_status.toLowerCase()}`}>{sampleStatusLabel(sampleCase.sample_status)}</em>
                  : <i className={`queue-state ${group.review_status}`} />}
              </button>
            </div>
          );})}
        </div>
      </aside>

      <main className="workbench-main">
        {(navigationContext || recoveryContext) && (onReturnToOrigin || onReturnToRecovery) && (
          <section className="recovery-review-context">
            <button className="button secondary" onClick={onReturnToOrigin || onReturnToRecovery}><ArrowLeft size={16} />返回{navigationContext?.originLabel || "航班恢复队列"}</button>
            <div>
              <strong>{readOnly ? "Java影子结果图形查看" : "图形关联核验"}</strong>
              <span>{navigationContext?.helpText || "淡蓝区域是向航班总线查询计划的范围，不代表飞机一直占位；深绿色条才是算法节点形成的实际保障窗口。"}</span>
            </div>
          </section>
        )}
        {readOnly && <div className="readonly-notice"><ScanSearch size={17} /><span><strong>Java影子结果 / 只读</strong>候选、得分和节点归属来自 Java 不可变评估快照，本页不会提交人工答案或触发重跑。</span></div>}
        <div className="workbench-header">
          <div>
            <div className="eyebrow">{detail.temporary_code}</div>
            <h1>{detail.stand} 机位保障节点</h1>
          </div>
          <div className="workbench-status">
            <StatusBadge status={detail.assignment_status} />
            <span>置信度 {Math.round(detail.confidence * 100)}%</span>
            <span>领先 {detail.margin.toFixed(0)} 分</span>
          </div>
        </div>

        {regressionFocus && (
          <section className={`surface regression-focus ${regressionFocus.passed ? "passed" : "failed"}`}>
            <div><strong>历史人工结论复审</strong><span>来源运行 #{regressionFocus.source_run_id}</span></div>
            <div><span>历史正确结果</span><strong>{statusLabel(regressionFocus.expected_result)}</strong></div>
            <ArrowRight size={18} />
            <div><span>当前策略结果</span><strong>{statusLabel(regressionFocus.current_result)}</strong></div>
            <b>{regressionFocus.passed ? "通过" : "发生回退"}</b>
          </section>
        )}

        <section className="surface timeline-surface">
          <div className="section-heading compact">
            <div className="tag-list">
              {detail.issue_tags.map((issue) => <span className="issue-tag" key={issue}>{issueLabel(issue)}</span>)}
              {Boolean(structuralReplay) && <span className="issue-tag" title={structuralReplayTitle(structuralReplay)}>历史人工结论回放</span>}
            </div>
            <span>{formatFull(detail.observed_start)} - {formatFull(detail.observed_end)}</span>
          </div>
          <FlightTimeline
            group={detail}
            selectedFlightPlanId={candidateId}
            recoveryWindow={recoveryContext?.requestWindowStart && recoveryContext.requestWindowEnd
              ? { start: recoveryContext.requestWindowStart, end: recoveryContext.requestWindowEnd }
              : null}
          />
        </section>

        {selectedPlan && (
          <section className="surface attribution-preview">
            <div className="section-heading">
              <h2>节点航班归属</h2>
              <span>当前机位按航空器连续，节点按航段拆分</span>
            </div>
            <div className="current-flight-split">
              <div><span>进港阶段</span><strong>{selectedPlan.inbound_flight_no || "待确认"}</strong><small>{detail.nodes.filter((node) => node.phase === "ARRIVAL").length} 条节点</small></div>
              <ArrowRight size={18} />
              <div><span>过站准备与离港阶段</span><strong>{selectedPlan.outbound_flight_no || "待确认"}</strong><small>{detail.nodes.filter((node) => node.phase !== "ARRIVAL").length} 条节点</small></div>
            </div>
            {candidateId === detail.assigned_flight_id && relatedSegments.length > 0 && (
              <div className="related-flight-chain">
                <strong>关联航班链</strong>
                <span>{new Set(relatedSegments.map((segment) => segment.stand)).size} 个机位 · {new Set(relatedSegments.map((segment) => segment.aircraft_no).filter(Boolean)).size} 架飞机 · {new Set(relatedSegments.map((segment) => segment.flight_no)).size} 个航班</span>
                <div>
                  {relatedSegments.map((segment) => (
                    <span className={segment.current_group ? "current" : "linked"} key={`${segment.group_id}-${segment.phase}-${segment.flight_no}`}>
                      <b>{segment.phase === "ARRIVAL" ? "进港" : "出港"} {segment.flight_no}</b>
                      {segment.stand} / {segment.aircraft_no || "飞机未知"} · {segment.node_count} 节点
                    </span>
                  ))}
                </div>
              </div>
            )}
          </section>
        )}

        <div className="detail-grid">
          <section className="surface">
            <div className="section-heading"><h2>节点链</h2><span>{detail.nodes.length} 条</span></div>
            <div className="node-list">
              {detail.nodes.map((node, index) => (
                <div className="node-row" key={node.id}>
                  <span className={`source-mark ${node.source_type}`} />
                  <div><strong title={node.event_type}>{eventLabel(node.event_type)}</strong><small>{SOURCE_LABELS[node.source_type] || node.source_type}</small></div>
                  <span className={`node-flight phase-${node.phase.toLowerCase()}`}>
                    {node.phase === "ARRIVAL" ? "进" : "出"} {node.phase === "ARRIVAL" ? selectedPlan?.inbound_flight_no || "待确认" : selectedPlan?.outbound_flight_no || "待确认"}
                  </span>
                  <time>{node.event_time ? formatTime(node.event_time) : "时间异常"}</time>
                  {!readOnly && index > 0 && (
                    <button
                      className={`icon-button ${splitNodeId === node.id ? "active" : ""}`}
                      aria-label={`在 ${eventLabel(node.event_type)} 前拆分`}
                      onClick={() => setSplitNodeId(node.id)}
                    >
                      <Split size={15} />
                    </button>
                  )}
                </div>
              ))}
            </div>
            {!readOnly && splitNodeId && (
              <div className="inline-confirm">
                <span>将在节点 #{splitNodeId} 前拆分</span>
                <button className="button secondary" disabled={busy} onClick={() => onSplit(detail.id, splitNodeId)}>
                  <GitPullRequestArrow size={16} />确认拆分
                </button>
              </div>
            )}
          </section>

          <section className="surface">
            <div className="section-heading"><h2>候选评分</h2><span>{selectableCandidates.length} 个可选{excludedCandidateCount > 0 ? ` · ${excludedCandidateCount} 个已排除` : ""}</span></div>
            <div className="candidate-list">
              {detail.candidates.length === 0 && <div className="empty-state compact">没有可信航班计划</div>}
              {detail.candidates.map((candidate) => {
                const plan = candidate.flight_plan;
                const excluded = Boolean(candidate.excluded_reason);
                const selected = !excluded && candidateId === plan.id;
                const sequence = sequenceEvidence(detail, plan.id);
                const acdmEvidence = detail.acdm_reference ? acdmAuxiliaryEvidence(detail, candidate) : null;
                return (
                  <label className={`candidate-row ${selected ? "selected" : ""} ${excluded ? "excluded" : ""}`} key={candidate.id}>
                    <input type="radio" name="candidate" checked={selected} disabled={excluded} onChange={() => setCandidateId(plan.id)} />
                    <div className="candidate-main">
                      <div className="candidate-title"><strong><span>进 {plan.inbound_flight_no || "待确认"}</span><ArrowRight size={13} /><span>出 {plan.outbound_flight_no || "待确认"}</span></strong><b>{candidate.score.toFixed(0)}分</b></div>
                      <span>{plan.airline || "航司未知"} · {plan.aircraft_type || "机型未知"} · {plan.aircraft_no || "注册号未知"}</span>
                      <div className="score-bars">
                        {Object.entries(candidate.score_breakdown).filter(([key]) => key !== "registration_similarity").map(([key, value]) => (
                          <span key={key} title={`${SCORE_LABELS[key] || key}: ${value}`}>
                            <i className={value < 0 ? "negative" : ""} style={{ width: `${Math.min(100, Math.abs(value) * 3)}%` }} />
                          </span>
                        ))}
                      </div>
                      <div className="score-breakdown-text">
                        {Object.entries(candidate.score_breakdown).map(([key, value]) => (
                          <span key={key}>{scoreEvidenceLabel(key, value)}</span>
                        ))}
                      </div>
                      <div className="candidate-evidence">
                        {excluded && <span className="candidate-excluded-reason">已排除：{candidate.excluded_reason}</span>}
                        {acdmEvidence && (
                          <span className={acdmEvidence.className}>{acdmEvidence.label}</span>
                        )}
                        <span>{timeOffsetLabel(detail.observed_start, plan.plan_start, "开始")}</span>
                        <span>{timeOffsetLabel(detail.observed_end, plan.plan_end, "结束")}</span>
                        {sequence && <span className={sequence.state === "applied" ? "positive" : "warning"}>{sequence.label}</span>}
                      </div>
                    </div>
                  </label>
                );
              })}
            </div>
          </section>
        </div>
      </main>

      {readOnly ? <aside className="evidence-panel surface readonly-evidence-panel">
        <div className="section-heading"><h2>Java影子判定</h2><StatusBadge status={detail.assignment_status} /></div>
        <div className="readonly-panel-copy"><ScanSearch size={17} /><span><strong>只读快照</strong>此处只显示 Java 影子链路在评估时保存的候选和节点归属，不作为当前生产权威结果。</span></div>
        <div className="recovery-detail-grid">
          <div><span>当前状态</span><strong>{statusLabel(detail.assignment_status)}</strong></div>
          <div><span>节点数量</span><strong>{detail.nodes.length}</strong></div>
          <div><span>最高候选</span><strong>{selectedPlan ? `${selectedPlan.inbound_flight_no || "待确认"} / ${selectedPlan.outbound_flight_no || "待确认"}` : "无可靠候选"}</strong></div>
          <div><span>候选数量</span><strong>{selectableCandidates.length}</strong></div>
        </div>
        <div className="panel-foot">需要人工试验或修正时，请切换回“仿真数据”。</div>
      </aside> : <aside className="evidence-panel surface">
        <div className="section-heading"><h2>人工核验</h2><span>{currentIndex + 1}/{groups.length}</span></div>
        {validationCase && (
          <div className="acdm-time-warning ready">
            {validationCase.review_verdict
              ? "闭环答案已提交，可在对比区查看策略结论"
              : detail.acdm_reference
                ? "已加入A-CDM对照证据，可核对并提交最终答案"
                : "可直接提交最终答案；A-CDM为可选对照证据"}
          </div>
        )}
        <div className="decision-actions">
          <button
            className="button success"
            disabled={busy || !canConfirmStrategy}
            title={canConfirmStrategy ? "确认当前策略结果" : "当前策略尚未形成明确航班，请提交最终航班号或保留无航班号"}
            onClick={() => onReview(detail.id, { verdict: "correct", comment })}
          >
            <Check size={17} />匹配正确
          </button>
          <button className="button secondary" disabled={busy} onClick={() => onReview(detail.id, { verdict: "unassigned", comment })}>
            <Unlink size={17} />保留无航班号
          </button>
        </div>
        {comparison && (
          <div className={`review-comparison ${comparison.strategyCorrect ? "correct" : "incorrect"}`}>
            <strong>{comparison.strategyCorrect ? "本轮策略匹配正确" : "本轮策略匹配错误，已进入回归集"}</strong>
            <span>{comparison.acdmText}</span>
          </div>
        )}
        {validationCase?.review_verdict && (
          <div className="three-way-comparison">
            <div><span>录入前基线</span><strong>{validationCase.baseline_flight_no || statusLabel(validationCase.baseline_status || "UNASSIGNED")}</strong></div>
            <div><span>{validationCase.acdm_flight_no ? "加入A-CDM后" : "当前策略"}</span><strong>{validationCase.current_flight_no || "未关联计划"}</strong></div>
            <div><span>最终人工答案</span><strong>{validationCase.final_flight_no || statusLabel(validationCase.final_status || "UNASSIGNED")}</strong></div>
          </div>
        )}
        <label>
          问题类型
          <select value={errorType} onChange={(event) => setErrorType(event.target.value)}>
            <option value="flight_match_error">航班匹配错误</option>
            <option value="grouping_error">节点分组错误</option>
            <option value="reference_error">参考数据错误</option>
            <option value="appearance_error">外观特征错误</option>
            <option value="source_data_error">原始节点异常</option>
          </select>
        </label>
        <label>
          核验说明
          <textarea rows={3} value={comment} onChange={(event) => setComment(event.target.value)} placeholder="记录判断依据" />
        </label>
        <label>
          最终正确航班号
          <input
            list="candidate-flight-numbers"
            value={finalFlightNo}
            onChange={(event) => setFinalFlightNo(event.target.value.toUpperCase())}
            placeholder="独立于A-CDM上报值，由人工最终确认"
          />
        </label>
        <button
          className="button danger"
          disabled={busy || !finalFlightNo.trim()}
          onClick={() => {
            const selected = detail.candidates.find((candidate) => candidate.flight_plan.id === candidateId);
            const planNumbers = selected ? [selected.flight_plan.inbound_flight_no, selected.flight_plan.outbound_flight_no].filter(Boolean).map((value) => value!.toUpperCase()) : [];
            const answerFlightNo = finalFlightNo.trim().toUpperCase();
            onReview(detail.id, {
              verdict: "incorrect",
              error_type: errorType,
              correct_flight_id: planNumbers.includes(answerFlightNo) ? candidateId || undefined : undefined,
              correct_flight_no: answerFlightNo,
              comment
            });
          }}
        >
          <Save size={17} />提交最终审核航班号
        </button>

        <div className="panel-divider" />
        <div className="section-heading"><h2>外观识别模拟</h2><ScanSearch size={18} /></div>
        <label>
          所属航司
          <select value={airline} onChange={(event) => setAirline(event.target.value)}>
            <option value="MU">东方航空 MU</option>
            <option value="CZ">南方航空 CZ</option>
            <option value="CA">中国国航 CA</option>
            <option value="HU">海南航空 HU</option>
            <option value="3U">四川航空 3U</option>
            <option value="GS">天津航空 GS</option>
          </select>
        </label>
        <label>
          机型
          <select value={aircraftType} onChange={(event) => setAircraftType(event.target.value)}>
            <option value="319">A319</option>
            <option value="320">A320</option>
            <option value="321">A321</option>
            <option value="738">B737-800</option>
            <option value="190">E190</option>
          </select>
        </label>
        <label>
          识别置信度 <b>{confidence}%</b>
          <input type="range" min="50" max="99" value={confidence} onChange={(event) => setConfidence(Number(event.target.value))} />
        </label>
        <label>
          飞机注册号（OCR模拟）
          <input
            value={aircraftRegistration}
            onChange={(event) => setAircraftRegistration(event.target.value.toUpperCase())}
            placeholder="例如 B-533"
          />
        </label>
        <label>
          注册号OCR置信度 <b>{registrationConfidence}%</b>
          <input type="range" min="30" max="99" value={registrationConfidence} onChange={(event) => setRegistrationConfidence(Number(event.target.value))} />
        </label>
        <button className="button primary" disabled={busy} onClick={() => onAppearance(
          detail,
          airline,
          aircraftType,
          confidence / 100,
          aircraftRegistration,
          registrationConfidence / 100
        )}>
          <Plane size={17} />写入特征并重跑
        </button>

        <div className="panel-divider" />
        <div className="section-heading"><h2>A-CDM现场填报模拟</h2><ScanSearch size={18} /></div>
        <label>
          上报航班号
          <input list="candidate-flight-numbers" value={acdmFlightNo} onChange={(event) => setAcdmFlightNo(event.target.value.toUpperCase())} placeholder="可录入计划中不存在的航班号" />
          <datalist id="candidate-flight-numbers">
            {candidateFlightNumbers(detail).map((flightNo) => <option value={flightNo} key={flightNo} />)}
          </datalist>
        </label>
        <label>
          飞机入位时间
          <input type="datetime-local" value={acdmEntryTime} onChange={(event) => setAcdmEntryTime(event.target.value)} />
        </label>
        <label>
          上轮挡时间
          <input type="datetime-local" value={acdmChockTime} onChange={(event) => setAcdmChockTime(event.target.value)} />
        </label>
        <label>
          人工释放机位时间（算法无结束节点时兜底）
          <input type="datetime-local" value={acdmReleaseTime} onChange={(event) => setAcdmReleaseTime(event.target.value)} />
        </label>
        {acdmTimeIssue && <div className="acdm-time-warning">{acdmTimeIssue}；航班号仍按可靠锚点处理</div>}
        {detail.acdm_reference && <div className="panel-foot">当前仿真证据：{detail.acdm_reference.flight_no}</div>}
        <button
          className="button primary"
          disabled={busy || !acdmFlightNo || !acdmEntryTime}
          onClick={() => onAcdm(detail, acdmFlightNo, acdmEntryTime, acdmChockTime, acdmReleaseTime)}
        >
          <Save size={17} />写入A-CDM证据并重跑
        </button>
        {detail.acdm_reference && (
          <button className="button secondary" disabled={busy} onClick={() => onClearAcdm(detail)}>
            <Unlink size={17} />清除A-CDM证据
          </button>
        )}

        {adjacent.length > 0 && <div className="panel-foot">同机位另有 {adjacent.length} 个分组可合并核验</div>}
      </aside>}
    </div>
  );
}

function scoreEvidenceLabel(key: string, value: number): string {
  if (key === "registration_similarity") return `注册号相似度 ${Math.round(value * 100)}%`;
  return `${SCORE_LABELS[key] || key} ${value.toFixed(0)}`;
}

function acdmAuxiliaryEvidence(detail: GroupDetail, candidate: Candidate): { label: string; className: string } {
  const acdmFlightNo = detail.acdm_reference?.flight_no.toUpperCase();
  const planNumbers = [candidate.flight_plan.inbound_flight_no, candidate.flight_plan.outbound_flight_no]
    .map((value) => value?.toUpperCase())
    .filter((value): value is string => Boolean(value));
  if (!acdmFlightNo || !planNumbers.includes(acdmFlightNo)) {
    return { label: "A-CDM辅助：航班号不一致", className: "warning" };
  }
  if (candidate.flight_plan.stand !== detail.stand) {
    return { label: "A-CDM辅助：航班号一致，机位不一致", className: "warning" };
  }
  return { label: "A-CDM辅助：航班号一致", className: "positive" };
}

function candidateFlightNumbers(detail: GroupDetail): string[] {
  return [...new Set(detail.candidates.flatMap((candidate) => [
    candidate.flight_plan.inbound_flight_no,
    candidate.flight_plan.outbound_flight_no
  ]).filter((value): value is string => Boolean(value)))];
}

function firstFlightNumber(detail: GroupDetail | null): string {
  return detail ? candidateFlightNumbers(detail)[0] || "" : "";
}

function finalAnswer(detail: GroupDetail | null): string {
  if (!detail) return "";
  const review = detail.reviews[detail.reviews.length - 1];
  return review?.expected_flight_no || detail.acdm_reference?.flight_no || firstFlightNumber(detail);
}

function sampleStatusLabel(status: string): string {
  return {
    AWAITING_ACDM: "待核验",
    AWAITING_REVIEW: "待核验",
    NEEDS_STRATEGY_FIX: "策略待修正",
    REGRESSION: "发生回退",
    VALIDATED: "已通过"
  }[status] || status;
}

function eventTime(detail: GroupDetail | null, eventType: string): string | null {
  return detail?.nodes.find((node) => node.event_type === eventType)?.event_time || null;
}

function toLocalInput(value: string | undefined | null): string {
  if (!value) return "";
  const date = new Date(value);
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function acdmTimeWarning(detail: GroupDetail | null, entryValue: string, chockValue: string): string | null {
  if (!detail || !entryValue || !chockValue) return null;
  const entry = new Date(entryValue).getTime();
  const chock = new Date(chockValue).getTime();
  if (chock < entry) return "人工中间节点存在轻微错序，已忽略其边界作用；飞机入位仍作为占位开始";
  const observedStart = new Date(detail.observed_start).getTime();
  const maxOffset = Math.max(Math.abs(entry - observedStart), Math.abs(chock - observedStart)) / 60_000;
  return maxOffset > 10 ? `人工中间节点与算法时间相差约${Math.round(maxOffset)}分钟，仅作为补充` : null;
}

function terminalEventTime(detail: GroupDetail | null): string | null {
  const terminal = detail?.nodes
    .filter((node) => node.event_time && ["AircraftLeave", "TowEnd"].includes(node.event_type))
    .sort((left, right) => new Date(right.event_time!).getTime() - new Date(left.event_time!).getTime())[0];
  return terminal?.event_time || null;
}

function timeOffsetLabel(observed: string, planned: string | null, label: string): string {
  if (!planned) return `${label}偏差 --`;
  const minutes = Math.round((new Date(observed).getTime() - new Date(planned).getTime()) / 60_000);
  if (minutes === 0) return `${label}偏差 0分钟`;
  return `${label}偏差 ${minutes > 0 ? "晚" : "早"}${Math.abs(minutes)}分钟`;
}

function sequenceEvidence(detail: GroupDetail, planId: number): { state: string; label: string } | null {
  const raw = detail.lineage.sequence_resolution;
  if (!raw || typeof raw !== "object") return null;
  const evidence = raw as Record<string, unknown>;
  if (evidence.expected_flight_plan_id !== planId) return null;
  if (evidence.state === "applied") {
    return {
      state: "applied",
      label: "顺序命中：前序锚点后的下一保障组 / 下一航班计划，时间有重叠"
    };
  }
  if (evidence.state === "rejected_no_time_overlap") {
    return { state: "rejected", label: "顺序未采用：计划窗口与节点时间无重叠" };
  }
  return null;
}

function reviewComparison(detail: GroupDetail | null): { strategyCorrect: boolean; acdmText: string } | null {
  if (!detail) return null;
  const raw = detail.lineage.latest_review_comparison;
  if (!raw || typeof raw !== "object") return null;
  const comparison = raw as Record<string, unknown>;
  const acdmText = comparison.acdm_flight_no
    ? `A-CDM航班号 ${comparison.acdm_flight_no} 与最终审核${comparison.acdm_matches_final ? "一致" : "不一致"}`
    : "本轮未使用A-CDM现场数据";
  return { strategyCorrect: comparison.strategy_correct === true, acdmText };
}

function structuralReplayTitle(value: unknown): string {
  if (!value || typeof value !== "object") return "";
  const replay = value as Record<string, unknown>;
  return `来源：${String(replay.source_temporary_code || "历史分组")}；依据：节点集合完全一致`;
}

function formatTime(value: string): string {
  return new Date(value).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function formatFull(value: string): string {
  return new Date(value).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}
