import { describe, expect, it } from "vitest";
import { codeOptions, withValue } from "./useStandardOptions";

describe("standart kod seçenekleri", () => {
  it("ülke ve dil kodlarına Türkçe adı yazar, ada göre sıralar", () => {
    expect(codeOptions(["TR", "DE", "IQ"], "region")).toEqual([
      { value: "DE", label: "Almanya (DE)" },
      { value: "IQ", label: "Irak (IQ)" },
      { value: "TR", label: "Türkiye (TR)" },
    ]);
    expect(codeOptions(["tr", "en"], "language")).toEqual([
      { value: "en", label: "İngilizce (en)" },
      { value: "tr", label: "Türkçe (tr)" },
    ]);
  });

  it("listede olmayan eski değeri seçeneklere ekler", () => {
    const options = codeOptions(["tr"], "language");
    expect(withValue(options, "tr")).toBe(options);
    expect(withValue(options, "tur")[0]).toEqual({ value: "tur", label: "tur" });
    expect(withValue(options, null)).toBe(options);
  });
});
