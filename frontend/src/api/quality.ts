// /api/v1/quality/* uç noktaları. Sınırlar ve sonuçlar metin olarak gelir ("7.5000").
import { api } from "./client";
import type { ListParams } from "./masterdata";
import type { Paginated } from "./types";

export type SampleStage = "INCOMING" | "IN_PROCESS" | "FINAL";
export type SampleStatus = "PENDING" | "IN_TEST" | "AWAITING_APPROVAL" | "DECIDED" | "CANCELLED";
export type SampleOrigin = "GOODS_RECEIPT" | "PRODUCTION" | "FILLING" | "MANUAL";
export type ResultType = "NUMERIC" | "PASS_FAIL" | "TEXT";
export type SpecStatus = "DRAFT" | "APPROVED" | "OBSOLETE";
export type DecisionType = "RELEASE" | "REJECT" | "REWORK" | "CONDITIONAL_RELEASE";
export type ApprovalStatus = "NOT_REQUIRED" | "PENDING" | "APPROVED" | "REFUSED";

export interface TestDefinition {
  id: number;
  code: string;
  name: string;
  result_type: ResultType;
  result_type_display: string;
  unit: string;
  method: string;
  decimal_places: number;
  is_active: boolean;
}

export interface SpecLine {
  id: number;
  specification: number;
  sequence: number;
  test: number;
  test_code: string;
  test_name: string;
  result_type: ResultType;
  unit: string;
  decimal_places: number;
  min_value: string | null;
  max_value: string | null;
  target_value: string | null;
  text_expected: string | null;
  is_mandatory: boolean;
}

export interface Specification {
  id: number;
  material: number;
  material_code: string;
  material_name: string;
  material_type: string;
  sample_stage: SampleStage;
  sample_stage_display: string;
  version_no: number;
  status: SpecStatus;
  status_display: string;
  change_note: string;
  copied_from: number | null;
  copied_from_no: number | null;
  approved_by_name: string | null;
  approved_at: string | null;
  obsoleted_at: string | null;
  created_by_name: string | null;
  created_at: string;
  line_count: number | null;
}

export interface SpecificationDetail extends Specification {
  lines: SpecLine[];
  is_editable: boolean;
}

export interface SpecLinePayload {
  test: number | null;
  min_value: string | null;
  max_value: string | null;
  target_value: string | null;
  text_expected: string;
  is_mandatory: boolean;
}

export interface Sample {
  id: number;
  number: string;
  status: SampleStatus;
  status_display: string;
  lot: number;
  lot_no: string;
  lot_status: string;
  material: number;
  material_code: string;
  material_name: string;
  material_type: string;
  stage: SampleStage;
  stage_display: string;
  origin: SampleOrigin;
  origin_display: string;
  specification: number | null;
  specification_label: string | null;
  taken_by: number | null;
  taken_by_name: string | null;
  /** Otomatik numunede ilk sonuç girilene kadar boş. */
  taken_at: string | null;
  retain_location: number | null;
  retain_location_code: string | null;
  note: string;
  decided_at: string | null;
  created_by_name: string | null;
  created_at: string;
  waiting_minutes: number | null;
}

export interface TestResult {
  id: number;
  spec_line: number;
  test_code: string;
  numeric_value: string | null;
  text_value: string;
  passed: boolean | null;
  is_within_spec: boolean;
  measured_by_name: string | null;
  measured_at: string;
  instrument: string;
  note: string;
  superseded_by: number | null;
  created_at: string;
}

export interface QualityDecision {
  id: number;
  sample: number;
  sample_number: string;
  lot_no: string;
  material_code: string;
  material_name: string;
  decision: DecisionType;
  decision_display: string;
  reason: string;
  decided_by_name: string | null;
  decided_at: string;
  release_location: number | null;
  release_location_code: string | null;
  approval_status: ApprovalStatus;
  approval_status_display: string;
  approved_by_name: string | null;
  approved_at: string | null;
  approval_note: string;
}

export interface SampleLine {
  line: SpecLine;
  current: TestResult | null;
  history: TestResult[];
}

export interface SampleDetail extends Sample {
  lines: SampleLine[];
  decisions: QualityDecision[];
  missing_tests: string[];
  out_of_spec_tests: string[];
  default_release_location: number | null;
  allowed_transitions: SampleStatus[];
  cancel_reason: string;
  coa_available: boolean;
}

export interface ResultInput {
  spec_line: number;
  numeric_value?: string | null;
  text_value?: string;
  passed?: boolean | null;
  instrument?: string;
  note?: string;
}

function clean(params: ListParams): ListParams {
  return Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== ""),
  );
}

async function get<T>(path: string, params: ListParams = {}): Promise<T> {
  const { data } = await api.get<T>(`/quality/${path}`, {
    params: clean(params),
    paramsSerializer: { indexes: null },
  });
  return data;
}

async function post<T>(path: string, body: object = {}): Promise<T> {
  const { data } = await api.post<T>(`/quality/${path}`, body);
  return data;
}

// --- spesifikasyon -------------------------------------------------------------------------

export function listSpecifications(params: ListParams = {}): Promise<Paginated<Specification>> {
  return get("specifications/", params);
}

export function getSpecification(id: number): Promise<SpecificationDetail> {
  return get(`specifications/${id}/`);
}

export function createSpecification(payload: {
  material: number;
  sample_stage: SampleStage;
  change_note: string;
}): Promise<SpecificationDetail> {
  return post("specifications/", payload);
}

export async function updateSpecification(
  id: number,
  payload: { change_note: string },
): Promise<SpecificationDetail> {
  const { data } = await api.patch<SpecificationDetail>(`/quality/specifications/${id}/`, payload);
  return data;
}

export function copySpecification(id: number, changeNote = ""): Promise<SpecificationDetail> {
  return post(`specifications/${id}/copy/`, { change_note: changeNote });
}

export function approveSpecification(id: number): Promise<SpecificationDetail> {
  return post(`specifications/${id}/approve/`);
}

export function addSpecLine(specId: number, payload: SpecLinePayload): Promise<SpecLine> {
  return post(`specifications/${specId}/lines/`, payload);
}

export async function updateSpecLine(id: number, payload: SpecLinePayload): Promise<SpecLine> {
  const { data } = await api.patch<SpecLine>(`/quality/specification-lines/${id}/`, payload);
  return data;
}

export async function removeSpecLine(id: number): Promise<void> {
  await api.delete(`/quality/specification-lines/${id}/`);
}

// --- numune --------------------------------------------------------------------------------

export function listSamples(params: ListParams = {}): Promise<Paginated<Sample>> {
  return get("samples/", params);
}

export function sampleQueue(params: ListParams = {}): Promise<Paginated<Sample>> {
  return get("samples/queue/", params);
}

export function getSample(id: number): Promise<SampleDetail> {
  return get(`samples/${id}/`);
}

export function createSample(payload: {
  lot: number;
  stage: SampleStage;
  note?: string;
}): Promise<SampleDetail> {
  return post("samples/", payload);
}

export function assignSpecification(id: number, specification: number): Promise<SampleDetail> {
  return post(`samples/${id}/assign-specification/`, { specification });
}

export function recordResult(id: number, input: ResultInput): Promise<SampleDetail> {
  return post(`samples/${id}/results/`, input);
}

export function decide(
  id: number,
  payload: { decision: DecisionType; reason: string; release_location: number | null },
): Promise<SampleDetail> {
  return post(`samples/${id}/decide/`, payload);
}

export function cancelSample(id: number, reason: string): Promise<SampleDetail> {
  return post(`samples/${id}/cancel/`, { reason });
}

export function coaUrl(id: number): string {
  return `/api/v1/quality/samples/${id}/coa.pdf`;
}

// --- karar ---------------------------------------------------------------------------------

export function listDecisions(params: ListParams = {}): Promise<Paginated<QualityDecision>> {
  return get("decisions/", params);
}

export function reviewDecision(
  id: number,
  approve: boolean,
  note: string,
): Promise<QualityDecision> {
  return post(`decisions/${id}/review/`, { approve, note });
}
