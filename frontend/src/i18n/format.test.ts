import { describe, expect, it } from "vitest";
import { formatDate, formatDateTime, formatMoney, formatNumber } from "./format";

describe("formatNumber", () => {
  it("Türkçe binlik ve ondalık ayırıcı kullanır", () => {
    expect(formatNumber(1234.56)).toBe("1.234,56");
    expect(formatNumber(1234567.5, 2)).toBe("1.234.567,50");
  });

  it("API'den gelen Decimal metnini biçimler", () => {
    expect(formatNumber("1234.5600")).toBe("1.234,56");
    expect(formatNumber("0.1250", 4)).toBe("0,1250");
  });

  it("boş ya da geçersiz değerde boş metin döner", () => {
    expect(formatNumber(null)).toBe("");
    expect(formatNumber("")).toBe("");
    expect(formatNumber("abc")).toBe("");
  });
});

describe("formatMoney", () => {
  it("her zaman iki ondalık gösterir", () => {
    expect(formatMoney(1500)).toBe("1.500,00");
    expect(formatMoney("99.9", "TL")).toBe("99,90 TL");
  });
});

describe("formatDate", () => {
  it("gg.aa.yyyy biçimi kullanır", () => {
    expect(formatDate("2026-10-15")).toBe("15.10.2026");
  });

  it("zaman damgasını İstanbul saatine göre gösterir", () => {
    // UTC 22:30 → İstanbul (UTC+3) ertesi gün 01:30
    expect(formatDate("2026-10-15T22:30:00Z")).toBe("16.10.2026");
    expect(formatDateTime("2026-10-15T22:30:00Z")).toBe("16.10.2026 01:30");
  });

  it("boş değerde boş metin döner", () => {
    expect(formatDate(null)).toBe("");
    expect(formatDateTime(undefined)).toBe("");
  });
});
