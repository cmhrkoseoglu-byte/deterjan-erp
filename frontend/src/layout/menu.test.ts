import { describe, expect, it } from "vitest";
import type { CurrentUser, Role } from "../api/types";
import { MENU, visibleMenu } from "./menu";

function userWith(roles: Role[], extra: Partial<CurrentUser> = {}): CurrentUser {
  return {
    id: 1,
    username: "u",
    full_name: "",
    email: "",
    roles,
    is_superuser: false,
    otp_enabled: false,
    otp_setup_required: false,
    field_device: false,
    idle_timeout_seconds: 3600,
    ...extra,
  };
}

const keys = (user: CurrentUser | null) => visibleMenu(user).map((item) => item.key);

describe("visibleMenu", () => {
  it("depo rolü kendi modülünü, (hazırlama için) üretim ve dolumu, (rezervasyon için) sevkiyatı, (iade kabulü için) iadeleri, (beklenen teslimatlar için) satın almayı görür", () => {
    expect(keys(userWith(["depo"]))).toEqual([
      "home",
      "inventory",
      "production",
      "filling",
      "sales",
      "returns",
      "purchasing",
      "hse",
      "reporting",
    ]);
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
      "filling",
      "sales",
      "returns",
      "purchasing",
      "hse",
      "reporting",
    ]);
  });

  it("admin ve süper kullanıcı her öğeyi görür", () => {
    const all = MENU.map((item) => item.key);
    expect(keys(userWith(["admin"]))).toEqual(all);
    expect(keys(userWith([], { is_superuser: true }))).toEqual(all);
  });

  it("maliyeti yalnızca yönetim (ve admin) görür", () => {
    expect(keys(userWith(["yonetim"]))).toContain("costing");
    for (const role of ["depo", "planlama", "satin_alma", "uretim", "dolum"] as Role[]) {
      expect(keys(userWith([role]))).not.toContain("costing");
    }
  });

  it("bakımı üretim, dolum, laboratuvar, planlama ve yönetim görür; İSG herkese açıktır", () => {
    for (const role of ["uretim", "dolum", "laboratuvar", "planlama", "yonetim"] as Role[]) {
      expect(keys(userWith([role]))).toContain("maintenance");
    }
    for (const role of ["depo", "sevkiyat", "satin_alma"] as Role[]) {
      expect(keys(userWith([role]))).not.toContain("maintenance");
      expect(keys(userWith([role]))).toContain("hse");
    }
  });

  it("panolar ve raporlar her role açıktır (içerik rolle daralır)", () => {
    for (const role of ["depo", "laboratuvar", "dolum", "sevkiyat", "uretim"] as Role[]) {
      expect(keys(userWith([role]))).toContain("reporting");
    }
  });

  it("yönetim paneli yalnızca admin içindir", () => {
    expect(keys(userWith(["yonetim"]))).not.toContain("admin");
  });

  it("Sistem ekranını yalnızca admin (ve süper kullanıcı) görür; yönetim panelinden önce gelir", () => {
    for (const role of ["yonetim", "planlama", "depo", "laboratuvar", "satin_alma"] as Role[]) {
      expect(keys(userWith([role]))).not.toContain("system");
    }
    const admin = keys(userWith(["admin"]));
    expect(admin).toContain("system");
    expect(admin.indexOf("system")).toBe(admin.indexOf("admin") - 1);
    expect(keys(userWith([], { is_superuser: true }))).toContain("system");
  });

  it("oturum yoksa menü boştur", () => {
    expect(keys(null)).toEqual([]);
  });
});
