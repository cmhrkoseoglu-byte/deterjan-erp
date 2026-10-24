#!/usr/bin/env node
// Yardım sayfasındaki kılavuzların ekran görüntülerini yeniden üretir
// (frontend/src/modules/help/guides/*.md → frontend/public/kilavuz/<ad>.jpg).
//
// Kullanım (uygulama ayakta ve `seed_demo` verisi yüklü olmalı):
//
//   node scripts/kilavuz-ekran-goruntuleri.mjs [BASE_URL]
//
//   BASE_URL            Varsayılan http://127.0.0.1:4173 (vite preview, /api vekili).
//                       Docker Compose ile: http://localhost
//   PW                  Playwright modülünün yolu; yoksa "playwright" aranır
//                       (ör. PW=$(npm root -g)/playwright).
//   DEMO_USER_PASSWORD  Demo kullanıcıların şifresi (varsayılan Demo.12345).
//   KILAVUZ_ONLY        Yalnızca bu görüntüleri üret (virgülle ayrılmış adlar, ör. "depo-stok,genel-gorevlerim").
//
// Betik önce demo verisinde ekranların boş görünmemesi için gereken kayıtları API üzerinden açar
// (yalnızca yoksa): mal kabul ve giriş numuneleri, şartlı kabul bekleyen karar, malzeme hazırlamada
// bir üretim emri, tartımı süren bir şarj, dolumu süren bir parti, onay bekleyen satın alma siparişi
// ve bir sorun bildirimi. Kayıtların notunda "Kılavuz örneği" yazar. Hiçbir şey silinmez, canlı
// başlangıç tarihi girilmez, açılış stoku içe aktarılmaz. Canlı başlangıç tarihi girilmiş bir
// sistemde (gerçek veri) betik hiçbir şey yapmadan durur.
//
// Sonra her rolün demo kullanıcısıyla (kullanıcı adı = rol kodu) giriş yapıp ekranları çeker:
// ofis ekranları 1366x800, tablet ekranları 1024x768, JPEG kalite 70. Bir görüntü alınamazsa uyarı
// yazılır ve devam edilir; sonunda biri bile alınamadıysa çıkış kodu 1'dir.
//
// Giriş hızı sınırı (LOGIN_RATE_LIMIT, varsayılan 10/dk) nedeniyle her kullanıcı bir kez giriş yapar;
// sınıra takılırsa betik bekleyip yeniden dener.
//
// Yalnızca Node yerleşik modülleri ve Playwright kullanılır.

import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PW ?? "playwright");

const BASE = (process.argv[2] ?? "http://127.0.0.1:4173").replace(/\/$/, "");
const PASSWORD = process.env.DEMO_USER_PASSWORD ?? "Demo.12345";
const ONLY = (process.env.KILAVUZ_ONLY ?? "").split(",").filter(Boolean);
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const OUT = path.join(ROOT, "frontend", "public", "kilavuz");
const NOTE = "Kılavuz örneği";

const OFFICE = { width: 1366, height: 800 };
const TABLET = { width: 1024, height: 768 };

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const inDays = (days) => {
  const d = new Date(Date.now() + days * 86400000);
  return d.toISOString().slice(0, 10);
};
const warn = (message) => console.warn(`UYARI: ${message}`);

let browser;
const sessions = new Map();

/** Kullanıcı başına bir tarayıcı bağlamı: arayüzden bir kez giriş yapar, API çağrıları aynı oturumla. */
async function session(user) {
  if (sessions.has(user)) return sessions.get(user);
  const context = await browser.newContext({
    viewport: OFFICE,
    locale: "tr-TR",
  });
  const page = await context.newPage();
  for (let attempt = 0; ; attempt++) {
    await page.goto(`${BASE}/login`);
    await page.getByLabel("Kullanıcı adı").fill(user);
    await page.getByLabel("Şifre").fill(PASSWORD);
    const response = page.waitForResponse((r) =>
      r.url().includes("/api/v1/auth/login/"),
    );
    await page.getByRole("button", { name: "Giriş yap" }).click();
    const status = (await response).status();
    if (status === 200) break;
    if (status !== 429 || attempt > 8)
      throw new Error(`${user} giriş yapamadı (HTTP ${status})`);
    console.log(`  giriş hız sınırı; ${user} için 20 sn bekleniyor`);
    await sleep(20000);
  }
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));

  const call = async (method, url, data) => {
    const cookies = await context.cookies();
    const csrf = cookies.find((c) => c.name === "csrftoken")?.value ?? "";
    const response = await context.request.fetch(`${BASE}/api/v1${url}`, {
      method,
      ...(data instanceof Object && data.multipart ? data : { data }),
      headers: { "X-CSRFToken": csrf, Referer: `${BASE}/` },
    });
    const text = await response.text();
    if (!response.ok())
      throw new Error(
        `${user} ${method} ${url} → ${response.status()} ${text.slice(0, 300)}`,
      );
    return text ? JSON.parse(text) : null;
  };
  const s = {
    user,
    context,
    page,
    get: (url) => call("GET", url),
    post: (url, data = {}) => call("POST", url, data),
  };
  sessions.set(user, s);
  return s;
}

/** Giriş yapmamış ziyaretçi (giriş ekranı için). */
async function anonymous() {
  if (!sessions.has(null)) {
    const context = await browser.newContext({
      viewport: OFFICE,
      locale: "tr-TR",
    });
    sessions.set(null, { context, page: await context.newPage() });
  }
  return sessions.get(null);
}

// --- demo kayıtları ------------------------------------------------------------------------------

const cache = {};
async function byCode(api, kind, code) {
  const key = `${kind}:${code}`;
  if (!cache[key]) {
    const data = await api.get(
      `/masterdata/${kind}/?search=${encodeURIComponent(code)}&page_size=100`,
    );
    const row = data.results.find((r) => r.code === code);
    if (!row) throw new Error(`${kind} bulunamadı: ${code}`);
    cache[key] = row;
  }
  return cache[key];
}

/** Emir açar ve onaylar (planlama). */
async function newProductionOrder(recipeCode, tankCode, quantity) {
  const pl = await session("planlama");
  const versions = await pl.get(
    "/recipes/versions/?status=APPROVED&page_size=100",
  );
  const version = versions.results.find((v) => v.recipe_code === recipeCode);
  if (!version) throw new Error(`onaylı reçete yok: ${recipeCode}`);
  const tank = await byCode(pl, "equipment", tankCode);
  const kg = await byCode(pl, "units", "KG");
  const order = await pl.post("/production/orders/", {
    recipe_version: version.id,
    planned_quantity: quantity,
    unit: kg.id,
    planned_date: today(),
    equipment: tank.id,
    priority: 2,
    notes: NOTE,
  });
  return pl.post(`/production/orders/${order.id}/approve/`);
}

/** Depo emrin malzemesini öneriden hazırlar; `limit` verilirse yalnızca ilk satırları. */
async function pickProductionOrder(orderId, limit = Infinity) {
  const dp = await session("depo");
  let order = await dp.get(`/production/orders/${orderId}/`);
  if (order.status === "APPROVED")
    order = await dp.post(`/production/orders/${orderId}/start-prep/`);
  const rows = order.requirements
    .filter((r) => r.is_picked && !r.is_ready)
    .slice(0, limit);
  for (const row of rows) {
    const [best] = await dp.get(
      `/production/orders/${orderId}/pick-suggestions/?requirement=${row.id}`,
    );
    if (!best) throw new Error(`${row.material_code} için serbest stok yok`);
    await dp.post(`/production/orders/${orderId}/picks/`, {
      requirement: row.id,
      lot: best.lot,
      quantity: row.to_pick,
      from_location: best.location,
    });
  }
  if (limit === Infinity)
    await dp.post(`/production/orders/${orderId}/mark-ready/`);
}

/** Üretim şarjı başlatır ve ilk `count` satırı tartar (hepsi tartılırsa şarjı bitirir). */
async function weighBatch(orderId, count = Infinity) {
  const ur = await session("uretim");
  const order = await ur.get(`/production/orders/${orderId}/`);
  let batch = await ur.post("/production/batches/", {
    order: orderId,
    equipment: order.equipment,
    planned_quantity: order.suggested_batch_quantity,
  });
  batch = await ur.get(`/production/batches/${batch.id}/`);
  const scales = await ur.get("/maintenance/calibration/");
  const scale = (qty) => {
    const usable = scales.filter((s) => s.status !== "OVERDUE" && !s.is_down);
    const big = usable.find((s) => /600/.test(s.equipment_name)) ?? usable[0];
    const small = usable.find((s) => /30 kg/.test(s.equipment_name)) ?? big;
    return Number(qty) > 25 ? big?.equipment : small?.equipment;
  };
  const pending = batch.lines
    .filter((l) => l.state === "pending")
    .slice(0, count);
  for (const line of pending) {
    await ur.post(`/production/batches/${batch.id}/consume/`, {
      requirement: line.requirement,
      lot: line.available[0].lot,
      quantity: line.planned_quantity,
      scale: line.is_water ? null : (scale(line.planned_quantity) ?? null),
    });
  }
  if (count === Infinity) {
    const output = String(Math.round(Number(batch.planned_quantity) * 0.985));
    batch = await ur.post(`/production/batches/${batch.id}/finish/`, {
      output_quantity: output,
      note: "",
    });
  }
  return batch;
}

/** Laboratuvar numunenin tüm testlerine spesifikasyon içinde sonuç girer; `outOfSpec` ilk sayısal testi dışarıda bırakır. */
async function enterResults(sampleId, { outOfSpec = false } = {}) {
  const lab = await session("laboratuvar");
  let sample = await lab.get(`/quality/samples/${sampleId}/`);
  let spoiled = !outOfSpec;
  for (const { line } of sample.lines) {
    const input = { spec_line: line.id };
    if (line.result_type === "NUMERIC") {
      const min = line.min_value === null ? null : Number(line.min_value);
      const max = line.max_value === null ? null : Number(line.max_value);
      let value = line.target_value !== null ? Number(line.target_value) : null;
      if (value === null)
        value =
          min !== null && max !== null ? (min + max) / 2 : (min ?? max ?? 1);
      if (!spoiled && (min !== null || max !== null)) {
        value = min !== null ? min * 0.98 : max * 1.02;
        spoiled = true;
      }
      input.numeric_value = value.toFixed(
        Math.max(line.decimal_places ?? 2, 2),
      );
    } else if (line.result_type === "PASS_FAIL") {
      input.passed = true;
    } else {
      input.text_value = line.text_expected || "Uygun";
    }
    sample = await lab.post(`/quality/samples/${sampleId}/results/`, input);
  }
  return sample;
}

async function releaseBulk(lotNo) {
  const lab = await session("laboratuvar");
  const queue = await lab.get(`/quality/samples/queue/?page_size=100`);
  const found = queue.results.find((s) => s.lot_no === lotNo);
  if (!found) throw new Error(`${lotNo} için numune yok`);
  const sample = await enterResults(found.id);
  await lab.post(`/quality/samples/${found.id}/decide/`, {
    decision: "RELEASE",
    reason: "",
    release_location: sample.default_release_location,
  });
}

async function ensureReceipt() {
  const lab = await session("laboratuvar");
  const queue = await lab.get("/quality/samples/queue/?page_size=100");
  const decisions = await lab.get(
    "/quality/decisions/?approval_status=PENDING",
  );
  const incoming = queue.results.filter(
    (s) => s.stage === "INCOMING" && s.status === "PENDING",
  );
  if (incoming.length >= 1 && decisions.count > 0) return;

  const dp = await session("depo");
  const supplier = await byCode(dp, "suppliers", "T-KIMYA");
  const sles = await byCode(dp, "materials", "SLES");
  const las = await byCode(dp, "materials", "LAS");
  const kg = await byCode(dp, "units", "KG");
  const quarantine = await byCode(dp, "locations", "KARANTINA");
  const storage = await byCode(dp, "locations", "HM-DEPO");
  const line = (material, quantity, lotNo) => ({
    material: material.id,
    quantity,
    unit: kg.id,
    supplier_lot_no: lotNo,
    manufactured_at: inDays(-10),
    expiry_date: inDays(720),
  });
  const receipt = await dp.post("/inventory/goods-receipts/", {
    supplier: supplier.id,
    receipt_date: today(),
    delivery_note_no: `IRS-${Date.now() % 100000}`,
    quarantine_location: quarantine.id,
    storage_location: storage.id,
    note: NOTE,
    lines: [
      line(sles, "1000", "AK-2026-118"),
      line(las, "2000", "AK-2026-119"),
    ],
  });
  await dp.post(`/inventory/goods-receipts/${receipt.id}/post/`);

  if (decisions.count === 0) {
    // LAS numunesinde spesifikasyon dışı sonuç ve şartlı kabul: yönetim onayı ekranı için.
    const fresh = await lab.get("/quality/samples/queue/?page_size=100");
    const lasSample = fresh.results.find(
      (s) =>
        s.stage === "INCOMING" &&
        s.material_code === "LAS" &&
        s.status === "PENDING",
    );
    if (lasSample) {
      const sample = await enterResults(lasSample.id, { outOfSpec: true });
      await lab.post(`/quality/samples/${lasSample.id}/decide/`, {
        decision: "CONDITIONAL_RELEASE",
        reason:
          "Aktif madde sınırın biraz altında; seyreltmede telafi edilir. (Kılavuz örneği)",
        release_location: sample.default_release_location,
      });
    }
  }
}

async function ensurePrepOrder() {
  const pl = await session("planlama");
  const open = await pl.get(
    "/production/orders/?status=APPROVED&status=MATERIAL_PREP",
  );
  if (open.count > 0) return;
  const order = await newProductionOrder("REC-BULASIK", "KT-01", "2000");
  await pickProductionOrder(order.id, 2);
}

async function ensureWeighing() {
  const ur = await session("uretim");
  const running = await ur.get("/production/batches/?status=IN_PROGRESS");
  if (running.count > 0) return;
  const order = await newProductionOrder("REC-BULASIK", "KT-01", "1000");
  await pickProductionOrder(order.id);
  await weighBatch(order.id, 3);
}

async function ensureFillingRun() {
  const dl = await session("dolum");
  const running = await dl.get("/filling/runs/?status=IN_PROGRESS");
  if (running.count > 0) return;
  // Serbest bulk: yüzey temizleyici şarjı üretilir ve laboratuvar serbest bırakır.
  const order = await newProductionOrder("REC-YUZEY", "KT-02", "1000");
  await pickProductionOrder(order.id);
  const batch = await weighBatch(order.id);
  await releaseBulk(batch.output_lot_no);

  const pl = await session("planlama");
  const product = await byCode(pl, "materials", "YUZEY-CAM-1000");
  const line = await byCode(pl, "equipment", "DH-01");
  const output = await byCode(pl, "locations", "MAMUL-DEPO");
  let filling = await pl.post("/filling/orders/", {
    finished_product: product.id,
    planned_units: 600,
    filling_line: line.id,
    output_location: output.id,
    planned_date: today(),
    notes: NOTE,
  });
  filling = await pl.post(`/filling/orders/${filling.id}/approve/`);

  const dp = await session("depo");
  filling = await dp.post(`/filling/orders/${filling.id}/start-prep/`);
  for (const row of filling.requirements.filter((r) => !r.is_ready)) {
    const [best] = await dp.get(
      `/filling/orders/${filling.id}/pick-suggestions/?requirement=${row.id}`,
    );
    await dp.post(`/filling/orders/${filling.id}/picks/`, {
      requirement: row.id,
      lot: best.lot,
      quantity: row.to_pick,
      from_location: best.location,
    });
  }
  await dp.post(`/filling/orders/${filling.id}/mark-ready/`);

  let run = await dl.post("/filling/runs/", { order: filling.id });
  run = await dl.get(`/filling/runs/${run.id}/`);
  const bulk =
    run.bulk_lots.find((b) => b.lot_no === batch.output_lot_no) ??
    run.bulk_lots[0];
  await dl.post(`/filling/runs/${run.id}/consume-bulk/`, {
    lot: bulk.lot,
    quantity: "300",
  });
  for (const stock of run.line_stock.slice(0, 2)) {
    await dl.post(`/filling/runs/${run.id}/scan/`, { lot_no: stock.lot_no });
  }
  await dl.post(`/filling/runs/${run.id}/scrap/`, {
    kind: "FINISHED",
    reason_code: "UNDERFILL",
    quantity: "2",
  });
}

async function ensurePurchaseOrder() {
  const sa = await session("satin_alma");
  const pending = await sa.get("/purchasing/orders/?status=PENDING_APPROVAL");
  if (pending.count > 0) return;
  const supplier = await byCode(sa, "suppliers", "T-KIMYA");
  const las = await byCode(sa, "materials", "LAS");
  const kg = await byCode(sa, "units", "KG");
  const order = await sa.post("/purchasing/orders/", {
    supplier: supplier.id,
    order_date: today(),
    currency: "TRY",
    exchange_rate: "1",
    notes: NOTE,
    lines: [
      {
        material: las.id,
        quantity: "3000",
        unit: kg.id,
        unit_price: "46.50",
        expected_date: inDays(10),
      },
    ],
  });
  await sa.post(`/purchasing/orders/${order.id}/submit/`);
}

async function ensureProblemReport() {
  const admin = await session("admin");
  const list = await admin.get("/golive/problems/");
  if (list.results.some((p) => p.has_screenshot)) return;
  const dl = await session("dolum");
  await dl.page.setViewportSize(TABLET);
  await go(dl.page, "/dolum/hat");
  const screenshot = await dl.page.screenshot({ type: "jpeg", quality: 60 });
  await dl.post("/golive/problems/", {
    multipart: {
      description:
        "Dolum hattında koli etiketi yazdırılamıyor, hata mesajı çıkmadı. (Kılavuz örneği)",
      page_url: `${BASE}/dolum/hat`,
      page_title: "Dolum",
      user_agent: "kilavuz-ekran-goruntuleri",
      screen: "1024x768",
      screenshot: {
        name: "ekran.jpg",
        mimeType: "image/jpeg",
        buffer: screenshot,
      },
    },
  });
}

const SETUP = [
  ["mal kabul ve numuneler", ensureReceipt],
  ["malzeme hazırlamada emir", ensurePrepOrder],
  ["tartımı süren şarj", ensureWeighing],
  ["dolumu süren parti", ensureFillingRun],
  ["onay bekleyen satın alma siparişi", ensurePurchaseOrder],
  ["sorun bildirimi", ensureProblemReport],
];

// --- ekran görüntüleri ---------------------------------------------------------------------------

/** Sayfa yüklensin: "Yükleniyor…" kaybolsun, ağ dursun. */
async function settle(page, text) {
  await page
    .waitForLoadState("networkidle", { timeout: 15000 })
    .catch(() => {});
  if (text)
    await page
      .getByText(text, { exact: false })
      .first()
      .waitFor({ timeout: 15000 });
  await page
    .getByText("Yükleniyor…")
    .first()
    .waitFor({ state: "hidden", timeout: 15000 })
    .catch(() => {});
  await page.waitForTimeout(700);
}

async function go(page, url, text) {
  await page.goto(`${BASE}${url}`);
  await settle(page, text);
}

/**
 * Listede eşleşen (yoksa ilk) satıra tıklar ve detay sayfasının açılmasını bekler. `match` metinse
 * satırın içinde geçer; düzenli ifadeyse satırdaki bir öğenin (ör. durum rozeti) metnine tam uyar.
 * Rozetler ekranda büyük harfle görünür ama DOM'daki metin "Devam ediyor" gibidir.
 */
async function openRow(page, url, match, expectPath) {
  await go(page, url);
  const rows = page.locator("main table tbody tr");
  const row = !match
    ? rows.first()
    : match instanceof RegExp
      ? rows.filter({ has: page.getByText(match) }).first()
      : rows.filter({ hasText: match }).first();
  await row.waitFor({ timeout: 15000 });
  await row.click();
  if (expectPath)
    await page.waitForURL((u) => expectPath.test(u.pathname), {
      timeout: 15000,
    });
  await settle(page);
}

/** Metni (başlık, bölüm adı) görünür alanın üstüne kaydırır. */
async function scrollTo(page, text) {
  const target = page.getByText(text, { exact: true }).first();
  await target.waitFor({ timeout: 15000 });
  await target.evaluate((el) => el.scrollIntoView({ block: "start" }));
  await page.evaluate(() => window.scrollBy(0, -80));
  await page.waitForTimeout(400);
}

async function scrollTop(page) {
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(300);
}

/** Açılış stoku şablonunu oturumla indirir ve geçici dosyaya yazar (önizleme için; aktarılmaz). */
async function openingTemplate(s) {
  const response = await s.context.request.get(
    `${BASE}/api/v1/inventory/opening/template/`,
  );
  if (!response.ok())
    throw new Error(`şablon indirilemedi (HTTP ${response.status()})`);
  const file = path.join(
    await mkdtemp(path.join(tmpdir(), "kilavuz-")),
    "acilis-stoku.xlsx",
  );
  await writeFile(file, await response.body());
  return file;
}

// Her görüntü: ad (kılavuzdaki /kilavuz/<ad>.jpg), kullanıcı (rol kodu; null = giriş yapmamış),
// tablet (1024x768) ya da ofis (1366x800; `viewport` ile özel boyut) ve ekranı hazırlayan adımlar.
const SHOTS = [
  // genel.md
  {
    name: "genel-giris",
    user: null,
    // Marka paneli 992 px üstünde görünür; tablet boyutu iki paneli de okunur ölçekte gösterir.
    tablet: true,
    run: async (page) => go(page, "/login", "Giriş yap"),
  },
  {
    name: "genel-gorevlerim",
    user: "laboratuvar",
    run: async (page) => go(page, "/", "Görevlerim"),
  },
  {
    name: "genel-bildirimler",
    user: "depo",
    run: async (page) => {
      await go(page, "/", "Görevlerim");
      await page
        .getByRole("button", { name: /bildirim/i })
        .first()
        .click();
      await page.waitForTimeout(1200);
    },
  },
  {
    name: "genel-yorumlar",
    user: "sevkiyat",
    run: async (page) => {
      await openRow(
        page,
        "/sevkiyat/siparisler",
        null,
        /\/sevkiyat\/siparisler\/\d+/,
      );
      const box = page.getByPlaceholder(/Yorum yazın/);
      await box.scrollIntoViewIfNeeded();
      await box.fill("Teslimat sabah 09:00'da olsun, ");
      await box.press("End");
      await box.type("@dep", { delay: 80 });
      await page.waitForTimeout(1200);
      await box.evaluate((el) => el.scrollIntoView({ block: "center" }));
      await page.waitForTimeout(300);
    },
  },
  {
    name: "genel-sorun-bildir",
    user: "dolum",
    tablet: true,
    run: async (page) => {
      await go(page, "/dolum/hat", "Dolum hattı");
      await page.getByRole("button", { name: "Sorun bildir" }).click();
      const dialog = page.getByRole("dialog");
      await dialog.waitFor();
      await dialog
        .getByLabel("Açıklama")
        .fill(
          "Koli etiketi yazdırılamıyor; Etiket yazdır'a basınca hiçbir şey olmuyor.",
        );
      await page.waitForTimeout(1500);
    },
  },
  {
    name: "genel-yardim",
    user: "depo",
    run: async (page) => go(page, "/yardim/genel", "Rolünüzün kılavuzları"),
  },

  // depo.md
  {
    name: "depo-stok",
    user: "depo",
    run: async (page) => go(page, "/depo/stok", "Stok sorgu"),
  },
  {
    name: "depo-mal-kabul",
    user: "depo",
    run: async (page) =>
      openRow(page, "/depo/mal-kabul", "MK-", /\/depo\/mal-kabul\/\d+/),
  },
  {
    name: "depo-lot",
    user: "depo",
    run: async (page) =>
      openRow(page, "/depo/lotlar", /^Karantina$/, /\/depo\/lotlar\/\d+/),
  },
  {
    name: "depo-hazirlama",
    user: "depo",
    tablet: true,
    run: async (page) => {
      await openRow(page, "/uretim/hazirlama", "UE-", /\/hazirlama$/);
      await scrollTop(page);
    },
  },
  {
    name: "depo-hazirlama-okut",
    user: "depo",
    tablet: true,
    run: async (page) => {
      await openRow(page, "/uretim/hazirlama", "UE-", /\/hazirlama$/);
      await scrollTo(page, "Lot barkodu");
    },
  },
  {
    name: "depo-toplama",
    user: "depo",
    tablet: true,
    run: async (page) => {
      await go(page, "/sevkiyat/toplama", "Toplama");
      await page
        .getByText(/^SV-\d{4}-\d+$/)
        .first()
        .click();
      await page.waitForURL(/\/toplama$/);
      await settle(page, "Lot okut");
      await scrollTo(page, "Lot okut");
    },
  },

  // planlama.md
  {
    name: "planlama-emir-yeni",
    user: "planlama",
    run: async (page) => go(page, "/uretim/emirler/yeni", "Yeni üretim emri"),
  },
  {
    name: "planlama-emir",
    user: "planlama",
    run: async (page) =>
      openRow(page, "/uretim/emirler", "UE-", /\/uretim\/emirler\/\d+$/),
  },
  {
    name: "planlama-dolum-emri",
    user: "planlama",
    run: async (page) =>
      openRow(page, "/dolum/emirler", "DO-", /\/dolum\/emirler\/\d+$/),
  },
  {
    name: "planlama-raporlar",
    user: "planlama",
    run: async (page) => go(page, "/raporlar/panolar", "Panolar"),
  },

  // uretim.md (tablet)
  {
    name: "uretim-sarjlar",
    user: "uretim",
    tablet: true,
    run: async (page) => go(page, "/uretim/sarjlar", "Şarj başlat"),
  },
  {
    name: "uretim-sarj",
    user: "uretim",
    tablet: true,
    run: async (page) => {
      await openRow(
        page,
        "/uretim/sarjlar",
        /^Devam ediyor$/,
        /\/uretim\/sarjlar\/\d+/,
      );
      await settle(page, "Tartımı kaydet");
      await scrollTop(page);
    },
  },
  {
    name: "uretim-tartim",
    user: "uretim",
    tablet: true,
    run: async (page) => {
      await openRow(
        page,
        "/uretim/sarjlar",
        /^Devam ediyor$/,
        /\/uretim\/sarjlar\/\d+/,
      );
      await settle(page, "Tartımı kaydet");
      await scrollTo(page, "Talimat");
      await page.evaluate(() => window.scrollBy(0, -70));
    },
  },
  {
    name: "uretim-sarj-bitir",
    user: "uretim",
    tablet: true,
    run: async (page) => {
      await openRow(
        page,
        "/uretim/sarjlar",
        /^Devam ediyor$/,
        /\/uretim\/sarjlar\/\d+/,
      );
      await settle(page, "Tartımı kaydet");
      await page.getByRole("button", { name: "Şarjı bitir" }).first().click();
      await page.getByRole("dialog").waitFor();
      await page.waitForTimeout(800);
    },
  },

  // laboratuvar.md
  {
    name: "lab-kuyruk",
    user: "laboratuvar",
    run: async (page) => go(page, "/kalite/kuyruk", "Numune kuyruğu"),
  },
  {
    name: "lab-numune",
    user: "laboratuvar",
    run: async (page) =>
      openRow(page, "/kalite/kuyruk", /^Bekliyor$/, /\/kalite\/numuneler\/\d+/),
  },
  {
    name: "lab-karar",
    user: "laboratuvar",
    run: async (page) => {
      await openRow(
        page,
        "/kalite/kuyruk",
        /^Bekliyor$/,
        /\/kalite\/numuneler\/\d+/,
      );
      await page.getByRole("button", { name: "Karar ver" }).first().click();
      await page.getByRole("dialog").waitFor();
      await page.waitForTimeout(800);
    },
  },
  {
    name: "lab-izlenebilirlik",
    user: "laboratuvar",
    run: async (page) => {
      await go(page, "/izlenebilirlik", "Geri izleme");
      await page.getByRole("tab", { name: "İleri izleme" }).click();
      await page.waitForTimeout(500);
      const search = page.getByPlaceholder(/Lot no ya da malzeme/).first();
      await search.click();
      await search.fill("ACILIS-SLES");
      await page
        .getByRole("option", { name: /ACILIS-SLES/ })
        .first()
        .click();
      await settle(page);
      await page.waitForTimeout(1000);
    },
  },

  // dolum.md (tablet)
  {
    name: "dolum-hat",
    user: "dolum",
    tablet: true,
    run: async (page) => go(page, "/dolum/hat", "Partiyi başlat"),
  },
  {
    name: "dolum-parti",
    user: "dolum",
    tablet: true,
    run: async (page) => {
      await openRow(page, "/dolum/hat", /^Dolumda$/, /\/dolum\/partiler\/\d+/);
      await scrollTop(page);
    },
  },
  {
    name: "dolum-ambalaj",
    user: "dolum",
    tablet: true,
    run: async (page) => {
      await openRow(page, "/dolum/hat", /^Dolumda$/, /\/dolum\/partiler\/\d+/);
      await scrollTo(page, "Ambalaj lotları");
    },
  },
  {
    name: "dolum-fire",
    user: "dolum",
    tablet: true,
    run: async (page) => {
      await openRow(page, "/dolum/hat", /^Dolumda$/, /\/dolum\/partiler\/\d+/);
      await scrollTo(page, "Fire");
    },
  },

  // sevkiyat.md
  {
    name: "sevkiyat-siparis-yeni",
    user: "sevkiyat",
    run: async (page) =>
      go(page, "/sevkiyat/siparisler/yeni", "Yeni satış siparişi"),
  },
  {
    name: "sevkiyat-siparis",
    user: "sevkiyat",
    run: async (page) =>
      openRow(
        page,
        "/sevkiyat/siparisler",
        /^Onaylandı$/,
        /\/sevkiyat\/siparisler\/\d+/,
      ),
  },
  {
    name: "sevkiyat-sevkiyat",
    user: "sevkiyat",
    run: async (page) =>
      openRow(
        page,
        "/sevkiyat/sevkiyatlar",
        /^Sevk edildi$/,
        /\/sevkiyat\/sevkiyatlar\/\d+/,
      ),
  },

  // satin-alma.md
  {
    name: "satin-alma-siparisler",
    user: "satin_alma",
    run: async (page) => go(page, "/satin-alma/siparisler", "Yeni sipariş"),
  },
  {
    name: "satin-alma-siparis-yeni",
    user: "satin_alma",
    run: async (page) => {
      await go(page, "/satin-alma/siparisler", "Yeni sipariş");
      await page.getByRole("button", { name: "Yeni sipariş" }).click();
      await settle(page, "Yeni satın alma siparişi");
    },
  },
  {
    name: "satin-alma-siparis",
    user: "satin_alma",
    run: async (page) =>
      openRow(
        page,
        "/satin-alma/siparisler",
        "SA-",
        /\/satin-alma\/siparisler\/\d+/,
      ),
  },

  // yonetim.md
  {
    name: "yonetim-pano",
    user: "yonetim",
    run: async (page) => go(page, "/raporlar/panolar", "Yönetim panosu"),
  },
  {
    name: "yonetim-sartli-kabul",
    user: "yonetim",
    run: async (page) => go(page, "/kalite/onay", "Şartlı kabul onayı"),
  },
  {
    name: "yonetim-siparis-onay",
    user: "yonetim",
    run: async (page) =>
      openRow(
        page,
        "/satin-alma/siparisler",
        /^Yönetim onayında$/,
        /\/satin-alma\/siparisler\/\d+/,
      ),
  },
  {
    name: "yonetim-maliyet",
    user: "yonetim",
    run: async (page) => go(page, "/maliyet/oranlar", "Oran ekle"),
  },

  // admin.md
  {
    name: "admin-kullanicilar",
    user: "admin",
    run: async (page) => go(page, "/sistem/kullanicilar", "Yeni kullanıcı"),
  },
  {
    name: "admin-sorunlar",
    user: "admin",
    run: async (page) => go(page, "/gecis/sorunlar", "Sorun bildirimleri"),
  },
  {
    name: "admin-sorun",
    user: "admin",
    run: async (page) =>
      openRow(page, "/gecis/sorunlar", "SB-", /\/gecis\/sorunlar\/\d+/),
  },
  {
    name: "admin-etiket-ayarlari",
    user: "admin",
    run: async (page) =>
      go(page, "/ana-veriler/etiket-ayarlari", "GS1 firma öneki"),
  },

  // gecis.md
  {
    name: "gecis-hazirlik",
    user: "yonetim",
    run: async (page) => go(page, "/gecis/hazirlik", "Canlı başlangıç tarihi"),
  },
  {
    name: "gecis-acilis",
    user: "depo",
    run: async (page, s) => {
      const file = await openingTemplate(s);
      // Düğme Stok sorgu sekmesindedir.
      await go(page, "/depo/stok", "Açılış stoku içe aktar");
      await page
        .getByRole("button", { name: "Açılış stoku içe aktar" })
        .click();
      const dialog = page.getByRole("dialog");
      await dialog.waitFor();
      await dialog.locator('input[type="file"]').setInputFiles(file);
      await dialog.getByRole("button", { name: "Önizle" }).click();
      await dialog.locator("table").first().waitFor({ timeout: 15000 });
      await page.waitForTimeout(800);
      await rm(path.dirname(file), { recursive: true, force: true });
      // "Aktar" düğmesine asla basılmaz.
    },
  },
  {
    name: "gecis-karsilastirma",
    user: "depo",
    run: async (page) =>
      openRow(
        page,
        "/gecis/karsilastirma",
        "SK-",
        /\/gecis\/karsilastirma\/\d+/,
      ),
  },
];

async function shoot(shot) {
  const s = shot.user ? await session(shot.user) : await anonymous();
  const { page } = s;
  await page.setViewportSize(shot.viewport ?? (shot.tablet ? TABLET : OFFICE));
  await shot.run(page, s);
  if (shot.user && page.url().includes("/login"))
    throw new Error("giriş sayfasına düştü");
  await page.mouse.move(0, 0);
  await page.screenshot({
    path: path.join(OUT, `${shot.name}.jpg`),
    type: "jpeg",
    quality: 70,
    fullPage: false,
  });
  // Açık pencere ya da menü sonraki görüntüye taşınmasın.
  await page.keyboard.press("Escape").catch(() => {});
}

async function main() {
  await mkdir(OUT, { recursive: true });
  browser = await chromium.launch();
  let failed = 0;
  try {
    // Gerçek sistemde örnek kayıt açmamak için: canlı başlangıç tarihi girilmişse dur.
    const golive = await (await session("yonetim")).get("/golive/go-live/");
    if (golive.go_live_date)
      throw new Error(
        `Canlı başlangıç tarihi girilmiş (${golive.go_live_date}); betik yalnızca demo verisinde çalışır.`,
      );
    for (const [label, step] of SETUP) {
      try {
        await step();
        console.log(`hazır: ${label}`);
      } catch (error) {
        warn(`${label} hazırlanamadı: ${error.message}`);
      }
    }
    const shots = ONLY.length
      ? SHOTS.filter((s) => ONLY.includes(s.name))
      : SHOTS;
    for (const shot of shots) {
      try {
        await shoot(shot);
        console.log(`✓ ${shot.name}.jpg`);
      } catch (error) {
        failed++;
        warn(`${shot.name}.jpg alınamadı: ${error.message.split("\n")[0]}`);
      }
    }
  } finally {
    await browser.close();
  }
  if (failed) {
    console.error(`${failed} görüntü alınamadı.`);
    process.exit(1);
  }
}

await main();
