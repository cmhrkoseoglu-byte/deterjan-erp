import type { RecipeLine } from "../../api/recipes";

export type LineChange = "added" | "removed" | "changed" | "same";

export interface ComparedLine {
  key: string;
  material_code: string;
  material_name: string;
  left: RecipeLine | null;
  right: RecipeLine | null;
  change: LineChange;
}

function keyed(lines: readonly RecipeLine[]): Map<string, RecipeLine> {
  // Aynı malzeme sürümde birden fazla satırda olabilir (ör. iki aşamada eklenen su).
  const seen = new Map<number, number>();
  const result = new Map<string, RecipeLine>();
  for (const line of [...lines].sort((a, b) => a.sequence - b.sequence)) {
    const index = seen.get(line.material) ?? 0;
    seen.set(line.material, index + 1);
    result.set(`${line.material}#${index}`, line);
  }
  return result;
}

function same(a: RecipeLine, b: RecipeLine): boolean {
  return (
    Number(a.quantity) === Number(b.quantity) &&
    a.unit === b.unit &&
    Number(a.tolerance_pct) === Number(b.tolerance_pct) &&
    a.is_water === b.is_water &&
    a.instruction.trim() === b.instruction.trim()
  );
}

/** İki sürümün satırlarını malzeme bazında eşleştirir: eklenen, çıkarılan, değişen. */
export function compareLines(
  left: readonly RecipeLine[],
  right: readonly RecipeLine[],
): ComparedLine[] {
  const a = keyed(left);
  const b = keyed(right);
  const keys = [...a.keys(), ...[...b.keys()].filter((key) => !a.has(key))];
  return keys.map((key) => {
    const l = a.get(key) ?? null;
    const r = b.get(key) ?? null;
    const any = (l ?? r)!;
    let change: LineChange = "same";
    if (!l) change = "added";
    else if (!r) change = "removed";
    else if (!same(l, r)) change = "changed";
    return {
      key,
      material_code: any.material_code,
      material_name: any.material_name,
      left: l,
      right: r,
      change,
    };
  });
}
