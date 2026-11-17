import { describe, expect, it } from "vitest";
import { superuser, userWith, withAccess, withoutAccess } from "../test/fixtures";
import type { Role } from "../api/types";
import {
  can,
  canAny,
  canRead,
  describeAccess,
  isAdminUser,
  moduleVisible,
  PANEL_ONLY_SECTIONS,
} from "./access";
import { ROLE_ACCESS, SECTIONS, type PermKey } from "./access.gen";
import { canOpenPage, personnelPath } from "./pageAccess";
import { landingPath } from "./paths";

describe("can / canRead / canAny", () => {
  it("me.access harflerini okur: v görür, c değiştirir, a onaylar", () => {
    const planlama = userWith("planlama");
    expect(can(planlama, "production.orders")).toBe(true);
    expect(can(planlama, "production.orders", "change")).toBe(true);
    expect(can(planlama, "personnel.cards")).toBe(false);
    const depo = userWith("depo");
    expect(can(depo, "production.prep", "change")).toBe(true);
    expect(can(depo, "production.orders", "change")).toBe(false);
    expect(can(null, "inventory.stock")).toBe(false);
  });

  it("kayıt okuması r ya da v ile; açık okumalı bölümler rolsüze de açık", () => {
    const none = userWith();
    expect(canRead(none, "inventory.receipts")).toBe(true);
    expect(can(none, "inventory.receipts")).toBe(false);
    expect(canRead(none, "purchasing.orders")).toBe(false);
    expect(canAny(userWith("sevkiyat"), ["sales.picking", "view"], ["sales.orders", "view"])).toBe(
      true,
    );
  });

  it("admin ve süper kullanıcı her bölümün her düzeyine sahip; yalnız admin düzeyleri dahil", () => {
    for (const admin of [userWith("admin"), superuser()]) {
      expect(isAdminUser(admin)).toBe(true);
      expect(can(admin, "inventory.manual_release", "approve")).toBe(true);
      expect(can(admin, "masterdata.reference", "change")).toBe(true);
      // Bölümde olmayan düzey yok sayılır (Arıza bildirimi'nde Görür yok).
      expect(can(admin, "maintenance.breakdowns", "view")).toBe(false);
      expect(canRead(admin, "inventory.receipts")).toBe(true);
    }
    expect(can(userWith("yonetim"), "masterdata.reference", "change")).toBe(false);
    expect(can(userWith("laboratuvar"), "inventory.manual_release", "approve")).toBe(false);
  });

  it("tanımsız bölüm hiçbir şey açmaz", () => {
    expect(can(userWith("admin"), "yok.bolum")).toBe(false);
    expect(can(userWith("yonetim"), "yok.bolum")).toBe(false);
  });

  it("modül, ekranı olan bölümlerinden birinde Görür'le görünür (okuma sayılmaz)", () => {
    expect(moduleVisible(userWith("depo"), "production")).toBe(true);
    expect(moduleVisible(userWith("depo"), "maintenance")).toBe(false);
    expect(moduleVisible(userWith(), "hse")).toBe(false);
    expect(moduleVisible(userWith("satin_alma"), "hse")).toBe(true);
    expect(moduleVisible(userWith(), "inventory")).toBe(true);
    // Açık okumalı bölümlerin `r`'si modülü açmaz.
    expect(moduleVisible(userWith(), "recipes")).toBe(false);
  });

  it("kendi ekranı olmayan bölüm modülü tek başına açmaz; varsayılan paketlerde fark yok", () => {
    for (const key of PANEL_ONLY_SECTIONS) {
      expect(SECTIONS[key as PermKey]?.kind).toBe("section");
      const moduleKey = key.split(".")[0];
      // Yalnız bu bölümü gören kişi modülü görmez.
      expect(moduleVisible(withAccess(userWith(), { [key]: "v" }), moduleKey)).toBe(false);
      // Bu bölümü gören her rolün modülde sekmesi olan başka bir bölümü vardır.
      for (const role of Object.keys(ROLE_ACCESS).filter((name) => name)) {
        if ([...(ROLE_ACCESS[role][key] ?? "")].includes("v")) {
          expect(moduleVisible(userWith(role as Role), moduleKey)).toBe(true);
        }
      }
    }
  });

  it("çok rollü kullanıcı rollerin birleşimini alır", () => {
    const both = userWith("depo", "sevkiyat");
    expect(can(both, "sales.picking", "change")).toBe(true);
    expect(can(both, "production.prep", "change")).toBe(true);
  });
});

describe("sayfa kuralları", () => {
  it("yeni üretim ve dolum emri sayfası emir Değiştirir'i ister; var olan emir modül birleşimi", () => {
    const depo = userWith("depo");
    expect(canOpenPage(depo, "productionOrder", { orderId: "12" })).toBe(true);
    expect(canOpenPage(depo, "productionOrder", { orderId: "yeni" })).toBe(false);
    expect(canOpenPage(userWith("planlama"), "fillingOrder", { orderId: "yeni" })).toBe(true);
    expect(canOpenPage(userWith("dolum"), "fillingOrder", { orderId: "yeni" })).toBe(false);
  });

  it("İndirmeler herkese açık; Panolar ve raporlar rolsüzde kapalı", () => {
    const none = userWith();
    expect(canOpenPage(none, "reporting", { tab: "indirmeler" })).toBe(true);
    expect(canOpenPage(none, "reporting", {})).toBe(false);
    expect(canOpenPage(none, "reporting", { tab: "panolar" })).toBe(false);
    expect(canOpenPage(userWith("dolum"), "reporting", {})).toBe(true);
  });

  it("yönetim panosu ve açılış sayfası yönetim rolü ile Yönetim panosu: Görür'ü birlikte ister", () => {
    const yonetim = userWith("yonetim");
    expect(canOpenPage(yonetim, "dashboard")).toBe(true);
    expect(landingPath(yonetim)).toBe("/pano");
    const blind = withoutAccess(yonetim, { "reporting.management": "v" });
    expect(canOpenPage(blind, "dashboard")).toBe(false);
    expect(landingPath(blind)).toBe("/gorevlerim");
    // Planlama panoyu Panolar ve raporlar'da görür ama /pano rol görünümüdür.
    expect(canOpenPage(userWith("planlama"), "dashboard")).toBe(false);
    expect(landingPath(userWith("admin"))).toBe("/gorevlerim");
  });

  it("Personel kartları'nı göremeyen kişinin menü bağlantısı ilk açabildiği personel sayfası", () => {
    const yonetim = userWith("yonetim");
    expect(personnelPath(yonetim)).toBe("/personel");
    expect(personnelPath(withoutAccess(yonetim, { "personnel.cards": "vc" }))).toBe(
      "/personel/puantaj",
    );
    const wagesOnly = withAccess(userWith(), { "personnel.wages": "v" });
    expect(personnelPath(wagesOnly)).toBe("/personel/ucretler");
  });
});

describe("gereken yetkinin adı", () => {
  it("modül › bölüm (düzey)", () => {
    expect(describeAccess({ key: "production.orders", level: "change" })).toBe(
      "Üretim › Üretim emirleri (Değiştirir)",
    );
    expect(describeAccess({ key: "purchasing.orders", level: "view" })).toBe(
      "Satın alma › Satın alma siparişleri (Görür)",
    );
    expect(describeAccess({ key: "hse", level: "view" })).toBe(
      "İSG ve çevre › bölümlerinden biri (Görür)",
    );
    expect(describeAccess({ key: "yok", level: "view" })).toBeNull();
  });
});
