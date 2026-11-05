import { describe, expect, it } from "vitest";
import { optionLabel } from "./useOptions";

describe("seçim kutusu etiketi", () => {
  it("kodu değişmiş kayıtta eski kodları da yazar", () => {
    expect(optionLabel({ code: "MLZ-0000001", name: "LAS" })).toBe("MLZ-0000001 - LAS");
    expect(optionLabel({ code: "MLZ-0000001", name: "LAS", former_codes: [] })).toBe(
      "MLZ-0000001 - LAS",
    );
    expect(
      optionLabel({ code: "MLZ-0000001", name: "LAS", former_codes: ["HM-LAS", "LAS-1"] }),
    ).toBe("MLZ-0000001 - LAS (eski: HM-LAS, LAS-1)");
  });

  it("ek bilgi addan sonra, eski kodlar en sonda yazar; kod adla aynıysa bir kez yazar", () => {
    expect(
      optionLabel({ code: "REC-0000001", name: "Bulaşık", former_codes: ["3645"] }, " (v2)"),
    ).toBe("REC-0000001 - Bulaşık (v2) (eski: 3645)");
    expect(optionLabel({ code: "KG", name: "KG" })).toBe("KG");
  });
});
