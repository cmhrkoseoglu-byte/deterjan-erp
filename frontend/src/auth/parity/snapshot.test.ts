import { describe, expect, it } from "vitest";
import { ANY, MISSING, matches, permitted, type Allowed } from "./allowlist";
import { compareSection, differences } from "./snapshot";

// Eşlik anlık görüntüsü aracının kendisi: fark bulma ve izin listesi (backend'deki
// test_snapshot_tool.py'nin karşılığı).

describe("eşlik anlık görüntüsü aracı", () => {
  it("değişen değeri persona sırasıyla bildirir", () => {
    const { unexpected, permitted: allowed } = differences(
      "menu",
      { hse: { superuser: true, no_role: true, depo: true } },
      { hse: { superuser: false, no_role: false, depo: true } },
      [],
    );
    expect(unexpected).toEqual([
      "menu › hse [no_role]: true → false",
      "menu › hse [superuser]: true → false",
    ]);
    expect(allowed).toEqual([]);
  });

  it("kaybolan ve yeni gelen durumları bildirir; nesne anahtarlarının sırası önemsiz", () => {
    const { unexpected } = differences(
      "routes",
      { "/eski": { depo: "open" }, "/ayni": { depo: { a: 1, b: 2 } } },
      { "/yeni": { depo: "open" }, "/ayni": { depo: { b: 2, a: 1 } } },
      [],
    );
    expect(unexpected).toEqual([
      `routes › /eski [depo]: open → ${MISSING}`,
      `routes › /yeni [depo]: ${MISSING} → open`,
    ]);
  });

  it("izin listesi yalnız bölümü, deseni, personayı ve değerleri tutan farka izin verir", () => {
    const rule: Allowed = {
      item: "§8 madde 1",
      section: "menu",
      case: "h?e",
      persona: "no_*",
      old: true,
      new: false,
    };
    const { unexpected, permitted: allowed } = differences(
      "menu",
      { hse: { no_role: true, depo: true }, reporting: { no_role: true } },
      { hse: { no_role: false, depo: false }, reporting: { no_role: false } },
      [rule],
    );
    expect(allowed).toEqual(["menu › hse [no_role]: true → false (§8 madde 1)"]);
    expect(unexpected).toEqual([
      "menu › hse [depo]: true → false",
      "menu › reporting [no_role]: true → false",
    ]);
    expect(permitted("routes", "hse", "no_role", true, false, [rule])).toBeUndefined();
    expect(permitted("menu", "hse", "no_role", true, true, [rule])).toBeUndefined();
    // Verilmeyen ya da ANY olan değer ve persona her değeri kabul eder.
    const loose: Allowed = { item: "§8 madde 2", section: "menu", case: "hse", new: ANY };
    expect(permitted("menu", "hse", "admin", [1], { a: 1 }, [loose])?.item).toBe("§8 madde 2");
  });

  it("desenler yalnız * ve ? jokerini tanır, öteki karakterler olduğu gibi eşleşir", () => {
    expect(matches("/isg/*", "/isg/:tab?")).toBe(true);
    expect(matches("/isg/:tab?", "/isg/:tab?")).toBe(true);
    expect(matches("/isg/.*", "/isg/olaylar")).toBe(false);
    expect(matches("(index)", "(index)")).toBe(true);
  });

  it("izinsiz farkta okunur bir hata verir, anlık görüntü yoksa nasıl üretileceğini söyler", () => {
    const baseline = { menu: { hse: { depo: true } } };
    expect(() => compareSection(baseline, "menu", { hse: { depo: true } })).not.toThrow();
    expect(() => compareSection(baseline, "menu", { hse: { depo: false } })).toThrow(
      /1 izinsiz fark\.\nmenu › hse \[depo\]: true → false/,
    );
    expect(() => compareSection(null, "menu", {})).toThrow(/ACCESS_PARITY_UPDATE=1/);
  });
});
