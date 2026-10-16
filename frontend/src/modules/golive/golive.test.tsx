import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../api/auth";
import * as goliveApi from "../../api/golive";
import type { ReadinessCheck, StockComparison } from "../../api/golive";
import { httpError, page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";
import { parseMarkdown } from "../help/markdown";

vi.mock("../../api/auth");
vi.mock("../../api/golive", async (importOriginal) => ({
  ...(await importOriginal<typeof goliveApi>()),
  getReadiness: vi.fn(),
  getGoLive: vi.fn(),
  setGoLive: vi.fn(),
  listComparisons: vi.fn(),
  getComparison: vi.fn(),
  listComparisonLines: vi.fn(),
  createComparison: vi.fn(),
  reportProblem: vi.fn(),
}));
vi.mock("html2canvas-pro", () => ({ default: vi.fn().mockRejectedValue(new Error("jsdom")) }));

const checks: ReadinessCheck[] = [
  {
    code: "users",
    group: "Kullanıcılar",
    title: "Her rolde en az bir kullanıcı",
    status: "MISSING",
    detail: "Kullanıcısı olmayan roller var.",
    count: 3,
    link: "/admin/core/user/",
    items: ["Dolum", "Sevkiyat"],
    more: 0,
  },
  {
    code: "materials_raw",
    group: "Ana veriler",
    title: "Hammaddeler",
    status: "OK",
    detail: "40 aktif kayıt.",
    count: 40,
    link: "/ana-veriler/malzemeler",
    items: [],
    more: 0,
  },
];

const comparison: StockComparison = {
  id: 7,
  number: "SK-2026-00001",
  as_of_date: "2026-10-16",
  level: "MATERIAL",
  level_display: "Malzeme",
  only_file_materials: false,
  file_name: "stok.xlsx",
  note: "1. hafta",
  line_count: 12,
  difference_count: 2,
  created_at: "2026-10-16T17:00:00+03:00",
  created_by_name: "Depo Sorumlusu",
};

describe("canlıya geçiş ekranı", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(authApi.fetchCsrf).mockResolvedValue();
    vi.mocked(goliveApi.getReadiness).mockResolvedValue(checks);
    vi.mocked(goliveApi.getGoLive).mockResolvedValue({ go_live_date: null, opening_open: true });
    vi.mocked(goliveApi.listComparisons).mockResolvedValue(page([comparison]));
  });

  it("hazırlık listesini gruplarıyla gösterir; yönetim canlı tarihini girer", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    vi.mocked(goliveApi.setGoLive).mockResolvedValue({
      go_live_date: "2026-11-02",
      opening_open: true,
    });
    const { router } = renderApp("/gecis");

    const users = await screen.findByTestId("check-users");
    expect(router.state.location.pathname).toBe("/gecis");
    expect(within(users).getByText("Yapılmadı")).toBeInTheDocument();
    expect(within(users).getByText("Dolum, Sevkiyat")).toBeInTheDocument();
    expect(screen.getByText("Açılış stoku yüklemesi açık.")).toBeInTheDocument();

    const input = screen.getAllByLabelText("Canlı başlangıç tarihi")[0];
    await userEvent.type(input, "2026-11-02");
    await userEvent.click(screen.getByRole("button", { name: "Kaydet" }));
    await waitFor(() => expect(goliveApi.setGoLive).toHaveBeenCalledWith("2026-11-02"));
  });

  it("depo canlı tarihini değiştiremez, sorun bildirimleri sekmesini görmez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    renderApp("/gecis/hazirlik");

    await screen.findByTestId("check-users");
    expect(screen.getAllByLabelText("Canlı başlangıç tarihi")[0]).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Kaydet" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Sorun bildirimleri" })).not.toBeInTheDocument();
  });

  it("dolum rolü canlıya geçiş ekranına giremez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("dolum"));
    renderApp("/gecis");
    expect(await screen.findByText(/yetkiniz yok/i)).toBeInTheDocument();
  });

  it("stok karşılaştırması: hatalı satırları gösterir, başarılıysa sonuca gider", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    vi.mocked(goliveApi.createComparison)
      .mockRejectedValueOnce(
        httpError(400, {
          code: "import_has_errors",
          detail: "Dosyada hatalı satırlar var",
          report: {
            kind: "stock_comparison",
            total: 1,
            valid: 0,
            invalid: 1,
            to_create: 1,
            to_update: 0,
            file_errors: [],
            rows: [
              {
                row: 2,
                code: "",
                action: "create",
                errors: [{ column: "Malzeme kodu", message: "Malzeme bulunamadı ya da pasif" }],
              },
            ],
            imported: false,
          },
        }),
      )
      .mockResolvedValueOnce(comparison);
    vi.mocked(goliveApi.getComparison).mockResolvedValue(comparison);
    vi.mocked(goliveApi.listComparisonLines).mockResolvedValue(
      page([
        {
          id: 1,
          material: 5,
          material_code: "HM-LAS",
          material_name: "LAS",
          lot_no: "",
          location: null,
          location_code: "",
          file_quantity: "90.0000",
          system_quantity: "100.0000",
          difference: "10.0000",
          unit: "KG",
          in_file: true,
        },
      ]),
    );
    const { router } = renderApp("/gecis/karsilastirma");

    expect(await screen.findByText("SK-2026-00001")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Yeni karşılaştırma" }));
    const dialog = await screen.findByRole("dialog");
    const file = new File(["x"], "stok.xlsx");
    await userEvent.upload(dialog.querySelector("input[type=file]") as HTMLInputElement, file);
    await userEvent.click(within(dialog).getByRole("button", { name: "Karşılaştır" }));
    expect(await within(dialog).findByText(/Malzeme kodu: Malzeme bulunamadı/)).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: "Karşılaştır" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/gecis/karsilastirma/7"));
    expect(await screen.findByText("HM-LAS")).toBeInTheDocument();
    expect(screen.getByText("12 satır, 2 farklı")).toBeInTheDocument();
    expect(goliveApi.listComparisonLines).toHaveBeenCalledWith(
      7,
      expect.objectContaining({ only_differences: true }),
    );
  });

  it("sorun bildir: görüntü alınamazsa açıklamayla gönderir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("dolum"));
    vi.mocked(goliveApi.reportProblem).mockResolvedValue({
      id: 3,
      number: "SB-2026-00003",
      description: "Etiket basılmıyor",
      page_url: "/yardim",
      page_title: "",
      user_agent: "",
      screen: "",
      has_screenshot: false,
      reporter: "",
      created_at: "2026-10-16T17:00:00+03:00",
    });
    renderApp("/yardim");

    await userEvent.click(await screen.findByRole("button", { name: "Sorun bildir" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Ekran görüntüsü alınamadı/)).toBeInTheDocument();
    const send = within(dialog).getByRole("button", { name: "Gönder" });
    expect(send).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText(/Açıklama/), "Etiket basılmıyor");
    await userEvent.click(send);

    await waitFor(() =>
      expect(goliveApi.reportProblem).toHaveBeenCalledWith(
        expect.objectContaining({
          description: "Etiket basılmıyor",
          page_url: "/yardim",
          screenshot: null,
        }),
      ),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("yardım sayfası kullanıcının rol kılavuzunu açar", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("dolum"));
    renderApp("/yardim");
    expect(await screen.findByText("Rolünüzün kılavuzları")).toBeInTheDocument();
    expect(screen.getByText("Rolünüz için")).toBeInTheDocument();
    expect(screen.getAllByText("Dolum (tablet)").length).toBeGreaterThan(0);
  });
});

describe("kılavuz markdown okuyucu", () => {
  it("başlık, liste, not ve görseli ayırır", () => {
    const blocks = parseMarkdown(
      [
        "# Başlık",
        "",
        "Bir **kalın** paragraf",
        "devamı.",
        "",
        "1. Birinci",
        "2. İkinci",
        "   uzun satır",
        "- madde",
        "> Not satırı",
        "![Ekran](/kilavuz/a.jpg)",
      ].join("\n"),
    );
    expect(blocks).toEqual([
      { kind: "h", level: 1, text: "Başlık" },
      { kind: "p", text: "Bir **kalın** paragraf devamı." },
      { kind: "ol", items: ["Birinci", "İkinci uzun satır"] },
      { kind: "ul", items: ["madde"] },
      { kind: "note", text: "Not satırı" },
      { kind: "img", alt: "Ekran", src: "/kilavuz/a.jpg" },
    ]);
  });
});
