import { describe, expect, it } from "vitest";
import type { RecipeLine } from "../../api/recipes";
import { compareLines } from "./compare";

let nextId = 1;
function line(material: number, quantity: string, extra: Partial<RecipeLine> = {}): RecipeLine {
  return {
    id: nextId++,
    version: 1,
    sequence: nextId,
    material,
    material_code: `M${material}`,
    material_name: `Malzeme ${material}`,
    quantity,
    unit: 1,
    unit_code: "KG",
    tolerance_pct: "2.00",
    instruction: "",
    is_water: false,
    ...extra,
  };
}

describe("sürüm karşılaştırma", () => {
  it("eklenen, çıkarılan, değişen ve aynı satırları bulur", () => {
    const left = [line(1, "100.0000"), line(2, "5.0000"), line(3, "1.0000")];
    const right = [line(1, "100"), line(2, "6.0000"), line(4, "2.0000")];

    const result = compareLines(left, right).map((row) => [row.material_code, row.change]);

    expect(result).toEqual([
      ["M1", "same"],
      ["M2", "changed"],
      ["M3", "removed"],
      ["M4", "added"],
    ]);
  });

  it("aynı malzemenin iki satırını ayrı eşleştirir", () => {
    const left = [line(9, "300", { sequence: 1 }), line(9, "200", { sequence: 5 })];
    const right = [line(9, "300", { sequence: 1 })];

    expect(compareLines(left, right).map((row) => row.change)).toEqual(["same", "removed"]);
  });

  it("tolerans değişikliğini fark sayar", () => {
    const [row] = compareLines([line(1, "1")], [line(1, "1", { tolerance_pct: "1.00" })]);
    expect(row.change).toBe("changed");
  });
});
