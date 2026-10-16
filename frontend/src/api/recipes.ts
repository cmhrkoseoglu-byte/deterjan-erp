// /api/v1/recipes/* uç noktaları.
import { api } from "./client";
import type { ImportReport } from "./masterdata";
import type { Paginated } from "./types";

export type VersionStatus = "DRAFT" | "APPROVED" | "OBSOLETE";

export interface Recipe {
  id: number;
  code: string;
  name: string;
  product: number;
  product_code: string;
  product_name: string;
  notes: string;
  approved_version: { id: number; version_no: number } | null;
  latest_version_no: number | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface RecipeLine {
  id: number;
  version: number;
  sequence: number;
  material: number;
  material_code: string;
  material_name: string;
  quantity: string;
  unit: number;
  unit_code: string;
  tolerance_pct: string;
  instruction: string;
  is_water: boolean;
}

export interface RecipeStep {
  id: number;
  version: number;
  sequence: number;
  description: string;
  duration_min: number | null;
  temperature_c: string | null;
  mixer_rpm: number | null;
}

export interface RecipeVersion {
  id: number;
  recipe: number;
  recipe_code: string;
  recipe_name: string;
  product: number;
  version_no: number;
  status: VersionStatus;
  status_display: string;
  batch_size: string;
  batch_unit: number;
  batch_unit_code: string;
  change_note: string;
  copied_from: number | null;
  copied_from_no: number | null;
  approved_by: number | null;
  approved_by_name: string | null;
  approved_at: string | null;
  obsoleted_at: string | null;
  created_at: string;
  created_by_name: string | null;
  updated_at: string;
}

export interface RecipeVersionDetail extends RecipeVersion {
  lines: RecipeLine[];
  steps: RecipeStep[];
  can_edit: boolean;
  can_approve: boolean;
}

export interface ScaledRequirement {
  sequence: number;
  line: number;
  material: number;
  material_code: string;
  material_name: string;
  quantity: string;
  unit: number;
  unit_code: string;
  tolerance_pct: string;
  is_water: boolean;
}

export type LinePayload = Partial<
  Pick<
    RecipeLine,
    "sequence" | "material" | "quantity" | "unit" | "tolerance_pct" | "instruction" | "is_water"
  >
>;
export type StepPayload = Partial<
  Pick<RecipeStep, "sequence" | "description" | "duration_min" | "temperature_c" | "mixer_rpm">
>;

export async function listRecipes(params: Record<string, unknown>): Promise<Paginated<Recipe>> {
  const { data } = await api.get<Paginated<Recipe>>("/recipes/recipes/", { params });
  return data;
}

export async function getRecipe(id: number): Promise<Recipe> {
  const { data } = await api.get<Recipe>(`/recipes/recipes/${id}/`);
  return data;
}

export async function saveRecipe(
  id: number | null,
  payload: Record<string, unknown>,
): Promise<Recipe> {
  const { data } = id
    ? await api.patch<Recipe>(`/recipes/recipes/${id}/`, payload)
    : await api.post<Recipe>("/recipes/recipes/", payload);
  return data;
}

export async function setRecipeActive(id: number, active: boolean): Promise<Recipe> {
  const { data } = await api.post<Recipe>(
    `/recipes/recipes/${id}/${active ? "activate" : "deactivate"}/`,
  );
  return data;
}

export async function listVersions(recipeId: number): Promise<RecipeVersion[]> {
  const { data } = await api.get<RecipeVersion[]>(`/recipes/recipes/${recipeId}/versions/`);
  return data;
}

export async function createVersion(
  recipeId: number,
  payload: { batch_size: string; batch_unit: number; change_note: string },
): Promise<RecipeVersionDetail> {
  const { data } = await api.post<RecipeVersionDetail>(
    `/recipes/recipes/${recipeId}/versions/`,
    payload,
  );
  return data;
}

export async function getVersion(id: number): Promise<RecipeVersionDetail> {
  const { data } = await api.get<RecipeVersionDetail>(`/recipes/versions/${id}/`);
  return data;
}

export async function updateVersion(
  id: number,
  payload: Partial<Pick<RecipeVersion, "batch_size" | "batch_unit" | "change_note">>,
): Promise<RecipeVersionDetail> {
  const { data } = await api.patch<RecipeVersionDetail>(`/recipes/versions/${id}/`, payload);
  return data;
}

export async function copyVersion(id: number, note: string): Promise<RecipeVersionDetail> {
  const { data } = await api.post<RecipeVersionDetail>(`/recipes/versions/${id}/copy/`, { note });
  return data;
}

export async function approveVersion(id: number, note: string): Promise<RecipeVersionDetail> {
  const { data } = await api.post<RecipeVersionDetail>(`/recipes/versions/${id}/approve/`, {
    note,
  });
  return data;
}

export async function scaleVersion(
  id: number,
  qty: string,
  unit: string,
): Promise<ScaledRequirement[]> {
  const { data } = await api.get<ScaledRequirement[]>(`/recipes/versions/${id}/scale/`, {
    params: { qty, unit },
  });
  return data;
}

export async function addLine(versionId: number, payload: LinePayload): Promise<RecipeLine> {
  const { data } = await api.post<RecipeLine>(`/recipes/versions/${versionId}/lines/`, payload);
  return data;
}

export async function updateLine(id: number, payload: LinePayload): Promise<RecipeLine> {
  const { data } = await api.patch<RecipeLine>(`/recipes/lines/${id}/`, payload);
  return data;
}

export async function removeLine(id: number): Promise<void> {
  await api.delete(`/recipes/lines/${id}/`);
}

export async function addStep(versionId: number, payload: StepPayload): Promise<RecipeStep> {
  const { data } = await api.post<RecipeStep>(`/recipes/versions/${versionId}/steps/`, payload);
  return data;
}

export async function updateStep(id: number, payload: StepPayload): Promise<RecipeStep> {
  const { data } = await api.patch<RecipeStep>(`/recipes/steps/${id}/`, payload);
  return data;
}

export async function removeStep(id: number): Promise<void> {
  await api.delete(`/recipes/steps/${id}/`);
}

// --- Excel'den içe aktarma (Faz 5, Adım 5.6) ------------------------------------------------

/** Her reçeteye yeni taslak sürüm açar; `confirm=false` önizleme. Hatalıysa 400 + `report`. */
export async function uploadRecipeImport(file: File, confirm: boolean): Promise<ImportReport> {
  const body = new FormData();
  body.append("file", file);
  body.append("confirm", confirm ? "true" : "false");
  const { data } = await api.post<ImportReport>("/recipes/import/", body);
  return data;
}

export const RECIPE_TEMPLATE_URL = "/api/v1/recipes/import/template/";
