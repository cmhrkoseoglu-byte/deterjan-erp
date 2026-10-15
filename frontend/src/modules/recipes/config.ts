import type { Role } from "../../api/types";
import type { FieldDef } from "../common/forms";
import { rt } from "./strings";

// Reçeteyi planlama ve laboratuvar yazar (admin her yere erişir); backend: apps/recipes/api/views.py.
export const RECIPE_WRITE_ROLES: Role[] = ["planlama", "laboratuvar"];
export const RECIPES_BASE = "/receteler";

export const recipeFields: FieldDef[] = [
  { name: "code", label: "Kod", type: "text", required: true },
  { name: "name", label: "Ad", type: "text", required: true },
  {
    name: "product",
    label: rt.product,
    type: "relation",
    required: true,
    relation: { endpoint: "materials", params: { material_type: "BULK" } },
    wide: true,
    description: "Reçeteyle üretilen yarı mamul. Sürüm açıldıktan sonra değiştirilemez.",
  },
  { name: "notes", label: rt.notes, type: "textarea" },
];

export const versionFields: FieldDef[] = [
  { name: "batch_size", label: rt.batch, type: "decimal", required: true },
  {
    name: "batch_unit",
    label: rt.batchUnit,
    type: "relation",
    required: true,
    relation: { endpoint: "units" },
  },
  { name: "change_note", label: rt.changeNote, type: "textarea" },
];

export const lineFields: FieldDef[] = [
  {
    name: "material",
    label: rt.material,
    type: "relation",
    required: true,
    relation: { endpoint: "materials", params: { material_type__in: "RAW,BULK" } },
    wide: true,
  },
  { name: "quantity", label: rt.quantity, type: "decimal", required: true },
  {
    name: "unit",
    label: rt.unit,
    type: "relation",
    required: true,
    relation: { endpoint: "units" },
  },
  { name: "tolerance_pct", label: rt.tolerance, type: "decimal" },
  {
    name: "sequence",
    label: rt.sequence,
    type: "integer",
    description: "Boş bırakılırsa sona eklenir",
  },
  { name: "is_water", label: rt.water, type: "checkbox", description: rt.waterHint, wide: true },
  { name: "instruction", label: rt.instruction, type: "textarea" },
];

export const stepFields: FieldDef[] = [
  { name: "description", label: rt.description, type: "textarea", required: true },
  { name: "duration_min", label: rt.duration, type: "integer" },
  { name: "temperature_c", label: rt.temperature, type: "decimal" },
  { name: "mixer_rpm", label: rt.rpm, type: "integer" },
  {
    name: "sequence",
    label: rt.sequence,
    type: "integer",
    description: "Boş bırakılırsa sona eklenir",
  },
];
