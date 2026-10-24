import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../api/auth";
import * as masterdataApi from "../../api/masterdata";
import * as reportingApi from "../../api/reporting";
import type { ManagementDashboard, ReportInfo, ReportJob, ReportPage } from "../../api/reporting";
import * as workflowApi from "../../api/workflow";
import { page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";
import { defaultParams, formatValue } from "./format";

vi.mock("../../api/auth");
vi.mock("../../api/reporting", async (importOriginal) => ({
  ...(await importOriginal<typeof reportingApi>()),
  listDashboards: vi.fn(),
  getDashboard: vi.fn(),
  listReports: vi.fn(),
  getReport: vi.fn(),
  exportReport: vi.fn(),
  listJobs: vi.fn(),
}));
vi.mock("../../api/masterdata", async (importOriginal) => ({
  ...(await importOriginal<typeof masterdataApi>()),
  listRecords: vi.fn(),
}));
vi.mock("../../api/workflow");

/** 03.10–16.10: son iki gün dökme (1.200 + 1.950 KG), bugün 975 adet mamul. */
function daily(): ManagementDashboard["daily"] {
  return Array.from({ length: 14 }, (_, i) => ({
    date: `2026-10-${String(3 + i).padStart(2, "0")}`,
    bulk:
      i === 13
        ? [{ unit: "KG", quantity: "1950.0000" }]
        : i === 12
          ? [{ unit: "KG", quantity: "1200.0000" }]
          : [],
    units: i === 13 ? 975 : 0,
  }));
}

function management(extra: Partial<ManagementDashboard> = {}): ManagementDashboard {
  const period = { bulk: [{ unit: "KG", quantity: "1950.0000", batches: 2 }], units: 975, runs: 1 };
  return {
    date: "2026-10-16",
    approvals: {
      conditional_acceptance: { count: 2, oldest_wait_hours: "5.25" },
      purchase_orders: { count: 1, total_try: "48500.00" },
    },
    production: { today: period, week: period },
    daily: daily(),
    shipping: { dispatched_today: 3, late_orders: 2 },
    open_orders: {
      production: [{ status: "IN_PRODUCTION", label: "Üretimde", count: 2 }],
      filling: [],
      sales: [],
    },
    qc_pending: { sample_count: 3, lot_count: 2, avg_wait_hours: "4.50", max_wait_hours: "9.00" },
    scrap: { days: 7, good_units: "975", scrap_units: "25", rate: "2.50" },
    critical_stock: {
      count: 1,
      items: [
        { material_id: 1, material: "LAS — LAS %96", stock: "10", min_stock: "500", unit: "KG" },
      ],
    },
    expiring_lots: { days: 30, count: 0, expired_count: 0, items: [] },
    tasks: {
      overdue_total: 4,
      by_role: [{ role: "depo", label: "Depo", open: 7, overdue: 4, max_delay_hours: "12.00" }],
    },
    maintenance: {
      days: 7,
      open_work_orders: 2,
      due_plans: 1,
      overdue_plans: 1,
      open_downtimes: 0,
      downtime_minutes: 200,
    },
    hse: { days: 30, incidents: 1, injuries: 0, open_incidents: 1 },
    stock_value: null,
    ...extra,
  };
}

const STOCK: ReportInfo = {
  code: "stock-movements",
  title: "Stok hareketleri",
  description: "Hareket defteri",
  filters: ["date_from", "date_to", "movement_type"],
  default_days: 30,
  columns: [],
};

function reportPage(extra: Partial<ReportPage> = {}): ReportPage {
  return {
    code: "stock-movements",
    title: "Stok hareketleri",
    columns: [
      { key: "lot_no", label: "Lot no", kind: "text" },
      { key: "quantity", label: "Miktar", kind: "number" },
      { key: "created_at", label: "Zaman", kind: "datetime" },
    ],
    summary: [{ key: "row_count", label: "Hareket", value: 1, kind: "number" }],
    filters: {},
    count: 1,
    sync_limit: 5000,
    results: [
      { lot_no: "H-261016-001", quantity: "-1250.5000", created_at: "2026-10-16T09:00:00Z" },
    ],
    ...extra,
  };
}

function job(extra: Partial<ReportJob> = {}): ReportJob {
  return {
    id: 5,
    report_code: "stock-movements",
    title: "Stok hareketleri",
    file_format: "xlsx",
    file_format_display: "Excel",
    params: {},
    status: "DONE",
    status_display: "Hazır",
    file_name: "stock-movements.xlsx",
    row_count: 12000,
    error: "",
    created_at: "2026-10-16T09:00:00Z",
    started_at: null,
    finished_at: null,
    expires_at: "2026-10-23T09:00:00Z",
    can_download: true,
    ...extra,
  };
}

beforeEach(() => {
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  vi.mocked(masterdataApi.listRecords).mockResolvedValue(page([]));
  vi.mocked(reportingApi.listDashboards).mockResolvedValue([
    { code: "management", title: "Yönetim panosu" },
  ]);
  vi.mocked(reportingApi.getDashboard).mockResolvedValue(management());
  vi.mocked(reportingApi.listReports).mockResolvedValue([STOCK]);
  vi.mocked(reportingApi.getReport).mockResolvedValue(reportPage());
  vi.mocked(reportingApi.listJobs).mockResolvedValue(page([job()]));
});

describe("panolar", () => {
  it("yönetim panosu onay bekleyenleri, dikkat gerektirenleri ve bugünü gösterir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    renderApp("/raporlar");
    expect(await screen.findByText("Onayınızı bekleyenler")).toBeInTheDocument();
    // Onay bekleyenler: şartlı kabul, limit üstü sipariş (TL), açık İSG olayı.
    expect(screen.getByText("2 karar")).toBeInTheDocument();
    expect(screen.getByText("En eskisi 5,3 sa bekliyor")).toBeInTheDocument();
    expect(screen.getByText("1 sipariş")).toBeInTheDocument();
    expect(screen.getByText("48.500,00 TL")).toBeInTheDocument();
    expect(screen.getByText("Son 30 günde 1 olay · yaralanmalı 0")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Kararları aç" })).toHaveAttribute(
      "href",
      "/kalite/onay",
    );
    expect(screen.getByRole("link", { name: "Siparişleri aç" })).toHaveAttribute(
      "href",
      "/satin-alma/siparisler",
    );
    // Dikkat gerektirenler: önce kritik, sonra uyarılar; satır ilgili listeye götürür.
    const stock = screen.getByRole("link", { name: /1 malzeme minimum stokun altında/ });
    expect(stock).toHaveAttribute("href", "/depo/stok");
    expect(stock).toHaveTextContent("Kritik");
    expect(screen.getByText("4 gecikmiş görev · en uzunu 12 sa (Depo)")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /2 siparişin istenen teslim tarihi geçti/ }),
    ).toHaveAttribute("href", "/sevkiyat/siparisler");
    expect(screen.getByText("1 bakım planının zamanı geçti")).toBeInTheDocument();
    // Bugün, fire ve duruş, iş yükü, açık emirler.
    expect(screen.getAllByText("1.950 KG").length).toBeGreaterThan(0);
    expect(screen.getByText("975 adet")).toBeInTheDocument();
    expect(screen.getByText("3 sevkiyat")).toBeInTheDocument();
    expect(screen.getByText("Geciken sipariş: 2")).toBeInTheDocument();
    expect(screen.getByText("2 lot")).toBeInTheDocument();
    expect(screen.getByText("%2,50")).toBeInTheDocument();
    expect(screen.getByText("3 sa 20 dk")).toBeInTheDocument();
    expect(screen.getByText("2 açık iş emri · süresi geçen plan: 1")).toBeInTheDocument();
    expect(screen.getByText("Üretimde 2")).toBeInTheDocument();
    expect(screen.getByText("LAS — LAS %96")).toBeInTheDocument();
  });

  it("planlama panoyu görür ama onay bağlantıları ve tutarlar yalnızca yönetimde", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    vi.mocked(reportingApi.getDashboard).mockResolvedValue(
      management({
        approvals: {
          conditional_acceptance: { count: 2, oldest_wait_hours: "5.25" },
          purchase_orders: { count: 1, total_try: null },
        },
      }),
    );
    renderApp("/raporlar");
    expect(await screen.findByText("Yönetim onayı bekleyenler")).toBeInTheDocument();
    expect(screen.getByText("1 sipariş")).toBeInTheDocument();
    expect(screen.queryByText("48.500,00 TL")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Kararları aç" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Siparişleri aç" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Olayları aç" })).toHaveAttribute(
      "href",
      "/isg/olaylar",
    );
    // Stok değeri yalnızca yönetime döner; planlamada kutu yok.
    expect(screen.queryByText("Stok değeri")).not.toBeInTheDocument();
  });

  it("dikkat gerektiren bir şey yoksa yolunda bilgisi gösterilir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    vi.mocked(reportingApi.getDashboard).mockResolvedValue(
      management({
        critical_stock: { count: 0, items: [] },
        tasks: { overdue_total: 0, by_role: [] },
        shipping: { dispatched_today: 0, late_orders: 0 },
        maintenance: {
          days: 7,
          open_work_orders: 0,
          due_plans: 0,
          overdue_plans: 0,
          open_downtimes: 0,
          downtime_minutes: 0,
        },
      }),
    );
    renderApp("/raporlar");
    expect(await screen.findByText("Dikkat gerektiren bir durum yok.")).toBeInTheDocument();
    expect(screen.getByText("Yolunda")).toBeInTheDocument();
  });

  it("QC'de 24 saatten uzun bekleyen numune ve geçmiş SKT uyarı olarak çıkar", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    vi.mocked(reportingApi.getDashboard).mockResolvedValue(
      management({
        qc_pending: { sample_count: 1, lot_count: 1, avg_wait_hours: "60", max_wait_hours: "60" },
        expiring_lots: { days: 30, count: 1, expired_count: 1, items: [] },
      }),
    );
    renderApp("/raporlar");
    expect(
      await screen.findByRole("link", { name: /QC'de bekleyen numune var · en uzunu 3 gün/ }),
    ).toHaveAttribute("href", "/kalite/numuneler");
    expect(screen.getByRole("link", { name: /1 lotun son kullanma tarihi geçti/ })).toHaveAttribute(
      "href",
      "/depo/lotlar",
    );
  });

  it("son 14 gün grafiği tablo olarak da okunur; dökme ve mamul ayrı seridir", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    renderApp("/raporlar");
    expect(await screen.findByText("Son 14 gün üretim")).toBeInTheDocument();
    expect(screen.getByText("Toplam 3.150 KG")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Tablo" }));
    expect(screen.getByText("16.10.2026 Cuma")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Dökme (KG)" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "1.200 KG" })).toBeInTheDocument();
    await user.click(screen.getByText("Mamul (adet)"));
    expect(screen.getByText("Toplam 975 adet")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "975 adet" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Grafik" }));
    expect(screen.queryByRole("cell", { name: "975 adet" })).not.toBeInTheDocument();
  });

  it("stok değeri türlere göre gösterilir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    vi.mocked(reportingApi.getDashboard).mockResolvedValue(
      management({
        stock_value: {
          total: "1086680.00",
          by_type: [
            { material_type: "PACKAGING", value: "186680.00" },
            { material_type: "RAW", value: "900000.00" },
          ],
          has_uncosted: true,
        },
      }),
    );
    renderApp("/raporlar/panolar");
    expect(await screen.findByText("1.086.680,00 TL")).toBeInTheDocument();
    expect(screen.getByText("900.000,00 TL")).toBeInTheDocument();
    // En değerli tür önce.
    const types = screen.getAllByText(/^(Hammadde|Ambalaj)$/).map((node) => node.textContent);
    expect(types).toEqual(["Hammadde", "Ambalaj"]);
    expect(screen.getByText("Maliyeti olmayan lotlar değere katılmadı.")).toBeInTheDocument();
  });

  it("rolüne pano açık değilse bilgi verir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("dolum"));
    vi.mocked(reportingApi.listDashboards).mockResolvedValue([]);
    renderApp("/raporlar");
    expect(await screen.findByText("Rolünüze açık bir pano yok.")).toBeInTheDocument();
  });
});

describe("açılış ekranı", () => {
  it("yönetim rolü yönetim panosuyla açılır; Görevlerim menüde kalır", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    const { router } = renderApp("/");
    expect(await screen.findByRole("heading", { name: "Yönetim panosu" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/pano");
    expect(screen.getByText(/Merhaba, Deneme Kullanıcı/)).toBeInTheDocument();
    expect(await screen.findByText("2 karar")).toBeInTheDocument();
    expect(reportingApi.getDashboard).toHaveBeenCalledWith("management");
    expect(screen.getByRole("link", { name: "Görevlerim" })).toHaveAttribute("href", "/gorevlerim");
  });

  it("diğer roller Görevlerim'le açılır; panoyu menüde görmez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    const { router } = renderApp("/");
    expect(await screen.findByRole("heading", { name: "Görevlerim" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/gorevlerim");
    expect(screen.queryByRole("link", { name: "Yönetim panosu" })).not.toBeInTheDocument();
  });

  it("admin Görevlerim'le açılır, panoyu menüden açar", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("admin"));
    const { router } = renderApp("/");
    expect(await screen.findByRole("heading", { name: "Görevlerim" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/gorevlerim");
    expect(screen.getByRole("link", { name: "Yönetim panosu" })).toHaveAttribute("href", "/pano");
  });

  it("planlama panoyu Panolar'da görür; /pano adresi yönetime özeldir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    renderApp("/pano");
    expect(await screen.findByText("Yetkiniz yok")).toBeInTheDocument();
  });
});

describe("raporlar", () => {
  it("rapor sütunları Türkçe biçimle gösterilir, Excel indirilir", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    vi.mocked(reportingApi.exportReport).mockResolvedValue({ kind: "file", fileName: "a.xlsx" });
    renderApp("/raporlar/raporlar");
    expect(await screen.findByText("H-261016-001")).toBeInTheDocument();
    expect(screen.getByText("-1.250,5")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Excel" }));
    await waitFor(() =>
      expect(reportingApi.exportReport).toHaveBeenCalledWith(
        "stock-movements",
        "xlsx",
        expect.objectContaining({ date_from: expect.any(String) }),
      ),
    );
  });

  it("büyük rapor arka plana alınır", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    vi.mocked(reportingApi.getReport).mockResolvedValue(reportPage({ count: 12000 }));
    vi.mocked(reportingApi.exportReport).mockResolvedValue({ kind: "job", job: job() });
    renderApp("/raporlar/raporlar");
    expect(await screen.findByText(/arka planda hazırlanır/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "PDF" }));
    await waitFor(() =>
      expect(reportingApi.exportReport).toHaveBeenCalledWith(
        "stock-movements",
        "pdf",
        expect.any(Object),
      ),
    );
  });
});

describe("indirmeler", () => {
  it("hazır dosya indirme bağlantısıyla listelenir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    renderApp("/raporlar/indirmeler");
    expect(await screen.findByRole("link", { name: "İndir" })).toHaveAttribute(
      "href",
      "/api/v1/reporting/jobs/5/download/",
    );
    expect(screen.getByText("Hazır")).toBeInTheDocument();
  });
});

describe("biçim", () => {
  it("değer türüne göre biçimler", () => {
    expect(formatValue("12.5000", "percent")).toBe("12,50");
    expect(formatValue(true, "boolean")).toBe("Evet");
    expect(formatValue(null, "number")).toBe("");
    expect(formatValue("2026-10-16", "date")).toBe("16.10.2026");
  });

  it("tarihli raporda varsayılan son 30 gün", () => {
    const params = defaultParams(STOCK);
    expect(params.date_from && params.date_to && params.date_from < params.date_to).toBe(true);
    expect(defaultParams({ ...STOCK, default_days: null })).toEqual({});
  });
});
