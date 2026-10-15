import { describe, expect, it } from "vitest";
import type { CurrentUser, Role } from "../api/types";
import { MENU, visibleMenu } from "./menu";

function userWith(roles: Role[], extra: Partial<CurrentUser> = {}): CurrentUser {
  return { id: 1, username: "u", full_name: "", email: "", roles, is_superuser: false, ...extra };
}

const keys = (user: CurrentUser | null) => visibleMenu(user).map((item) => item.key);

describe("visibleMenu", () => {
  it("depo rolü kendi modülünü ve (malzeme hazırlama için) üretimi görür", () => {
    expect(keys(userWith(["depo"]))).toEqual(["home", "inventory", "production"]);
  });

  it("laboratuvar rolü kalite modülünü ve (lot onay için) depoyu görür", () => {
    const visible = keys(userWith(["laboratuvar"]));
    expect(visible).toContain("quality");
    expect(visible).toContain("inventory");
    expect(visible).not.toContain("sales");
  });

  it("stok sorgu her role açıktır", () => {
    expect(keys(userWith(["uretim"]))).toContain("inventory");
    expect(keys(userWith(["sevkiyat"]))).toContain("inventory");
  });

  it("reçeteleri planlama ve laboratuvar görür", () => {
    expect(keys(userWith(["laboratuvar"]))).toContain("recipes");
    expect(keys(userWith(["planlama"]))).toEqual(expect.arrayContaining(["masterdata", "recipes"]));
    expect(keys(userWith(["uretim"]))).not.toContain("recipes");
  });

  it("birden fazla rolün menüleri birleşir", () => {
    expect(keys(userWith(["depo", "sevkiyat"]))).toEqual([
      "home",
      "inventory",
      "production",
      "sales",
    ]);
  });

  it("admin ve süper kullanıcı her öğeyi görür", () => {
    const all = MENU.map((item) => item.key);
    expect(keys(userWith(["admin"]))).toEqual(all);
    expect(keys(userWith([], { is_superuser: true }))).toEqual(all);
  });

  it("yönetim paneli yalnızca admin içindir", () => {
    expect(keys(userWith(["yonetim"]))).not.toContain("admin");
  });

  it("oturum yoksa menü boştur", () => {
    expect(keys(null)).toEqual([]);
  });
});
