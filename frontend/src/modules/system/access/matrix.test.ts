import { describe, expect, it } from "vitest";
import { ROLES, type Role } from "../../../api/types";
import { READERS } from "../../../auth/access.gen";
import { accessFor } from "../../../test/fixtures";
import {
  cellId,
  cellInfo,
  cleanIneffective,
  columnState,
  defaultLetters,
  defaultSources,
  diff,
  hasLetter,
  previewAccess,
  readThroughNotes,
  removeAllInModule,
  resetModule,
  setColumn,
  settle,
  toggle,
  toOverrides,
  viewOnlyModule,
  type Draft,
  type OverrideMap,
} from "./matrix";
import { RECORD_NOUNS } from "./strings";

const NONE: OverrideMap = new Map();

function draft(roles: Role[], overrides: [string, "grant" | "revoke"][] = []): Draft {
  return { roles, overrides: new Map(overrides) };
}

describe("ön izleme", () => {
  it("ayar yokken rol varsayılanıyla (ROLE_ACCESS) aynıdır", () => {
    const cases: Role[][] = [[], ...ROLES.map((role) => [role]), ["depo", "sevkiyat"]];
    for (const roles of cases) {
      expect(previewAccess(roles, NONE)).toEqual(accessFor(roles));
      expect(defaultLetters(roles)).toEqual(accessFor(roles));
    }
  });

  it("Görür kaldırılınca Değiştirir de düşer; ön koşulu eksik düzey düşer", () => {
    const revoked = previewAccess(
      ["depo"],
      new Map([[cellId("production.prep", "view"), "revoke"]]),
    );
    expect(hasLetter(revoked, "production.prep", "view")).toBe(false);
    expect(hasLetter(revoked, "production.prep", "change")).toBe(false);
    const granted = previewAccess(
      ["depo"],
      new Map([[cellId("purchasing.orders", "change"), "grant"]]),
    );
    // Fiyatları görür yok: Değiştirir düşer, Görür kalır.
    expect(hasLetter(granted, "purchasing.orders", "change")).toBe(false);
    expect(hasLetter(granted, "purchasing.orders", "view")).toBe(true);
  });
});

describe("hücre durumu", () => {
  it("kaynakları yazar: herkes, rol ve rolü olan herkes", () => {
    expect(defaultSources("inventory.lots", "view", ["depo"])).toEqual(["Herkes"]);
    expect(defaultSources("production.prep", "change", ["depo"])).toEqual(["Depo"]);
    expect(defaultSources("hse.hazards", "view", ["depo"])).toEqual(["Rolü olan herkes"]);
    expect(defaultSources("production.orders", "view", ["depo", "uretim"])).toEqual([
      "Depo",
      "Üretim",
    ]);
  });

  it("bölümde olmayan, yalnız admin, KVKK ve herkese açık kilitli hücreleri ayırır", () => {
    const d = draft(["depo"]);
    expect(cellInfo(d, NONE, "inventory.lots", "change").state).toBe("absent");
    expect(cellInfo(d, NONE, "inventory.manual_release", "approve")).toMatchObject({
      state: "locked",
      lockReason: "admin_only",
    });
    expect(cellInfo(d, NONE, "personnel.cards", "view")).toMatchObject({
      state: "locked",
      lockReason: "kvkk",
    });
    expect(cellInfo(d, NONE, "inventory.stock", "view")).toMatchObject({
      state: "locked",
      lockReason: "everyone",
    });
    expect(cellInfo(d, NONE, "production.prep", "change").state).toBe("role");
    expect(cellInfo(d, NONE, "quality.specs", "view").state).toBe("none");
  });

  it("eklenen, kaldırılan ve kaydedilmemiş hücreler", () => {
    const saved: OverrideMap = new Map([[cellId("production.prep", "change"), "revoke"]]);
    const d = draft(
      ["depo"],
      [
        [cellId("production.prep", "change"), "revoke"],
        [cellId("quality.specs", "view"), "grant"],
      ],
    );
    expect(cellInfo(d, saved, "production.prep", "change")).toMatchObject({
      state: "revoked",
      dirty: false,
      effective: false,
    });
    expect(cellInfo(d, saved, "quality.specs", "view")).toMatchObject({
      state: "granted",
      dirty: true,
      effective: true,
    });
  });

  it("rolün verdiğini ekleyen ayar etkisizdir; ön koşulu eksik ekleme düşer", () => {
    const d = draft(
      ["depo"],
      [
        [cellId("production.prep", "view"), "grant"],
        [cellId("purchasing.orders", "change"), "grant"],
      ],
    );
    expect(cellInfo(d, NONE, "production.prep", "view").ineffective).toBe("redundant");
    expect(cellInfo(d, NONE, "purchasing.orders", "change").ineffective).toBe("dropped_prereq");
  });
});

describe("tıklama", () => {
  it("ilk tıklama tersine çevirir, ikinci tıklama rol varsayılanına döndürür", () => {
    const first = toggle(draft(["depo"]), "production.prep", "change").draft;
    expect(first.overrides.get(cellId("production.prep", "change"))).toBe("revoke");
    const second = toggle(first, "production.prep", "change").draft;
    expect(second.overrides.size).toBe(0);
    const grant = toggle(draft(["depo"]), "quality.specs", "view").draft;
    expect(grant.overrides.get(cellId("quality.specs", "view"))).toBe("grant");
  });

  it("açık kayıtlar yalnız kapatılır", () => {
    const closed = toggle(draft(["depo"]), "quality.open_records", "read").draft;
    expect(toOverrides(closed.overrides)).toEqual([
      { key: "quality.open_records", level: "read", effect: "revoke" },
    ]);
    expect(toggle(closed, "quality.open_records", "read").draft.overrides.size).toBe(0);
  });

  it("Değiştirir açılınca Görür ve eksik ön koşul da verilir; not yazılır", () => {
    const result = toggle(draft(["uretim"]), "purchasing.orders", "change");
    expect(toOverrides(result.draft.overrides)).toEqual([
      { key: "purchasing.orders", level: "change", effect: "grant" },
      { key: "purchasing.orders", level: "view", effect: "grant" },
      { key: "sensitive.prices", level: "view", effect: "grant" },
    ]);
    expect(result.notes.map((note) => note.text)).toEqual([
      "Satın alma › Satın alma siparişleri: Değiştirir için Fiyatları görür de verildi.",
    ]);
    const preview = previewAccess(result.draft.roles, result.draft.overrides);
    expect(hasLetter(preview, "purchasing.orders", "change")).toBe(true);
  });

  it("Görür kapanınca Değiştirir eklemesi de kalkar", () => {
    const d = draft(
      ["uretim"],
      [
        [cellId("sales.orders", "view"), "grant"],
        [cellId("sales.orders", "change"), "grant"],
      ],
    );
    const result = toggle(d, "sales.orders", "view").draft;
    expect(result.overrides.size).toBe(0);
    const depo = toggle(draft(["depo"]), "production.prep", "view").draft;
    // Yalnız Görür'ün kaldırması yazılır; Değiştirir onunla düşer.
    expect(toOverrides(depo.overrides)).toEqual([
      { key: "production.prep", level: "view", effect: "revoke" },
    ]);
  });

  it("KVKK yüzünden verilemeyen ön koşulda taslak değişmez", () => {
    const d = draft(["depo"]);
    const result = toggle(d, "costing.lot_costs", "view");
    // Maliyetleri görür ve Fiyatları görür verilebilir; hata yok.
    expect(result.notes.some((note) => note.error)).toBe(false);
    expect(cellInfo(d, NONE, "costing.personnel_cost", "view").state).toBe("locked");
  });
});

describe("okumaya devam eden kayıtlar", () => {
  it("Görür'ü kaldırılan bölümün kayıtları öteki bölümlerden okunur", () => {
    const d = toggle(draft(["depo"]), "production.orders", "view").draft;
    const preview = previewAccess(d.roles, d.overrides);
    const notes = readThroughNotes(preview, "production.orders", RECORD_NOUNS);
    expect(notes).toContain(
      "Emirleri Malzeme hazırlama ve Şarj ve tartım üzerinden görmeye devam eder.",
    );
  });

  it("her kayıt türünün okunur adı var", () => {
    for (const model of Object.keys(READERS)) expect(RECORD_NOUNS[model]).toBeTruthy();
  });
});

describe("toplu işlemler", () => {
  it("modüldeki bütün yetkileri kaldır açık kayıtlar satırını değiştirmez", () => {
    const d = removeAllInModule(draft(["depo"]), "production");
    expect(d.overrides.has(cellId("production.open_records", "read"))).toBe(false);
    const preview = previewAccess(d.roles, d.overrides);
    for (const key of ["production.orders", "production.prep", "production.batches"])
      expect(hasLetter(preview, key, "view")).toBe(false);
    expect(hasLetter(preview, "production.open_records", "read")).toBe(true);
    expect(resetModule(d, "production").overrides.size).toBe(0);
  });

  it("yalnız görsün yeni Görür açmaz, Değiştirir'i kapatır", () => {
    const d = viewOnlyModule(draft(["depo"]), "production");
    const preview = previewAccess(d.roles, d.overrides);
    expect(hasLetter(preview, "production.prep", "view")).toBe(true);
    expect(hasLetter(preview, "production.prep", "change")).toBe(false);
    const planning = viewOnlyModule(draft(["sevkiyat"]), "production");
    expect(planning.overrides.size).toBe(0);
  });

  it("yalnız görsün, Değiştirir'den gelen Görür'ü korur", () => {
    const start = toggle(draft(["yonetim"]), "masterdata.cards", "change").draft;
    const switched: Draft = { roles: ["depo"], overrides: start.overrides };
    expect(
      hasLetter(previewAccess(switched.roles, switched.overrides), "masterdata.cards", "view"),
    ).toBe(true);
    const d = viewOnlyModule(switched, "masterdata");
    const preview = previewAccess(d.roles, d.overrides);
    expect(hasLetter(preview, "masterdata.cards", "view")).toBe(true);
    expect(hasLetter(preview, "masterdata.cards", "change")).toBe(false);
  });

  it("sütun kutusu kilitli ve yalnız admin hücreleri atlar", () => {
    const d = draft(["depo"]);
    expect(columnState(d, "inventory", "approve")).not.toBe("all");
    const on = setColumn(d, "production", "change", true).draft;
    expect(columnState(on, "production", "change")).toBe("all");
    expect(on.overrides.has(cellId("inventory.manual_release", "approve"))).toBe(false);
  });

  it("etkisiz ayarları temizler; değişiklik sayısı rolleri ve hücreleri sayar", () => {
    const base = draft(["depo"]);
    const d: Draft = {
      roles: ["depo", "planlama"],
      overrides: new Map([
        [cellId("production.prep", "view"), "grant"],
        [cellId("quality.specs", "view"), "grant"],
      ]),
    };
    expect(diff(base, d).count).toBe(3);
    expect(toOverrides(cleanIneffective(d, new Set(), base.roles).overrides)).toEqual([
      { key: "quality.specs", level: "view", effect: "grant" },
    ]);
  });

  it("sunucunun etkisiz işareti taslakta roller değişince sayılmaz", () => {
    const id = cellId("production.orders", "approve");
    const flagged = new Set([`${id}|grant`]);
    const saved: Role[] = ["depo", "planlama"];
    const same = draft(saved, [[id, "grant"]]);
    expect(cleanIneffective(same, flagged, saved).overrides.size).toBe(0);
    // Planlama kaldırılınca ekleme yeniden geçerli olur; temizlenmez.
    const changed = draft(["depo"], [[id, "grant"]]);
    expect(cellInfo(changed, same.overrides, "production.orders", "approve").ineffective).toBe(
      undefined,
    );
    expect(toOverrides(cleanIneffective(changed, flagged, saved).overrides)).toEqual([
      { key: "production.orders", level: "approve", effect: "grant" },
    ]);
  });
});

describe("sunucunun kabul edeceği taslak", () => {
  it("yönetim rolü kalkınca kaydedilmemiş KVKK eklemesi kalkar, kayıtlısı kalır", () => {
    const fresh = cellId("personnel.cards", "view");
    const kept = cellId("personnel.wages", "view");
    const saved: OverrideMap = new Map([[kept, "grant"]]);
    const result = settle(
      draft(
        ["depo"],
        [
          [fresh, "grant"],
          [kept, "grant"],
        ],
      ),
      saved,
    );
    expect(toOverrides(result.draft.overrides)).toEqual([
      { key: "personnel.wages", level: "view", effect: "grant" },
    ]);
    expect(result.notes).toEqual([
      {
        key: "personnel.cards",
        text: "Personel › Personel kartları ve özlük belgeleri: Görür eklemesi kaldırıldı: yalnız yönetim rolündekilere verilebilir (KVKK).",
      },
    ]);
    // Yönetim rolü varken değişmez.
    const held = draft(["yonetim"], [[fresh, "grant"]]);
    expect(settle(held, saved).draft).toBe(held);
  });

  it("taslağın verdiği ön koşul kapatılınca ona bağlı kaydedilmemiş ekleme de kalkar", () => {
    const on = toggle(draft(["depo"]), "purchasing.over_limit", "approve");
    // Depo siparişleri rolden görür; Fiyatları görür taslakta verilir.
    expect(toOverrides(on.draft.overrides)).toEqual([
      { key: "purchasing.over_limit", level: "approve", effect: "grant" },
      { key: "sensitive.prices", level: "view", effect: "grant" },
    ]);
    const off = toggle(on.draft, "sensitive.prices", "view");
    expect(off.draft.overrides.size).toBe(0);
    expect(off.notes.map((note) => note.text)).toEqual([
      "Satın alma › Limit üstü sipariş onayı: Onaylar eklemesi de kaldırıldı (Fiyatları görür gerekir).",
    ]);
    // Kayıtlı ekleme kalır; sunucu kaydedince uyararak düşürür.
    const saved = on.draft.overrides;
    const kept = toggle(on.draft, "sensitive.prices", "view", saved);
    expect(kept.draft.overrides.get(cellId("purchasing.over_limit", "approve"))).toBe("grant");
    expect(kept.notes.map((note) => note.text)).toEqual([
      "Satın alma › Limit üstü sipariş onayı: Onaylar de düşer (Hassas veriler › Fiyatları görür: Görür gerekir).",
    ]);
  });
});
