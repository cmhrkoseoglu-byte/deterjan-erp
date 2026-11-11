import { describe, expect, it } from "vitest";
import { ALLOWED, MISSING, entryErrors, type Allowed } from "./allowlist";
import { loadBaseline } from "./snapshot";

// İzin listesinin kendisi (plan §5.5, §10): her kayıt planın bir maddesine ve dondurulmuş bir
// hücreye bağlıdır (backend'deki test_allowlist.py'nin karşılığı).

/** Hata satırı "<kayıt> [persona]: <neden>" biçimindedir. */
function reasons(errors: string[]): string[] {
  return errors.map((error) => error.slice(error.indexOf("]: ") + 3));
}

describe("izin listesi", () => {
  it("her kayıt planın bir maddesine ve dondurulmuş bir hücreye bağlıdır", async () => {
    const baseline = await loadBaseline();
    expect(baseline).not.toBeNull();
    expect(entryErrors(ALLOWED, baseline ?? {})).toEqual([]);
  });

  it("bağlanamayan kayıtları yakalar", () => {
    const baseline = { menu: { hse: { no_role: true, depo: true } } };
    const good: Allowed = {
      item: "§8 madde 1",
      section: "menu",
      case: "hse",
      persona: "no_role",
      old: true,
      new: false,
      step: 8,
    };
    const page: Allowed = {
      item: "yeni sayfa: Yetkilerim",
      section: "menu",
      case: "yetkilerim",
      old: MISSING,
      step: 9,
    };
    const planned = { "yeni sayfa: Yetkilerim": [9] };
    expect(entryErrors([good, page], baseline, 1, planned)).toEqual([]);

    const bad: Allowed[] = [
      { ...good, step: 7 },
      { ...good, item: "§8 madde 99" },
      { ...good, item: "plan dışı" },
      { ...good, section: "yok" },
      { ...good, case: "reporting" },
      { ...good, old: false, new: true },
      { ...page, case: "hse" },
      { ...good, new: true },
      { ...good, until: 7 },
      { ...page, step: 8 },
      { ...good, old: null, new: false },
    ];
    expect(reasons(entryErrors(bad, baseline, 1, planned))).toEqual([
      "madde 1 [8]. adımda açılır, kayıt 7. adımda.",
      "§8'de böyle bir madde yok.",
      "planın bir maddesine bağlı değil.",
      "böyle bir bölüm yok.",
      "anlık görüntüde eşleşen hücre yok.",
      "eşleşen hücrelerin hiçbirinde eski değer false değil.",
      "yeni durum diye yazılmış, anlık görüntüde 2 hücre var.",
      "eski ve yeni değer aynı.",
      "son adım (7) ilk adımdan (8) önce.",
      "planın eklediği kayıt [9]. adımda açılır, kayıt 8. adımda.",
      "eşleşen hücrelerin hiçbirinde eski değer null değil.",
    ]);
  });

  it("adımı açılan kaydın yeni değeri sabitlenmelidir", () => {
    const baseline = { menu: { hse: { no_role: true } } };
    const open: Allowed = {
      item: "§8 madde 1",
      section: "menu",
      case: "hse",
      persona: "no_role",
      old: true,
      step: 8,
    };
    expect(entryErrors([open], baseline, 7)).toEqual([]);
    expect(reasons(entryErrors([open], baseline, 8))).toEqual([
      "adımı açıldı; yeni değer gözlenen değere sabitlenmeli (daraltmak onay istemez).",
    ]);
    expect(entryErrors([{ ...open, new: false }], baseline, 8)).toEqual([]);
    expect(entryErrors([{ ...open, until: 8 }], baseline, 9)).toEqual([]);
  });
});
