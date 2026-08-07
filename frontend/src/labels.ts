export const ISSUE_LABELS: Record<string, string> = {
  AMBIGUOUS_MATCH: "多候选冲突",
  MISSING_PLAN: "计划缺失",
  LONG_WINDOW: "时间窗超长",
  INVALID_YEAR: "异常年份",
  INVALID_TIME_ORDER: "起止倒置",
  MISSING_PLAN_TIME: "计划时间缺失",
  MISSING_STAND: "机位缺失",
  MISSING_SAFEGUARD_CODE: "保障编码缺失",
  CROSS_STAND_CODE: "保障编码跨机位重复",
  COMBINATION_STAND_CONFLICT: "组合机位占用冲突",
  OCCUPANCY_FLIGHT_CONFLICT: "同一驻位航段冲突",
  OVERLAP: "计划重叠",
  INCOMPLETE_SEQUENCE: "节点链不完整",
  REFERENCE_CONFLICT: "参考航班冲突",
  NODE_DATA_ERROR: "节点数据异常",
  MANUAL_SPLIT: "人工拆分",
  MANUAL_MERGE: "人工合并",
  PLAN_END_OVERRUN: "实际结束晚于计划",
  ORPHAN_START_MARKER: "边界孤立开始节点",
  ACDM_TIME_OUTLIER: "A-CDM时间偏差过大",
  ACDM_PLAN_MISSING: "A-CDM航班无对应计划",
  ACDM_FLIGHT_AMBIGUOUS: "A-CDM航班计划不唯一",
  ACDM_NODE_ORDER_ANOMALY: "A-CDM中间节点轻微错序",
  INCOMPLETE_FRAGMENT: "低信息片段",
  DEGRADED: "降级保留",
  TERMINAL_TAIL_REATTACHED: "结束节点已回接",
  PARENT_STAND_CODE_WITHOUT_PLAN: "主机位号无对应计划",
  PARENT_STAND_PLAN_CONFLICT: "主机位计划与左右机位占用冲突"
};

export const STATUS_LABELS: Record<string, string> = {
  MATCHED: "自动匹配",
  MATCHED_REFERENCE: "A-CDM确认",
  MATCHED_REFERENCE_NO_PLAN: "A-CDM确认·计划缺失",
  MATCHED_MANUAL: "人工匹配",
  NEEDS_REVIEW: "待核验",
  UNASSIGNED: "无航班号",
  UNASSIGNED_FINAL: "最终无航班号",
  RECOVERY_PENDING: "计划恢复中",
  MATCHED_RECOVERED: "恢复后匹配",
  DATA_ERROR: "数据异常",
  SUPERSEDED: "已被替代"
};

export const SOURCE_LABELS: Record<string, string> = {
  algorithm_node: "算法",
  manual_report: "A-CDM现场填报",
  acdm_reference: "A-CDM",
  acdm_simulation: "A-CDM仿真"
};

export const SCORE_LABELS: Record<string, string> = {
  stand: "机位一致",
  time_window: "可信时间窗",
  node_semantics: "节点阶段",
  continuity: "链路连续",
  sequence_order: "同机位顺序",
  appearance_airline: "航司外观",
  appearance_type: "机型外观",
  appearance_registration: "注册号OCR",
  registration_similarity: "注册号相似度"
};

export function issueLabel(issue: string): string {
  return ISSUE_LABELS[issue] || issue;
}

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] || status;
}
