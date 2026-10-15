import { describe, expect, it } from "vitest";
import { formatDate, formatDateTime, formatElapsed, formatMoney, formatNumber } from "./format";

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

describe("formatElapsed", () => {
  const now = new Date("2026-10-15T12:00:00Z");
  it.each([
    ["2026-10-15T11:59:30Z", "az önce"],
    ["2026-10-15T11:15:00Z", "45 dk"],
    ["2026-10-15T09:00:00Z", "3 sa"],
    ["2026-10-15T08:40:00Z", "3 sa 20 dk"],
    ["2026-10-13T08:00:00Z", "2 gün 4 sa"],
    ["2026-10-14T12:00:00Z", "1 gün"],
    ["2026-10-16T12:00:00Z", "az önce"],
  ])("%s → %s", (from, expected) => {
    expect(formatElapsed(from, now)).toBe(expected);
  });

  it("boş değerde boş metin", () => {
    expect(formatElapsed(null, now)).toBe("");
  });
});
