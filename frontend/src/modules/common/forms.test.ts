import { describe, expect, it } from "vitest";
import { normalizeDecimal, toFormValues, toPayload, trimDecimal, type FieldDef } from "./forms";

const fields: FieldDef[] = [
  { name: "code", label: "Kod", type: "text" },
  { name: "density", label: "Yoğunluk", type: "decimal" },
  { name: "shelf_life_days", label: "Raf ömrü", type: "integer" },
  { name: "base_unit", label: "Birim", type: "relation" },
  { name: "is_hazardous", label: "Tehlikeli", type: "checkbox" },
];

describe("form yardımcıları", () => {
  it("Türkçe ondalık girişini API biçimine çevirir", () => {
    expect(normalizeDecimal("1,05")).toBe("1.05");
    expect(normalizeDecimal("1.234,5")).toBe("1234.5");
    expect(normalizeDecimal(" 12.5 ")).toBe("12.5");
  });

  it("API ondalığındaki gereksiz sıfırları atar", () => {
    expect(trimDecimal("12.5000")).toBe("12.5");
    expect(trimDecimal("1000.0000")).toBe("1000");
    expect(trimDecimal("7")).toBe("7");
  });

  it("kaydı form değerlerine ve form değerlerini gövdeye çevirir", () => {
    const values = toFormValues(fields, {
      code: "HM-1",
      density: "1.0500",
      shelf_life_days: null,
      base_unit: 3,
      is_hazardous: true,
    });
    expect(values).toEqual({
      code: "HM-1",
      density: "1.05",
      shelf_life_days: "",
      base_unit: "3",
      is_hazardous: true,
    });

    expect(toPayload(fields, { ...values, density: "1,1", shelf_life_days: "" })).toEqual({
      code: "HM-1",
      density: "1.1",
      shelf_life_days: null,
      base_unit: 3,
      is_hazardous: true,
    });
  });

  it("yeni kayıtta varsayılanları kullanır", () => {
    expect(toFormValues(fields, null, { is_hazardous: true, code: "X" })).toMatchObject({
      code: "X",
      is_hazardous: true,
      density: "",
    });
  });
});
