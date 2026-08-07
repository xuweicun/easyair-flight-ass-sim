import { CircleAlert, CircleCheck, CircleHelp, CircleX, Layers3 } from "lucide-react";
import { statusLabel } from "../labels";

const statusClass: Record<string, string> = {
  MATCHED: "success",
  MATCHED_REFERENCE: "success",
  MATCHED_REFERENCE_NO_PLAN: "success",
  MATCHED_MANUAL: "success",
  MATCHED_RECOVERED: "success",
  RECOVERY_PENDING: "warning",
  NEEDS_REVIEW: "warning",
  UNASSIGNED: "neutral",
  UNASSIGNED_FINAL: "neutral",
  DATA_ERROR: "danger"
};

export function StatusBadge({ status }: { status: string }) {
  const Icon =
    status === "MATCHED" || status === "MATCHED_MANUAL" || status === "MATCHED_REFERENCE" || status === "MATCHED_REFERENCE_NO_PLAN" || status === "MATCHED_RECOVERED"
      ? CircleCheck
      : status === "NEEDS_REVIEW" || status === "RECOVERY_PENDING"
        ? CircleAlert
        : status === "DATA_ERROR"
          ? CircleX
          : status === "UNASSIGNED" || status === "UNASSIGNED_FINAL"
            ? Layers3
            : CircleHelp;
  return (
    <span className={`status-badge ${statusClass[status] || "neutral"}`}>
      <Icon size={14} aria-hidden="true" />
      {statusLabel(status)}
    </span>
  );
}
