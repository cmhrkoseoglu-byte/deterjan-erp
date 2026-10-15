import { describe, expect, it } from "vitest";
import type { SpecLine } from "../../api/quality";
import { limitText, numericOutOfSpec } from "./limits";

function line(overrides: Partial<SpecLine> = {}): SpecLine {
  return {
    id: 1,
    specification: 1,
    sequence: 1,
    test: 1,
    test_code: "PH",
    test_name: "pH",
    result_type: "NUMERIC",
    unit: "",
    decimal_places: 2,
    min_value: "6.0000",
    max_value: "8.0000",
    target_value: null,
    text_expected: null,
    is_mandatory: true,
    ...overrides,
  };
}

describe("spesifikasyon sınırları", () => {
  it("sınır metnini Türkçe biçimler", () => {
    expect(limitText(line())).toBe("6,00 – 8,00");
    expect(limitText(line({ max_value: null, unit: "%" }))).toBe("≥ 6,00 %");
    expect(limitText(line({ min_value: null, decimal_places: 0, unit: "cP" }))).toBe("≤ 8 cP");
    expect(limitText(line({ result_type: "TEXT", text_expected: "Berrak" }))).toBe("Berrak");
    expect(limitText(line({ result_type: "PASS_FAIL" }))).toBe("Uygun");
  });

  it("girilen değeri sınırlarla karşılaştırır (sınırlar dahil)", () => {
    expect(numericOutOfSpec(line(), "")).toBeNull();
    expect(numericOutOfSpec(line(), "abc")).toBeNull();
    expect(numericOutOfSpec(line(), "6")).toBe(false);
    expect(numericOutOfSpec(line(), "8,0")).toBe(false);
    expect(numericOutOfSpec(line(), "8,01")).toBe(true);
    expect(numericOutOfSpec(line(), "5.9")).toBe(true);
    expect(numericOutOfSpec(line({ result_type: "TEXT" }), "9")).toBeNull();
  });
});
