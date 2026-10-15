import { Badge } from "@mantine/core";
import type { ApprovalStatus, DecisionType, SampleStatus, SpecStatus } from "../../api/quality";
import { APPROVAL_COLOR, DECISION_COLOR, SAMPLE_STATUS_COLOR, SPEC_STATUS_COLOR } from "./config";
import { qt } from "./strings";

export function SampleStatusBadge({ status }: { status: SampleStatus }) {
  return (
    <Badge color={SAMPLE_STATUS_COLOR[status]} variant="light">
      {qt.sampleStatus[status]}
    </Badge>
  );
}

export function SpecStatusBadge({ status }: { status: SpecStatus }) {
  return (
    <Badge color={SPEC_STATUS_COLOR[status]} variant="light">
      {qt.specStatus[status]}
    </Badge>
  );
}

export function DecisionBadge({ decision }: { decision: DecisionType }) {
  return (
    <Badge color={DECISION_COLOR[decision]} variant="filled">
      {qt.decision[decision]}
    </Badge>
  );
}

export function ApprovalBadge({ status }: { status: ApprovalStatus }) {
  return (
    <Badge color={APPROVAL_COLOR[status]} variant="light">
      {qt.approval[status]}
    </Badge>
  );
}
