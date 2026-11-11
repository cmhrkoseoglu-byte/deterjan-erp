import { describe, expect, it } from "vitest";
import { ANY, MISSING, isActive, matches, permitted, requiredFor, type Allowed } from "./allowlist";
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
    // İzin listesi açıkça boş verilir: gerçek liste 8. adımda menü kayıtlarını gerekli kılar.
    expect(() => compareSection(baseline, "menu", { hse: { depo: true } }, [])).not.toThrow();
    expect(() => compareSection(baseline, "menu", { hse: { depo: false } }, [])).toThrow(
      /1 izinsiz fark\.\nmenu › hse \[depo\]: true → false/,
    );
    expect(() => compareSection(null, "menu", {})).toThrow(/ACCESS_PARITY_UPDATE=1/);
  });

  it("köşeli parantezler olduğu gibi eşleşir (backend'deki desenlerle aynı)", () => {
    const name = "quality.conditional_release.approve [kendi önerisi]";
    expect(matches(name, name)).toBe(true);
    expect(matches(name, "quality.conditional_release.approve k")).toBe(false);
    expect(matches("quality.conditional_release.* [kendi önerisi]", name)).toBe(true);
    expect(
      matches(
        "quality.conditional_release.* [kendi önerisi]",
        "quality.conditional_release.approve [başkasının önerisi]",
      ),
    ).toBe(false);
  });

  it("sonraki bir adımın kaydı o adıma gelinceye kadar geçerli değildir", () => {
    const rule: Allowed = { item: "§8 madde 1", section: "menu", case: "hse", step: 8 };
    const expected = { hse: { no_role: true } };
    const actual = { hse: { no_role: false } };
    expect(differences("menu", expected, actual, [rule], 7).unexpected).toEqual([
      "menu › hse [no_role]: true → false",
    ]);
    const { unexpected, used } = differences("menu", expected, actual, [rule], 8);
    expect(unexpected).toEqual([]);
    expect(used).toEqual([rule]);
    expect(isActive(rule, 7)).toBe(false);
    expect(requiredFor("menu", [rule], 7)).toEqual([]);
    expect(requiredFor("menu", [rule], 8)).toEqual([rule]);
  });

  it("gerekli kayıt hiçbir farkla eşleşmezse karşılaştırma bozulur", () => {
    const rule: Allowed = {
      item: "§8 madde 1",
      section: "menu",
      case: "hse",
      old: true,
      new: false,
    };
    const baseline = { menu: { hse: { no_role: true } } };
    expect(() =>
      compareSection(baseline, "menu", { hse: { no_role: false } }, [rule]),
    ).not.toThrow();
    expect(() => compareSection(baseline, "menu", { hse: { no_role: true } }, [rule])).toThrow(
      /1 kayıt hiçbir farkla eşleşmedi \(menu\)\.\n§8 madde 1: menu › hse \[\*\]/,
    );
    // Başka bölümün kaydı ve gerekli olmayan kayıt aranmaz.
    const other: Allowed = { item: "§8 madde 2", section: "routes", case: "/isg" };
    const optional: Allowed = { ...rule, required: false };
    expect(() =>
      compareSection(baseline, "menu", { hse: { no_role: true } }, [other, optional]),
    ).not.toThrow();
  });

  it("kayıt son adımından sonra geçerli değildir", () => {
    const rule: Allowed = { item: "yeni sayfa: deneme", section: "menu", case: "hse", until: 8 };
    const expected = { hse: { no_role: true } };
    const actual = { hse: { no_role: false } };
    expect(differences("menu", expected, actual, [rule], 8).unexpected).toEqual([]);
    expect(isActive(rule, 9)).toBe(false);
    expect(requiredFor("menu", [rule], 9)).toEqual([]);
    expect(differences("menu", expected, actual, [rule], 9).unexpected).toEqual([
      "menu › hse [no_role]: true → false",
    ]);
  });
});
