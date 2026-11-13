import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import type { CurrentUser } from "../../api/types";
import { roleBar } from "../../layout/roleBar";
import { MENU, visibleMenu } from "../../layout/menu";
import { GUIDES } from "../../modules/help/guides";
import { adjustmentPath, receiptPath } from "../../modules/inventory/config";
import { fillingOrderPath, specPath } from "../../modules/filling/config";
import { orderPath } from "../../modules/production/config";
import { purchaseOrderPath } from "../../modules/purchasing/config";
import { ManagementView } from "../../modules/reporting/Dashboards";
import { returnPath } from "../../modules/returns/config";
import { salesOrderPath } from "../../modules/sales/config";
import { routes } from "../../routes";
import { RECORD_ROUTES } from "../../workflow/recordLinks";
import { SEARCH_PATH } from "../paths";
import { makePersonas, PERSONAS } from "./personas";
import {
  closed,
  decide,
  holdRequests,
  outcome,
  readTabs,
  renderAt,
  requests,
  routeCases,
  routeDecision,
  tabPath,
} from "./probes";
import { managementData, readHelp, readManagement, readReportButtons } from "./readers";
import {
  compareSection,
  loadBaseline,
  saveBaseline,
  updating,
  type Baseline,
  type Cases,
  type Json,
} from "./snapshot";

// Kabuk (menü, üst çubuk, bildirimler) sondaya karışmasın: sayfalar yalnız içerikleriyle çizilir.
// Menü `visibleMenu` ile ayrıca dondurulur.
vi.mock("../../layout/AppLayout", async () => {
  const { Outlet } = await import("react-router-dom");
  return { AppLayout: Outlet };
});

/**
 * Ön yüz eşlik anlık görüntüsü (plan §5.5, 4. parça; §5.9). Her persona için bugünkü kodun
 * verdiği kararlar `baseline.json`'da dondurulur; kişiye özel ayar yokken her adım aynı sonucu
 * vermelidir. Bilerek yapılan farklar `allowlist.ts`'de planın §8 maddesine bağlanır.
 *
 * Kararlar kullanıcının gördüğünden okunur (sayfa gerçek rota ağacıyla çizilir); menü, açılış
 * sayfası ve üst bant rengi kendi işlevlerinden. Her bölüm ayrı bir testtir.
 */

/** Anlık görüntünün bölümleri; her biri aşağıdaki bir testte karşılaştırılır. */
const SECTIONS = [
  "menu",
  "shell",
  "pageTabs",
  "pageDefaults",
  "reportButtons",
  "help",
  "routes",
  "search",
  "dashboardLinks",
  "recordLinks",
  "newPages",
];

const users = makePersonas();
const collected: Baseline = {};
let baseline: Baseline | null = null;
/** Bütün bölümler üretildi: güncellemede dosya baştan yazılır (yoksa yalnız üretilenler). */
let complete = false;
let release: () => void = () => undefined;

function check(section: string, cases: Cases): void {
  collected[section] = cases;
  if (!updating()) compareSection(baseline, section, cases);
}

/** Her persona için değer üreterek bir durum satırı kurar. */
async function row(
  value: (persona: string, user: CurrentUser | null) => Json | Promise<Json>,
): Promise<Record<string, Json>> {
  const values: Record<string, Json> = {};
  for (const [persona, user] of users) values[persona] = await value(persona, user);
  return values;
}

/** Bir kez hesaplanıp birden çok bölüme dağıtılan sonuç (aynı çizimden okunan bölümler). */
function once<T>(compute: () => Promise<T>): () => Promise<T> {
  let result: Promise<T> | null = null;
  return () => (result ??= compute());
}

const SLOW = 120_000;

beforeAll(async () => {
  baseline = await loadBaseline();
  release = holdRequests();
});

afterAll(async () => {
  release();
  if (updating()) await saveBaseline(collected, complete ? null : baseline);
});

/**
 * Menüdeki her modül sayfası, sekmesiz adresiyle: görünen sekmeler (adresleri), seçilen sekme
 * (sekmesi yoksa açıldığı adres) ve başlıktaki bildirim düğmeleri.
 */
const modulePages = once(async () => {
  const pages = MENU.filter((item) => !item.external);
  expect(pages).toHaveLength(20);
  const tabs: Cases = {};
  const opened: Cases = {};
  const buttons: Cases = {};
  for (const page of pages) {
    tabs[page.path] = {};
    opened[page.path] = {};
    buttons[page.path] = {};
    for (const [persona, user] of users) {
      const rendered = await renderAt(routes, page.path, user);
      try {
        const decision = outcome(rendered, page.path);
        if (closed(decision)) {
          tabs[page.path][persona] = decision;
          opened[page.path][persona] = decision;
          buttons[page.path][persona] = decision;
          continue;
        }
        buttons[page.path][persona] = readReportButtons(rendered.container);
        const { values, selected } = readTabs(rendered.container);
        const where = rendered.router.state.location.pathname;
        const paths: string[] = [];
        let selectedPath: string | null = null;
        for (const value of values) {
          paths.push(await tabPath(rendered, page.path, value));
          if (value === selected) selectedPath = paths[paths.length - 1];
        }
        tabs[page.path][persona] = paths;
        // Sekmesi olmayan sayfada açıldığı adres (yönlendirdiyse yeni adres).
        opened[page.path][persona] = selectedPath ?? where;
      } finally {
        rendered.unmount();
      }
    }
  }
  // Bildirim düğmeleri: yalnız bir düğmenin çıktığı sayfalar.
  const withButtons = Object.entries(buttons).filter(([, values]) =>
    Object.values(values).some((value) => Array.isArray(value) && value.length > 0),
  );
  expect(withButtons.map(([path]) => path).sort()).toEqual(["/bakim", "/gorevlerim", "/isg"]);
  return { tabs, opened, buttons: Object.fromEntries(withButtons) as Cases };
});

describe("ön yüz eşlik anlık görüntüsü", () => {
  it("persona listesi backend sözleşme testiyle aynı", () => {
    expect(PERSONAS).toEqual([
      "anonymous",
      "inactive",
      "no_role",
      "yonetim",
      "planlama",
      "depo",
      "uretim",
      "laboratuvar",
      "dolum",
      "sevkiyat",
      "satin_alma",
      "admin",
      "superuser",
      "depo+sevkiyat",
    ]);
  });

  it("menü", async () => {
    // Menünün tek kaynağı MENU; yeni öğe anlık görüntüye girmeden geçemesin.
    expect(MENU).toHaveLength(21);
    const menu: Cases = {};
    for (const item of MENU) {
      menu[item.key] = await row((_persona, user) =>
        visibleMenu(user).some((visible) => visible.key === item.key),
      );
    }
    check("menu", menu);
  });

  it("açılış sayfası ve üst bant rengi", async () => {
    check("shell", {
      // `/` (logo, girişten sonra) kişiyi nereye götürüyor: yönetim panosu ya da Görevlerim.
      landing: await row((_persona, user) => decide(routes, "/", user)),
      roleBar: await row((_persona, user) => roleBar(user).role),
    });
  });

  it(
    "modül sayfaları: görünen sekmeler",
    async () => check("pageTabs", (await modulePages()).tabs),
    SLOW,
  );

  it(
    "modül sayfaları: sekmesiz açılınca seçilen sekme",
    async () => {
      check("pageDefaults", (await modulePages()).opened);
    },
    SLOW,
  );

  it(
    "modül sayfaları: arıza ve olay bildirimi düğmeleri",
    async () => {
      check("reportButtons", (await modulePages()).buttons);
    },
    SLOW,
  );

  it("yardım: rolün kılavuzları ve kılavuzsuz açılınca gösterilen", async () => {
    expect(GUIDES).toHaveLength(11);
    const mine: Record<string, Json> = {};
    const opened: Record<string, Json> = {};
    for (const [persona, user] of users) {
      const rendered = await renderAt(routes, "/yardim", user);
      try {
        const decision = outcome(rendered, "/yardim");
        if (closed(decision)) {
          mine[persona] = decision;
          opened[persona] = decision;
          continue;
        }
        const help = readHelp(rendered.container);
        mine[persona] = help.mine;
        opened[persona] = help.opened;
      } finally {
        rendered.unmount();
      }
    }
    check("help", { mine, opened });
  });

  it(
    "rota korumaları: her rota personayı içeri alıyor mu",
    async () => {
      const cases = routeCases(routes);
      expect(cases).toHaveLength(56);
      expect(new Set(cases.map((item) => item.name)).size).toBe(cases.length);
      const result: Cases = {};
      for (const { name, chain } of cases) {
        result[name] = await row((persona, user) => routeDecision(chain, persona, user));
      }
      check("routes", result);
    },
    SLOW,
  );

  it("arama sayfasında aranan listeler", async () => {
    const query = "ESLIK";
    const path = `${SEARCH_PATH}?q=${query}`;
    const searched = new Map<string, Set<string> | string>();
    for (const [persona, user] of users) {
      requests.length = 0;
      const rendered = await renderAt(routes, path, user);
      try {
        const decision = outcome(rendered, path);
        const urls = requests
          .filter((request) => (request.params as { search?: string })?.search === query)
          .map((request) => request.url ?? "");
        searched.set(persona, closed(decision) ? decision : new Set(urls));
      } finally {
        rendered.unmount();
      }
    }
    // Admin her listede arar: kaynakların tamamı.
    const all = searched.get("admin");
    if (!(all instanceof Set)) throw new Error("Admin arama sayfasını açamadı.");
    expect(all.size).toBe(11);
    const result: Cases = {};
    for (const url of [...all].sort()) {
      result[url] = await row((persona) => {
        const value = searched.get(persona)!;
        return value instanceof Set ? value.has(url) : value;
      });
    }
    check("search", result);
  });

  it("yönetim panosu: kartlardaki ve dikkat listesindeki bağlantılar", async () => {
    const tree = [{ path: "*", element: <ManagementView data={managementData()} /> }];
    const seen = new Map<string, { heading: string; links: string[] }>();
    for (const [persona, user] of users) {
      const rendered = await renderAt(tree, "/", user);
      try {
        seen.set(persona, readManagement(rendered.container));
      } finally {
        rendered.unmount();
      }
    }
    // Admin her bağlantıyı görür: 3 onay kartı, 7 hedefli dikkat satırı, 3 açık emir satırı.
    const all = seen.get("admin")!.links;
    expect(all).toHaveLength(13);
    expect(new Set(all).size).toBe(all.length);
    const result: Cases = { "approvals heading": await row((p) => seen.get(p)!.heading) };
    for (const link of all) result[link] = await row((p) => seen.get(p)!.links.includes(link));
    check("dashboardLinks", result);
  });

  it(
    "kayıt bağlantıları: hedef sayfa personaya açılıyor mu",
    async () => {
      const models = Object.keys(RECORD_ROUTES).sort();
      expect(models).toHaveLength(21);
      const result: Cases = {};
      for (const model of models) {
        const path = RECORD_ROUTES[model](1);
        result[model] = await row((_persona, user) => decide(routes, path, user));
      }
      check("recordLinks", result);
    },
    SLOW,
  );

  it(
    "yeni belge sayfaları açılıyor mu",
    async () => {
      // `(id | "yeni")` alan bütün adres yardımcıları.
      const paths = [
        orderPath("yeni"),
        fillingOrderPath("yeni"),
        specPath("yeni"),
        receiptPath("yeni"),
        adjustmentPath("yeni"),
        salesOrderPath("yeni"),
        purchaseOrderPath("yeni"),
        returnPath("yeni"),
      ];
      const result: Cases = {};
      for (const path of paths) {
        result[path] = await row((_persona, user) => decide(routes, path, user));
      }
      check("newPages", result);
    },
    SLOW,
  );

  it("bütün bölümler üretildi ve karşılaştırıldı", () => {
    expect(Object.keys(collected).sort()).toEqual([...SECTIONS].sort());
    if (!updating()) expect(Object.keys(baseline ?? {}).sort()).toEqual([...SECTIONS].sort());
    complete = true;
  });
});
