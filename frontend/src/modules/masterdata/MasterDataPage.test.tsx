import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../api/auth";
import * as codingApi from "../../api/coding";
import * as labelsApi from "../../api/labels";
import * as mdApi from "../../api/masterdata";
import type { Material } from "../../api/masterdata";
import { httpError, page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";

vi.mock("../../api/auth");
vi.mock("../../api/coding");
vi.mock("../../api/labels", async (importOriginal) => ({
  ...(await importOriginal<typeof labelsApi>()),
  listPrinters: vi.fn(),
  testPrinter: vi.fn(),
  getLabelSettings: vi.fn(),
  saveLabelSettings: vi.fn(),
}));
vi.mock("../../api/masterdata", async (importOriginal) => {
  const original = await importOriginal<typeof mdApi>();
  return {
    ...original,
    listRecords: vi.fn(),
    saveRecord: vi.fn(),
    setRecordActive: vi.fn(),
    uploadImport: vi.fn(),
    getCompanyProfile: vi.fn(),
    saveCompanyProfile: vi.fn(),
    suggestGtin: vi.fn(),
    suggestCaseGtin: vi.fn(),
  };
});

const company = {
  legal_name: "Örnek Deterjan San. ve Tic. A.Ş.",
  address: "OSB 1. Cadde No: 1\nKocaeli",
  tax_office: "Gebze",
  tax_number: "1234567890",
  trade_registry_no: "",
  mersis_no: "",
  updated_at: "2026-10-25T10:00:00+03:00",
};

const las: Material = {
  id: 5,
  code: "HM-LAS",
  name: "LAS",
  material_type: "RAW",
  material_type_display: "Hammadde",
  category: null,
  category_name: null,
  base_unit: 1,
  base_unit_code: "KG",
  density: "1.0500",
  shelf_life_days: 730,
  min_stock: null,
  gtin: "",
  gtin_locked: false,
  requires_incoming_qc: true,
  is_hazardous: true,
  storage_notes: "",
  is_active: true,
  created_at: "2026-10-15T10:00:00+03:00",
  updated_at: "2026-10-15T10:00:00+03:00",
};

describe("ana veriler ekranı", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(authApi.fetchCsrf).mockResolvedValue();
    vi.mocked(codingApi.suggestCode).mockResolvedValue({
      key: "masterdata.material",
      active: false,
      code: null,
      format: "MLZ-0000000",
    });
    vi.mocked(mdApi.listRecords).mockImplementation(async (endpoint) => {
      if (endpoint === "materials") return page([las]);
      if (endpoint === "units") return page([{ id: 1, code: "KG", name: "Kilogram" }]);
      return page([]);
    });
  });

  it("malzeme listesini aktif filtresiyle gösterir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    const { router } = renderApp("/ana-veriler");

    expect(await screen.findByText("HM-LAS")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/ana-veriler/malzemeler");
    expect(screen.getByText("Tehlikeli")).toBeInTheDocument();
    expect(mdApi.listRecords).toHaveBeenCalledWith(
      "materials",
      expect.objectContaining({ is_active: "true", page: 1 }),
    );
  });

  it("form alan hatalarını alanın altında gösterir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    vi.mocked(mdApi.saveRecord).mockRejectedValue(
      httpError(400, {
        code: "validation_error",
        detail: "Gönderilen bilgiler geçersiz.",
        errors: { code: ["Bu Kod alanına sahip Malzeme zaten mevcut."] },
      }),
    );
    renderApp("/ana-veriler/malzemeler");

    await userEvent.click(await screen.findByRole("button", { name: "Yeni" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Kod/), "hm-las");
    await userEvent.type(within(dialog).getByLabelText(/^Ad/), "LAS");
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));

    expect(
      await within(dialog).findByText("Bu Kod alanına sahip Malzeme zaten mevcut."),
    ).toBeInTheDocument();
    expect(mdApi.saveRecord).toHaveBeenCalledWith(
      "materials",
      null,
      expect.objectContaining({ code: "hm-las", name: "LAS", requires_incoming_qc: true }),
    );
  });

  it("yeni malzemede önerilen kod gelir ve değiştirilebilir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    vi.mocked(codingApi.suggestCode).mockResolvedValue({
      key: "masterdata.material",
      active: true,
      code: "MLZ-0000025",
      format: "MLZ-0000000",
    });
    vi.mocked(mdApi.saveRecord).mockResolvedValue({ ...las, id: 9, code: "MLZ-0000030" });
    renderApp("/ana-veriler/malzemeler");

    await userEvent.click(await screen.findByRole("button", { name: "Yeni" }));
    const dialog = await screen.findByRole("dialog");
    const code = within(dialog).getByLabelText(/Kod/);
    await waitFor(() => expect(code).toHaveValue("MLZ-0000025"));
    expect(
      within(dialog).getByText("Önerilen kod. Değiştirebilirsiniz; biçim: MLZ-0000000"),
    ).toBeInTheDocument();
    expect(codingApi.suggestCode).toHaveBeenCalledWith("masterdata.material", undefined);

    await userEvent.clear(code);
    await userEvent.type(code, "MLZ-0000030");
    await userEvent.type(within(dialog).getByLabelText(/^Ad/), "SLES");
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(mdApi.saveRecord).toHaveBeenCalledWith(
        "materials",
        null,
        expect.objectContaining({ code: "MLZ-0000030", name: "SLES" }),
      ),
    );
  });

  it("Yeni yeniden açılınca önerilen kod yine gelir (vazgeçip ya da kayıt açıp kapattıktan sonra)", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    vi.mocked(codingApi.suggestCode).mockResolvedValue({
      key: "masterdata.material",
      active: true,
      code: "MLZ-0000025",
      format: "MLZ-0000000",
    });
    renderApp("/ana-veriler/malzemeler");
    const openNew = async () => {
      await userEvent.click(await screen.findByRole("button", { name: "Yeni" }));
      return screen.findByRole("dialog");
    };
    const close = async (dialog: HTMLElement) => {
      await userEvent.click(within(dialog).getByRole("button", { name: "Vazgeç" }));
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    };

    let dialog = await openNew();
    await waitFor(() => expect(within(dialog).getByLabelText(/Kod/)).toHaveValue("MLZ-0000025"));
    await close(dialog);
    // Öneri değişmese de (aynı kod döner) alan dolu gelir.
    dialog = await openNew();
    await waitFor(() => expect(within(dialog).getByLabelText(/Kod/)).toHaveValue("MLZ-0000025"));
    await close(dialog);

    await userEvent.click(screen.getByText("HM-LAS"));
    dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText(/Kod/)).toHaveValue("HM-LAS");
    await close(dialog);
    dialog = await openNew();
    await waitFor(() => expect(within(dialog).getByLabelText(/Kod/)).toHaveValue("MLZ-0000025"));
  });

  it.each([
    [
      "benzersizlik hatası",
      {
        code: "validation_error",
        detail: "Gönderilen bilgiler geçersiz.",
        errors: { code: ["Bu Kod alanına sahip Malzeme zaten mevcut."] },
      },
      "Bu Kod alanına sahip Malzeme zaten mevcut.",
    ],
    [
      "code_taken",
      {
        code: "code_taken",
        detail: "MLZ-0000025 az önce başka bir kayda verildi. Yeni öneri: MLZ-0000026.",
      },
      "MLZ-0000025 az önce başka bir kayda verildi. Yeni öneri: MLZ-0000026.",
    ],
    [
      "code_reserved",
      {
        code: "code_reserved",
        detail: "MLZ-0000025 başka bir kaydın eski kodu; kullanılamaz.",
      },
      "MLZ-0000025 başka bir kaydın eski kodu; kullanılamaz.",
    ],
  ])(
    "önerilen kod kaydederken alınmışsa (%s) sıradaki öneri alana yazılır",
    async (_name, body, serverMessage) => {
      vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
      let next = "MLZ-0000025";
      vi.mocked(codingApi.suggestCode).mockImplementation(async () => ({
        key: "masterdata.material",
        active: true,
        code: next,
        format: "MLZ-0000000",
      }));
      vi.mocked(mdApi.saveRecord)
        .mockImplementationOnce(async () => {
          next = "MLZ-0000026"; // başka bir kullanıcı 25'i az önce aldı
          throw httpError(400, body);
        })
        .mockResolvedValue({ ...las, id: 9, code: "MLZ-0000026" });
      renderApp("/ana-veriler/malzemeler");

      await userEvent.click(await screen.findByRole("button", { name: "Yeni" }));
      const dialog = await screen.findByRole("dialog");
      const code = within(dialog).getByLabelText(/Kod/);
      await waitFor(() => expect(code).toHaveValue("MLZ-0000025"));
      await userEvent.type(within(dialog).getByLabelText(/^Ad/), "SLES");
      await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));

      expect(
        await within(dialog).findByText(
          "MLZ-0000025 başka bir kayda verilmiş. Yerine sıradaki önerilen kod MLZ-0000026 yazıldı; kontrol edip yeniden kaydedin.",
        ),
      ).toBeInTheDocument();
      expect(code).toHaveValue("MLZ-0000026");
      expect(within(dialog).queryByText(serverMessage)).not.toBeInTheDocument();

      await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
      await waitFor(() =>
        expect(mdApi.saveRecord).toHaveBeenLastCalledWith(
          "materials",
          null,
          expect.objectContaining({ code: "MLZ-0000026", name: "SLES" }),
        ),
      );
    },
  );

  it.each([
    ["öneri değişmediyse", "same"],
    ["öneri yenilenemediyse", "fail"],
  ])("önerilen kod alınmış ama %s kod ve sunucu hatası olduğu gibi kalır", async (_name, mode) => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    const suggestion = {
      key: "masterdata.material",
      active: true,
      code: "MLZ-0000025",
      format: "MLZ-0000000",
    };
    vi.mocked(codingApi.suggestCode).mockResolvedValueOnce(suggestion);
    if (mode === "same") vi.mocked(codingApi.suggestCode).mockResolvedValue(suggestion);
    else vi.mocked(codingApi.suggestCode).mockRejectedValue(httpError(500, {}));
    vi.mocked(mdApi.saveRecord).mockRejectedValue(
      httpError(400, { code: "duplicate", detail: "Bu kayıt zaten var (kod tekrarı)." }),
    );
    renderApp("/ana-veriler/malzemeler");

    await userEvent.click(await screen.findByRole("button", { name: "Yeni" }));
    const dialog = await screen.findByRole("dialog");
    const code = within(dialog).getByLabelText(/Kod/);
    await waitFor(() => expect(code).toHaveValue("MLZ-0000025"));
    await userEvent.type(within(dialog).getByLabelText(/^Ad/), "SLES");
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));

    expect(
      await within(dialog).findByText("Bu kayıt zaten var (kod tekrarı)."),
    ).toBeInTheDocument();
    expect(code).toHaveValue("MLZ-0000025");
    expect(within(dialog).queryByText(/başka bir kayda verilmiş/)).not.toBeInTheDocument();
  });

  it("kullanıcının yazdığı kod alınmışsa kod değiştirilmez, hata gösterilir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    vi.mocked(codingApi.suggestCode).mockResolvedValue({
      key: "masterdata.material",
      active: true,
      code: "MLZ-0000025",
      format: "MLZ-0000000",
    });
    vi.mocked(mdApi.saveRecord).mockRejectedValue(
      httpError(400, {
        code: "code_taken",
        detail: "MLZ-0000030 az önce başka bir kayda verildi. Yeni öneri: MLZ-0000025.",
      }),
    );
    renderApp("/ana-veriler/malzemeler");

    await userEvent.click(await screen.findByRole("button", { name: "Yeni" }));
    const dialog = await screen.findByRole("dialog");
    const code = within(dialog).getByLabelText(/Kod/);
    await waitFor(() => expect(code).toHaveValue("MLZ-0000025"));
    await userEvent.clear(code);
    await userEvent.type(code, "MLZ-0000030");
    await userEvent.type(within(dialog).getByLabelText(/^Ad/), "SLES");
    const calls = vi.mocked(codingApi.suggestCode).mock.calls.length;
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));

    expect(
      await within(dialog).findByText(/MLZ-0000030 az önce başka bir kayda verildi/),
    ).toBeInTheDocument();
    expect(code).toHaveValue("MLZ-0000030");
    expect(within(dialog).queryByText(/başka bir kayda verilmiş/)).not.toBeInTheDocument();
    expect(codingApi.suggestCode).toHaveBeenCalledTimes(calls);
  });

  it("kodu kayıt açıldıktan sonra yalnızca admin değiştirir; eski kodlar görünür", async () => {
    const renamed = { ...las, code: "MLZ-0000001", former_codes: ["HM-LAS"] };
    vi.mocked(mdApi.listRecords).mockImplementation(async (endpoint) =>
      endpoint === "materials" ? page([renamed]) : page([]),
    );
    vi.mocked(mdApi.saveRecord).mockResolvedValue(renamed);
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    renderApp("/ana-veriler/malzemeler");

    await userEvent.click(await screen.findByText("MLZ-0000001"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText(/Kod/)).toBeDisabled();
    expect(
      within(dialog).getByText(
        "Kodu yalnızca sistem yöneticisi değiştirebilir. Eski kodlar: HM-LAS",
      ),
    ).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() => expect(mdApi.saveRecord).toHaveBeenCalled());
    expect(vi.mocked(mdApi.saveRecord).mock.calls[0][2]).not.toHaveProperty("code");
    expect(codingApi.suggestCode).not.toHaveBeenCalled();
  });

  it("admin düzenlemede kodu değiştirebilir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("admin"));
    renderApp("/ana-veriler/malzemeler");

    await userEvent.click(await screen.findByText("HM-LAS"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText(/Kod/)).toBeEnabled();
  });

  it("iş kuralı hatasını uyarı olarak gösterir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    vi.mocked(mdApi.saveRecord).mockRejectedValue(
      httpError(400, {
        code: "base_unit_locked",
        detail: "HM-LAS kullanılıyor; temel birimi değiştirilemez.",
      }),
    );
    renderApp("/ana-veriler/malzemeler");

    await userEvent.click(await screen.findByText("HM-LAS"));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));

    expect(await within(dialog).findByText(/temel birimi değiştirilemez/)).toBeInTheDocument();
    expect(mdApi.saveRecord).toHaveBeenCalledWith(
      "materials",
      5,
      expect.objectContaining({ density: "1.05" }),
    );
  });

  it("yazma yetkisi olmayan rol yeni kayıt ve içe aktarma düğmelerini görmez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    renderApp("/ana-veriler/malzemeler");

    await screen.findByText("HM-LAS");
    expect(screen.queryByRole("button", { name: "Yeni" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Excel'den içe aktar" })).not.toBeInTheDocument();
  });

  it("birimleri yalnızca admin yazar", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    renderApp("/ana-veriler/birimler");

    await screen.findByText("KG");
    expect(screen.queryByRole("button", { name: "Yeni" })).not.toBeInTheDocument();
  });

  it("depo rolü ana veriler ekranına giremez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    renderApp("/ana-veriler");

    expect(await screen.findByText("Yetkiniz yok")).toBeInTheDocument();
  });

  it("içe aktarmada hatalı satır varken aktarma düğmesi kapalıdır", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    vi.mocked(mdApi.uploadImport).mockResolvedValue({
      kind: "materials",
      total: 2,
      valid: 1,
      invalid: 1,
      to_create: 2,
      to_update: 0,
      file_errors: [],
      imported: false,
      rows: [
        { row: 2, code: "HM-1", action: "create", errors: [] },
        {
          row: 3,
          code: "HM-2",
          action: "create",
          errors: [{ column: "Tür", message: "Geçersiz değer" }],
        },
      ],
    });
    renderApp("/ana-veriler/malzemeler");

    await userEvent.click(await screen.findByRole("button", { name: "Excel'den içe aktar" }));
    const dialog = await screen.findByRole("dialog");
    const file = new File(["x"], "m.xlsx");
    await userEvent.upload(dialog.querySelector("input[type=file]") as HTMLInputElement, file);
    await userEvent.click(within(dialog).getByRole("button", { name: "Önizle" }));

    expect(await within(dialog).findByText("Tür: Geçersiz değer")).toBeInTheDocument();
    expect(within(dialog).getByText(/2 satır: 2 yeni, 0 güncelleme, 1 hatalı/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "2 satırı aktar" })).toBeDisabled();
    expect(mdApi.uploadImport).toHaveBeenCalledWith("materials", file, false);
  });

  it("hatasız önizlemeden sonra aktarır", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    const report = {
      kind: "materials" as const,
      total: 1,
      valid: 1,
      invalid: 0,
      to_create: 1,
      to_update: 0,
      file_errors: [],
      rows: [{ row: 2, code: "HM-1", action: "create" as const, errors: [] }],
    };
    vi.mocked(mdApi.uploadImport)
      .mockResolvedValueOnce({ ...report, imported: false })
      .mockResolvedValueOnce({ ...report, imported: true });
    renderApp("/ana-veriler/malzemeler");

    await userEvent.click(await screen.findByRole("button", { name: "Excel'den içe aktar" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.upload(
      dialog.querySelector("input[type=file]") as HTMLInputElement,
      new File(["x"], "m.xlsx"),
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Önizle" }));
    await userEvent.click(await within(dialog).findByRole("button", { name: "1 satırı aktar" }));

    await waitFor(() =>
      expect(mdApi.uploadImport).toHaveBeenLastCalledWith("materials", expect.any(File), true),
    );
  });

  it("yazıcılar sekmesinde deneme etiketi gönderilir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("admin"));
    vi.mocked(mdApi.listRecords).mockImplementation(async (endpoint) =>
      endpoint === "printers"
        ? page([
            {
              id: 3,
              code: "ZB-DEPO",
              name: "Depo Zebra",
              printer_type: "ZPL",
              host: "192.168.1.50",
              port: 9100,
              dpi: 203,
              location: null,
              location_code: null,
              note: "",
              is_active: true,
            },
          ])
        : page([]),
    );
    vi.mocked(labelsApi.testPrinter).mockResolvedValue({ printed: 1, printer: "ZB-DEPO" });
    renderApp("/ana-veriler/yazicilar");
    expect(await screen.findByText("192.168.1.50:9100")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Deneme etiketi: ZB-DEPO" }));
    await waitFor(() => expect(labelsApi.testPrinter).toHaveBeenCalledWith(3));
  });

  it("etiket ayarlarında GS1 alanları salt okunur; admin firma adını kaydeder, GS1 gönderilmez", async () => {
    const settings = {
      company_name: "Inncos",
      gs1_company_prefix: "8690000",
      sscc_extension_digit: 0,
      next_sscc_serial: 41,
      default_printer: null,
      default_printer_code: null,
      sscc_enabled: true,
      updated_at: "2026-10-15T09:00:00+03:00",
    };
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("admin"));
    vi.mocked(labelsApi.listPrinters).mockResolvedValue([]);
    vi.mocked(labelsApi.getLabelSettings).mockResolvedValue(settings);
    vi.mocked(labelsApi.saveLabelSettings).mockResolvedValue({
      ...settings,
      company_name: "Inncos Kimya",
    });
    renderApp("/ana-veriler/etiket-ayarlari");
    const prefix = await screen.findByLabelText(/GS1 firma öneki/);
    expect(prefix).toBeDisabled();
    expect(prefix).toHaveValue("8690000");
    expect(screen.getByLabelText(/SSCC uzantı hanesi/)).toBeDisabled();
    expect(screen.getByLabelText(/Sıradaki SSCC seri no/)).toHaveValue("41");
    expect(screen.getByTestId("gs1-managed")).toHaveTextContent(
      "GS1 ayarları Sistem > Kodlama sistematiği > GS1'de değiştirilir.",
    );
    expect(
      screen.getByRole("link", { name: "Sistem > Kodlama sistematiği > GS1" }),
    ).toHaveAttribute("href", "/sistem/kodlama?bolum=gs1");
    expect(screen.getByText("SSCC palet etiketi açık.")).toBeInTheDocument();

    const company = screen.getByLabelText(/Etikette firma adı/);
    await userEvent.clear(company);
    await userEvent.type(company, "Inncos Kimya");
    await userEvent.click(screen.getByRole("button", { name: "Kaydet" }));
    // Yalnızca firma adı ve varsayılan yazıcı gönderilir.
    await waitFor(() =>
      expect(labelsApi.saveLabelSettings).toHaveBeenCalledWith({
        company_name: "Inncos Kimya",
        default_printer: null,
      }),
    );
  });

  it("planlama etiket ayarlarını değiştiremez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    vi.mocked(labelsApi.listPrinters).mockResolvedValue([]);
    vi.mocked(labelsApi.getLabelSettings).mockResolvedValue({
      company_name: "Inncos",
      gs1_company_prefix: "",
      sscc_extension_digit: 0,
      next_sscc_serial: 1,
      default_printer: null,
      default_printer_code: null,
      sscc_enabled: false,
      updated_at: "2026-10-15T09:00:00+03:00",
    });
    renderApp("/ana-veriler/etiket-ayarlari");
    expect(await screen.findByLabelText(/GS1 firma öneki/)).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Kaydet" })).toBeNull();
    // GS1 ekranı yalnız admin'e açıktır: diğer roller yalnızca yerini görür.
    expect(screen.getByTestId("gs1-managed")).toHaveTextContent(
      "GS1 ayarları Sistem > Kodlama sistematiği > GS1'de değiştirilir.",
    );
    expect(screen.queryByRole("link", { name: /Kodlama sistematiği/ })).toBeNull();
  });
  it("yönetim firma bilgilerini düzenler; hatalı vergi no gönderilmez", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    vi.mocked(mdApi.getCompanyProfile).mockResolvedValue(company);
    vi.mocked(mdApi.saveCompanyProfile).mockResolvedValue({
      ...company,
      mersis_no: "0123456789000017",
    });
    renderApp("/ana-veriler/firma-bilgileri");
    const taxNumber = await screen.findByLabelText(/Vergi no \/ TCKN/);
    expect(screen.getByLabelText(/Ticari unvan/)).toHaveValue(company.legal_name);
    await user.clear(taxNumber);
    await user.type(taxNumber, "12345");
    await user.click(screen.getByRole("button", { name: "Kaydet" }));
    expect(await screen.findByText("10 ya da 11 haneli bir sayı olmalı.")).toBeInTheDocument();
    expect(mdApi.saveCompanyProfile).not.toHaveBeenCalled();

    await user.clear(taxNumber);
    await user.type(taxNumber, "1234567890");
    await user.type(screen.getByLabelText(/MERSİS no/), "0123456789000017");
    await user.click(screen.getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(mdApi.saveCompanyProfile).toHaveBeenCalledWith({
        legal_name: company.legal_name,
        address: company.address,
        tax_office: "Gebze",
        tax_number: "1234567890",
        trade_registry_no: "",
        mersis_no: "0123456789000017",
      }),
    );
  });

  it("planlama firma bilgilerini yalnızca okur", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    vi.mocked(mdApi.getCompanyProfile).mockResolvedValue(company);
    renderApp("/ana-veriler/firma-bilgileri");
    expect(await screen.findByLabelText(/Ticari unvan/)).toBeDisabled();
    expect(screen.getByText(/yönetim ve sistem yöneticisi değiştirir/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Kaydet" })).toBeNull();
  });
});

/** Elle çözülen söz: yanıtın (ya da hatanın) ne zaman geleceğini test belirler. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

/** Mantine uyarısının rengi kök öğenin stilindeki değişkenlerde (--alert-bg, --alert-color). */
function alertStyle(element: HTMLElement): string {
  return element.closest(".mantine-Alert-root")?.getAttribute("style") ?? "";
}

describe("GS1: malzeme GTIN'i ve koli GTIN'i", () => {
  const finished: Material = {
    ...las,
    id: 6,
    code: "MAM-1",
    name: "Bulaşık deterjanı 750 ml",
    material_type: "FINISHED",
    material_type_display: "Mamul",
    base_unit_code: "ADET",
    requires_incoming_qc: false,
    is_hazardous: false,
  };
  const units = [
    { id: 1, code: "KG", name: "Kilogram", is_active: true },
    { id: 7, code: "KOLI", name: "Koli", is_active: true },
  ];
  const caseConversion: mdApi.Conversion = {
    id: 21,
    material: 6,
    material_code: "MAM-1",
    unit: 7,
    unit_code: "KOLI",
    factor_to_base: "12.000000",
    base_unit_code: "ADET",
    gtin: "18690000000019",
    gtin_locked: true,
    retired_gtins: [],
    is_active: true,
    created_at: "2026-11-05T10:00:00+03:00",
    updated_at: "2026-11-05T10:00:00+03:00",
  };

  function records(materials: Material[], conversions: mdApi.Conversion[] = []) {
    vi.mocked(mdApi.listRecords).mockImplementation(async (endpoint) => {
      if (endpoint === "materials") return page(materials);
      if (endpoint === "units") return page(units);
      if (endpoint === "conversions") return page(conversions);
      return page([]);
    });
  }

  async function choose(dialog: HTMLElement, label: string, option: string) {
    await userEvent.click(within(dialog).getByRole("textbox", { name: label }));
    await userEvent.click(await screen.findByRole("option", { name: option }));
  }

  const takenDetail = "Bu GTIN başka bir malzemede ya da koli dönüşümünde kayıtlı: MAM-2.";
  const gtinTaken = () => httpError(400, { code: "gtin_taken", detail: takenDetail });
  /** Alınmış önerinin yerine sıradaki öneri yazılınca çıkan sarı not. */
  const refreshed = (taken: string, next: string) =>
    `${taken} başka bir malzemede ya da koli dönüşümünde kayıtlı. Yerine sıradaki önerilen GTIN ${next} yazıldı; kontrol edip yeniden kaydedin.`;

  /** Yeni mamulde "GTIN öner"in yazdığı GTIN'le kaydeder (kod verilirse önce kodu yazar). */
  async function saveSuggestedGtin(code = "") {
    await userEvent.click(await screen.findByRole("button", { name: "Yeni" }));
    const dialog = await screen.findByRole("dialog");
    await choose(dialog, "Tür", "Mamul");
    await userEvent.click(await within(dialog).findByRole("button", { name: "GTIN öner" }));
    if (code) await userEvent.type(within(dialog).getByLabelText(/^Kod/), code);
    await userEvent.type(within(dialog).getByLabelText(/^Ad/), "Bulaşık deterjanı");
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    return { dialog, gtin: within(dialog).getByLabelText(/GTIN \(barkod no\)/) };
  }

  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(authApi.fetchCsrf).mockResolvedValue();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    vi.mocked(codingApi.suggestCode).mockResolvedValue({
      key: "masterdata.material",
      active: false,
      code: null,
      format: "MLZ-0000000",
    });
    records([las]);
  });

  it("mamulde öneri açıksa ve GTIN boşsa 'GTIN öner' sıradaki GTIN'i alana yazar", async () => {
    vi.mocked(mdApi.suggestGtin).mockResolvedValue({
      active: true,
      gtin: "8690000000123",
      reason: "",
    });
    vi.mocked(mdApi.saveRecord).mockResolvedValue({ ...finished, id: 9, gtin: "8690000000123" });
    renderApp("/ana-veriler/malzemeler");

    await userEvent.click(await screen.findByRole("button", { name: "Yeni" }));
    const dialog = await screen.findByRole("dialog");
    const gtin = within(dialog).getByLabelText(/GTIN \(barkod no\)/);
    // Öneri yalnızca mamulde: hammaddede istenmez.
    expect(within(dialog).queryByRole("button", { name: "GTIN öner" })).not.toBeInTheDocument();
    expect(mdApi.suggestGtin).not.toHaveBeenCalled();

    await choose(dialog, "Tür", "Mamul");
    await userEvent.click(await within(dialog).findByRole("button", { name: "GTIN öner" }));
    expect(gtin).toHaveValue("8690000000123");
    // Alan dolunca düğme kalkar.
    expect(within(dialog).queryByRole("button", { name: "GTIN öner" })).not.toBeInTheDocument();

    await userEvent.type(within(dialog).getByLabelText(/^Ad/), "Bulaşık deterjanı");
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(mdApi.saveRecord).toHaveBeenCalledWith(
        "materials",
        null,
        expect.objectContaining({ material_type: "FINISHED", gtin: "8690000000123" }),
      ),
    );
  });

  it("art arda ikinci mamulde önceki öneri sunulmaz; yeni öneri gelince yazılır", async () => {
    const second = deferred<mdApi.GtinSuggestion>();
    vi.mocked(mdApi.suggestGtin)
      .mockResolvedValue({ active: true, gtin: "8690000000147", reason: "" })
      .mockResolvedValueOnce({ active: true, gtin: "8690000000123", reason: "" })
      .mockReturnValueOnce(second.promise);
    vi.mocked(mdApi.saveRecord).mockResolvedValue({ ...finished, id: 9, gtin: "8690000000123" });
    const { queryClient } = renderApp("/ana-veriler/malzemeler");
    const newFinished = async () => {
      await userEvent.click(await screen.findByRole("button", { name: "Yeni" }));
      const dialog = await screen.findByRole("dialog");
      await choose(dialog, "Tür", "Mamul");
      return dialog;
    };

    let dialog = await newFinished();
    await userEvent.click(await within(dialog).findByRole("button", { name: "GTIN öner" }));
    await userEvent.type(within(dialog).getByLabelText(/^Ad/), "Bulaşık deterjanı");
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(mdApi.saveRecord).toHaveBeenCalledWith(
      "materials",
      null,
      expect.objectContaining({ gtin: "8690000000123" }),
    );
    // Malzeme kaydı öneriyi de geçersizler (malzeme listesiyle birlikte yenilenir).
    expect(queryClient.getQueryState(mdApi.gtinSuggestionKey)?.isInvalidated).toBe(true);

    dialog = await newFinished();
    await waitFor(() => expect(mdApi.suggestGtin).toHaveBeenCalledTimes(2));
    // Yeni öneri gelene kadar önbellekteki (az önce kaydedilen) GTIN sunulmaz.
    expect(within(dialog).queryByRole("button", { name: "GTIN öner" })).not.toBeInTheDocument();
    second.resolve({ active: true, gtin: "8690000000130", reason: "" });
    await userEvent.click(await within(dialog).findByRole("button", { name: "GTIN öner" }));
    expect(within(dialog).getByLabelText(/GTIN \(barkod no\)/)).toHaveValue("8690000000130");
  });

  it("önerilen GTIN kaydederken alınmışsa sıradaki öneri alana yazılır", async () => {
    let next = "8690000000123";
    vi.mocked(mdApi.suggestGtin).mockImplementation(async () => ({
      active: true,
      gtin: next,
      reason: "",
    }));
    const taken = "Bu GTIN başka bir malzemede ya da koli dönüşümünde kayıtlı: MAM-2.";
    vi.mocked(mdApi.saveRecord)
      .mockImplementationOnce(async () => {
        next = "8690000000130"; // başka bir kullanıcı 123'ü az önce aldı
        throw httpError(400, { code: "gtin_taken", detail: taken });
      })
      .mockResolvedValue({ ...finished, id: 9, gtin: "8690000000130" });
    renderApp("/ana-veriler/malzemeler");

    await userEvent.click(await screen.findByRole("button", { name: "Yeni" }));
    const dialog = await screen.findByRole("dialog");
    await choose(dialog, "Tür", "Mamul");
    await userEvent.click(await within(dialog).findByRole("button", { name: "GTIN öner" }));
    const gtin = within(dialog).getByLabelText(/GTIN \(barkod no\)/);
    expect(gtin).toHaveValue("8690000000123");
    await userEvent.type(within(dialog).getByLabelText(/^Ad/), "Bulaşık deterjanı");
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));

    const notice = await within(dialog).findByText(
      "8690000000123 başka bir malzemede ya da koli dönüşümünde kayıtlı. Yerine sıradaki önerilen GTIN 8690000000130 yazıldı; kontrol edip yeniden kaydedin.",
    );
    expect(alertStyle(notice)).toContain("--mantine-color-yellow-light"); // sarı
    expect(gtin).toHaveValue("8690000000130");
    expect(within(dialog).queryByText(taken)).not.toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(mdApi.saveRecord).toHaveBeenLastCalledWith(
        "materials",
        null,
        expect.objectContaining({ gtin: "8690000000130" }),
      ),
    );
  });

  it("kullanıcının yazdığı GTIN alınmışsa GTIN değiştirilmez; sunucunun hatası görünür", async () => {
    let next = "8690000000123";
    vi.mocked(mdApi.suggestGtin).mockImplementation(async () => ({
      active: true,
      gtin: next,
      reason: "",
    }));
    const taken = "Bu GTIN başka bir malzemede ya da koli dönüşümünde kayıtlı: MAM-2.";
    vi.mocked(mdApi.saveRecord).mockImplementation(async () => {
      next = "8690000000130";
      throw httpError(400, { code: "gtin_taken", detail: taken });
    });
    renderApp("/ana-veriler/malzemeler");

    await userEvent.click(await screen.findByRole("button", { name: "Yeni" }));
    const dialog = await screen.findByRole("dialog");
    await choose(dialog, "Tür", "Mamul");
    // Öneri alana yazıldıktan sonra kullanıcı kendi GTIN'ini yazar.
    await userEvent.click(await within(dialog).findByRole("button", { name: "GTIN öner" }));
    const gtin = within(dialog).getByLabelText(/GTIN \(barkod no\)/);
    await userEvent.clear(gtin);
    await userEvent.type(gtin, "8690000000017");
    await userEvent.type(within(dialog).getByLabelText(/^Ad/), "Bulaşık deterjanı");
    const calls = vi.mocked(mdApi.suggestGtin).mock.calls.length;
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));

    expect(await within(dialog).findByText(taken)).toBeInTheDocument();
    expect(gtin).toHaveValue("8690000000017");
    expect(within(dialog).queryByText(/Yerine sıradaki önerilen GTIN/)).not.toBeInTheDocument();
    expect(mdApi.suggestGtin).toHaveBeenCalledTimes(calls);
  });

  it("öneri yenilenirken kullanıcı kendi GTIN'ini yazarsa geç gelen öneri yazılmaz", async () => {
    const refetch = deferred<mdApi.GtinSuggestion>();
    vi.mocked(mdApi.suggestGtin)
      .mockResolvedValueOnce({ active: true, gtin: "8690000000123", reason: "" })
      .mockReturnValueOnce(refetch.promise);
    vi.mocked(mdApi.saveRecord)
      .mockRejectedValueOnce(gtinTaken())
      .mockResolvedValue({ ...finished, id: 9, gtin: "8690000000017" });
    const { queryClient } = renderApp("/ana-veriler/malzemeler");

    const { dialog, gtin } = await saveSuggestedGtin();
    expect(await within(dialog).findByText(takenDetail)).toBeInTheDocument();
    await waitFor(() => expect(mdApi.suggestGtin).toHaveBeenCalledTimes(2));
    // Yenileme sürerken kullanıcı kendi GTIN'ini yazar; sonra yenilenen öneri gelir.
    await userEvent.clear(gtin);
    await userEvent.type(gtin, "8690000000017");
    refetch.resolve({ active: true, gtin: "8690000000130", reason: "" });

    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
    expect(gtin).toHaveValue("8690000000017");
    expect(within(dialog).queryByText(/Yerine sıradaki önerilen GTIN/)).not.toBeInTheDocument();
    expect(within(dialog).getByText(takenDetail)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(mdApi.saveRecord).toHaveBeenLastCalledWith(
        "materials",
        null,
        expect.objectContaining({ gtin: "8690000000017" }),
      ),
    );
  });

  it("öneri yenilenirken yeniden kaydedilirse geç gelen öneri alana yazılmaz", async () => {
    const refetch = deferred<mdApi.GtinSuggestion>();
    const resave = deferred<Material>();
    vi.mocked(mdApi.suggestGtin)
      .mockResolvedValue({ active: true, gtin: "8690000000147", reason: "" })
      .mockResolvedValueOnce({ active: true, gtin: "8690000000123", reason: "" })
      .mockReturnValueOnce(refetch.promise);
    vi.mocked(mdApi.saveRecord)
      .mockRejectedValueOnce(gtinTaken())
      .mockReturnValueOnce(resave.promise);
    const { queryClient } = renderApp("/ana-veriler/malzemeler");

    const { dialog, gtin } = await saveSuggestedGtin();
    expect(await within(dialog).findByText(takenDetail)).toBeInTheDocument();
    await waitFor(() => expect(mdApi.suggestGtin).toHaveBeenCalledTimes(2));
    // Yenileme sürerken kullanıcı alandaki GTIN'le yeniden kaydeder.
    const save = within(dialog).getByRole("button", { name: "Kaydet" });
    await userEvent.click(save);
    await waitFor(() => expect(mdApi.saveRecord).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(save).toBeDisabled()); // ikinci kayıt sürüyor
    expect(mdApi.saveRecord).toHaveBeenLastCalledWith(
      "materials",
      null,
      expect.objectContaining({ gtin: "8690000000123" }),
    );
    refetch.resolve({ active: true, gtin: "8690000000130", reason: "" });

    // Geç gelen öneri, sürmekte olan kaydın GTIN'inin yerine yazılmaz.
    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
    expect(gtin).toHaveValue("8690000000123");
    expect(within(dialog).queryByText(/Yerine sıradaki önerilen GTIN/)).not.toBeInTheDocument();
    // İkinci kayıt da reddedilince öneri yeniden istenir; not kaydedilmek istenen GTIN'i söyler.
    resave.reject(gtinTaken());
    expect(
      await within(dialog).findByText(refreshed("8690000000123", "8690000000147")),
    ).toBeInTheDocument();
    expect(gtin).toHaveValue("8690000000147");
  });

  it("önerilen GTIN art arda iki kez alınmışsa her seferinde sıradaki öneri yazılır", async () => {
    let next = "8690000000123";
    vi.mocked(mdApi.suggestGtin).mockImplementation(async () => ({
      active: true,
      gtin: next,
      reason: "",
    }));
    vi.mocked(mdApi.saveRecord)
      .mockImplementationOnce(async () => {
        next = "8690000000130";
        throw gtinTaken();
      })
      .mockImplementationOnce(async () => {
        next = "8690000000147";
        throw gtinTaken();
      })
      .mockResolvedValue({ ...finished, id: 9, gtin: "8690000000147" });
    renderApp("/ana-veriler/malzemeler");

    const { dialog, gtin } = await saveSuggestedGtin();
    expect(
      await within(dialog).findByText(refreshed("8690000000123", "8690000000130")),
    ).toBeInTheDocument();
    expect(gtin).toHaveValue("8690000000130");

    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    expect(
      await within(dialog).findByText(refreshed("8690000000130", "8690000000147")),
    ).toBeInTheDocument();
    expect(gtin).toHaveValue("8690000000147");
    expect(within(dialog).queryByText(takenDetail)).not.toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(mdApi.saveRecord).toHaveBeenCalledTimes(3);
    expect(mdApi.saveRecord).toHaveBeenLastCalledWith(
      "materials",
      null,
      expect.objectContaining({ gtin: "8690000000147" }),
    );
  });

  it("kayıt GTIN dışı bir nedenle reddedilirse öneri yeniden istenmez; GTIN ve hata kalır", async () => {
    let next = "8690000000123";
    vi.mocked(mdApi.suggestGtin).mockImplementation(async () => ({
      active: true,
      gtin: next,
      reason: "",
    }));
    const duplicate = "Bu kayıt zaten var (kod tekrarı).";
    vi.mocked(mdApi.saveRecord)
      .mockImplementationOnce(async () => {
        next = "8690000000130"; // öneri bu arada ilerledi
        throw httpError(400, { code: "duplicate", detail: duplicate });
      })
      .mockResolvedValue({ ...finished, id: 9, code: "MAM-3", gtin: "8690000000123" });
    renderApp("/ana-veriler/malzemeler");

    const { dialog, gtin } = await saveSuggestedGtin("MAM-1");
    expect(await within(dialog).findByText(duplicate)).toBeInTheDocument();
    // Kullanıcı kodu düzeltirken GTIN, sunucunun hatası ve öneri isteği olduğu gibi kalır.
    const code = within(dialog).getByLabelText(/^Kod/);
    await userEvent.clear(code);
    await userEvent.type(code, "MAM-3");
    expect(gtin).toHaveValue("8690000000123");
    expect(within(dialog).getByText(duplicate)).toBeInTheDocument();
    expect(within(dialog).queryByText(/Yerine sıradaki önerilen GTIN/)).not.toBeInTheDocument();
    expect(mdApi.suggestGtin).toHaveBeenCalledTimes(1);

    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(mdApi.saveRecord).toHaveBeenLastCalledWith(
        "materials",
        null,
        expect.objectContaining({ code: "MAM-3", gtin: "8690000000123" }),
      ),
    );
  });

  it.each([
    [
      "öneri kapalıysa",
      {
        active: false,
        gtin: null,
        reason: "GS1 firma öneki ve sıradaki ürün referansı girilmemiş.",
      },
      false,
    ],
    [
      "boş GTIN kalmadıysa",
      { active: true, gtin: null, reason: "Ürün referansları doldu; GS1'de yeni referans girin." },
      true,
    ],
  ])("%s 'GTIN öner' çıkmaz", async (_name, suggestion, showsReason) => {
    records([{ ...finished, gtin: "" }]);
    vi.mocked(mdApi.suggestGtin).mockResolvedValue(suggestion);
    renderApp("/ana-veriler/malzemeler");

    await userEvent.click(await screen.findByText("MAM-1"));
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(mdApi.suggestGtin).toHaveBeenCalled());
    if (showsReason) expect(await within(dialog).findByText(suggestion.reason)).toBeInTheDocument();
    else expect(within(dialog).queryByText(suggestion.reason)).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "GTIN öner" })).not.toBeInTheDocument();
    expect(within(dialog).getByLabelText(/GTIN \(barkod no\)/)).toBeEnabled();
  });

  it("lotu olan mamulün GTIN'i kapalıdır, nedeni yazar ve gönderilmez", async () => {
    const locked = { ...finished, gtin: "8690000000012", gtin_locked: true };
    records([locked]);
    vi.mocked(mdApi.saveRecord).mockResolvedValue(locked);
    renderApp("/ana-veriler/malzemeler");

    await userEvent.click(await screen.findByText("MAM-1"));
    const dialog = await screen.findByRole("dialog");
    const gtin = within(dialog).getByLabelText(/GTIN \(barkod no\)/);
    expect(gtin).toBeDisabled();
    expect(gtin).toHaveValue("8690000000012");
    // Kilit yalnız mamulde (hammaddede lot olsa da sunucu `gtin_locked: false` gönderir).
    expect(gtin).toHaveAccessibleDescription("Lotu olan mamulün GTIN'i değiştirilemez.");
    expect(within(dialog).queryByRole("button", { name: "GTIN öner" })).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() => expect(mdApi.saveRecord).toHaveBeenCalled());
    expect(vi.mocked(mdApi.saveRecord).mock.calls[0][2]).not.toHaveProperty("gtin");
  });

  it("malzemeyi yalnız görüntüleyen rol GTIN önerisi istemez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    records([{ ...finished, gtin: "" }]);
    renderApp("/ana-veriler/malzemeler");

    await userEvent.click(await screen.findByText("MAM-1"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText(/GTIN \(barkod no\)/)).toBeDisabled();
    expect(within(dialog).queryByRole("button", { name: "GTIN öner" })).not.toBeInTheDocument();
    expect(mdApi.suggestGtin).not.toHaveBeenCalled();
  });

  /** Yeni malzemede tür mamul seçilir ve "GTIN öner"in yazdığı GTIN alana gelir. */
  async function suggestForNewFinished() {
    await userEvent.click(await screen.findByRole("button", { name: "Yeni" }));
    const dialog = await screen.findByRole("dialog");
    await choose(dialog, "Tür", "Mamul");
    await userEvent.click(await within(dialog).findByRole("button", { name: "GTIN öner" }));
    const gtin = within(dialog).getByLabelText(/GTIN \(barkod no\)/);
    expect(gtin).toHaveValue("8690000000123");
    return { dialog, gtin };
  }

  it("önerilen GTIN tür mamulden çıkınca silinir; mamule dönülünce öneri yeniden çıkar", async () => {
    vi.mocked(mdApi.suggestGtin).mockResolvedValue({
      active: true,
      gtin: "8690000000123",
      reason: "",
    });
    vi.mocked(mdApi.saveRecord).mockResolvedValue({ ...las, id: 9 });
    renderApp("/ana-veriler/malzemeler");

    const { dialog, gtin } = await suggestForNewFinished();
    // Firma GTIN'i önerisi yalnızca mamul için: hammaddeye geçilince alanda kalmaz.
    await choose(dialog, "Tür", "Hammadde");
    await waitFor(() => expect(gtin).toHaveValue(""));
    expect(within(dialog).queryByRole("button", { name: "GTIN öner" })).not.toBeInTheDocument();
    await choose(dialog, "Tür", "Mamul");
    expect(await within(dialog).findByRole("button", { name: "GTIN öner" })).toBeEnabled();

    await choose(dialog, "Tür", "Hammadde");
    await userEvent.type(within(dialog).getByLabelText(/^Ad/), "LAS");
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(mdApi.saveRecord).toHaveBeenCalledWith(
        "materials",
        null,
        expect.objectContaining({ material_type: "RAW", gtin: "" }),
      ),
    );
  });

  it("yenilenen önerinin sarı notu tür mamulden çıkıp öneri silinince kalkar", async () => {
    let next = "8690000000123";
    vi.mocked(mdApi.suggestGtin).mockImplementation(async () => ({
      active: true,
      gtin: next,
      reason: "",
    }));
    vi.mocked(mdApi.saveRecord).mockImplementationOnce(async () => {
      next = "8690000000130"; // başka bir kullanıcı 123'ü az önce aldı
      throw gtinTaken();
    });
    renderApp("/ana-veriler/malzemeler");

    const { dialog, gtin } = await saveSuggestedGtin();
    expect(
      await within(dialog).findByText(refreshed("8690000000123", "8690000000130")),
    ).toBeInTheDocument();
    expect(gtin).toHaveValue("8690000000130");
    await choose(dialog, "Tür", "Hammadde");
    await waitFor(() => expect(gtin).toHaveValue(""));
    expect(within(dialog).queryByText(/Yerine sıradaki önerilen GTIN/)).not.toBeInTheDocument();
  });

  it("elle yazılan GTIN tür mamulden çıkınca kalır (öneri değiştirildiyse de)", async () => {
    vi.mocked(mdApi.suggestGtin).mockResolvedValue({
      active: true,
      gtin: "8690000000123",
      reason: "",
    });
    vi.mocked(mdApi.saveRecord).mockResolvedValue({ ...las, id: 9, gtin: "8690000000017" });
    renderApp("/ana-veriler/malzemeler");

    const { dialog, gtin } = await suggestForNewFinished();
    // Öneri elle değiştirildi (ör. tedarikçinin GTIN'i): alandaki GTIN artık kullanıcının.
    await userEvent.clear(gtin);
    await userEvent.type(gtin, "8690000000017");
    await choose(dialog, "Tür", "Hammadde");
    expect(gtin).toHaveValue("8690000000017");

    await userEvent.type(within(dialog).getByLabelText(/^Ad/), "LAS");
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(mdApi.saveRecord).toHaveBeenCalledWith(
        "materials",
        null,
        expect.objectContaining({ material_type: "RAW", gtin: "8690000000017" }),
      ),
    );
  });

  it("tür mamulden çıkınca öneri unutulur: elle yazılan GTIN alınmışsa öneriyle değiştirilmez", async () => {
    vi.mocked(mdApi.suggestGtin)
      .mockResolvedValueOnce({ active: true, gtin: "8690000000123", reason: "" })
      .mockResolvedValue({ active: true, gtin: "8690000000130", reason: "" });
    vi.mocked(mdApi.saveRecord).mockRejectedValue(gtinTaken());
    const { queryClient } = renderApp("/ana-veriler/malzemeler");

    const { dialog, gtin } = await suggestForNewFinished();
    await choose(dialog, "Tür", "Hammadde");
    await waitFor(() => expect(gtin).toHaveValue(""));
    // Hammaddeye aynı GTIN elle yazılır; kayıt GTIN alınmış diye reddedilir.
    await userEvent.type(gtin, "8690000000123");
    await userEvent.type(within(dialog).getByLabelText(/^Ad/), "LAS");
    const save = within(dialog).getByRole("button", { name: "Kaydet" });
    await userEvent.click(save);

    expect(await within(dialog).findByText(takenDetail)).toBeInTheDocument();
    await waitFor(() => expect(save).toBeEnabled()); // kayıt hatası işlendi
    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
    expect(gtin).toHaveValue("8690000000123");
    expect(within(dialog).getByText(takenDetail)).toBeInTheDocument();
    expect(within(dialog).queryByText(/Yerine sıradaki önerilen GTIN/)).not.toBeInTheDocument();
    expect(mdApi.suggestGtin).toHaveBeenCalledTimes(1);
  });

  it("koli dönüşümünde 'Koli GTIN'i' çıkar; öneri malzemeden türetilir ve kaydedilir", async () => {
    records([finished]);
    vi.mocked(mdApi.suggestCaseGtin).mockResolvedValue({ gtin: "18690000000019", reason: "" });
    vi.mocked(mdApi.saveRecord).mockResolvedValue({ ...caseConversion, gtin_locked: false });
    renderApp("/ana-veriler/birim-donusumleri");

    await userEvent.click(await screen.findByRole("button", { name: "Yeni" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByLabelText(/Koli GTIN'i/)).not.toBeInTheDocument();
    await choose(dialog, "Birim", "KG - Kilogram");
    expect(within(dialog).queryByLabelText(/Koli GTIN'i/)).not.toBeInTheDocument();
    await choose(dialog, "Birim", "KOLI - Koli");
    const gtin = await within(dialog).findByLabelText(/Koli GTIN'i/);
    // Malzeme seçilmeden öneri yok.
    expect(
      within(dialog).queryByRole("button", { name: "Koli GTIN'i öner" }),
    ).not.toBeInTheDocument();

    await choose(dialog, "Malzeme", "MAM-1 - Bulaşık deterjanı 750 ml");
    await userEvent.click(within(dialog).getByRole("button", { name: "Koli GTIN'i öner" }));
    await waitFor(() => expect(gtin).toHaveValue("18690000000019"));
    expect(mdApi.suggestCaseGtin).toHaveBeenCalledWith(6);
    await userEvent.type(within(dialog).getByLabelText(/Temel birim karşılığı/), "12");
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(mdApi.saveRecord).toHaveBeenCalledWith("conversions", null, {
        material: 6,
        unit: 7,
        factor_to_base: "12",
        gtin: "18690000000019",
      }),
    );
  });

  it("koli GTIN'i türetilemezse nedeni görünür; koli dışı birime geçince yazılan GTIN silinir", async () => {
    records([finished]);
    vi.mocked(mdApi.suggestCaseGtin).mockResolvedValue({
      gtin: null,
      reason: "Malzemenin GTIN'i yok; koli GTIN'i türetilemez.",
    });
    vi.mocked(mdApi.saveRecord).mockResolvedValue({ ...caseConversion, unit: 1, unit_code: "KG" });
    renderApp("/ana-veriler/birim-donusumleri");

    await userEvent.click(await screen.findByRole("button", { name: "Yeni" }));
    const dialog = await screen.findByRole("dialog");
    await choose(dialog, "Malzeme", "MAM-1 - Bulaşık deterjanı 750 ml");
    await choose(dialog, "Birim", "KOLI - Koli");
    await userEvent.click(await within(dialog).findByRole("button", { name: "Koli GTIN'i öner" }));
    expect(
      await within(dialog).findByText("Malzemenin GTIN'i yok; koli GTIN'i türetilemez."),
    ).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText(/Koli GTIN'i/), "18690000000019");
    expect(within(dialog).queryByText(/türetilemez/)).not.toBeInTheDocument();

    await choose(dialog, "Birim", "KG - Kilogram");
    expect(within(dialog).queryByLabelText(/Koli GTIN'i/)).not.toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText(/Temel birim karşılığı/), "1");
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(mdApi.saveRecord).toHaveBeenCalledWith(
        "conversions",
        null,
        expect.objectContaining({ unit: 1, gtin: "" }),
      ),
    );
  });

  it("'Koli GTIN'i öner' yanıtı malzeme değiştikten sonra gelirse alana yazılmaz", async () => {
    const other: Material = { ...finished, id: 8, code: "MAM-2", name: "Cam temizleyici 500 ml" };
    records([finished, other]);
    const reply = deferred<mdApi.CaseGtinSuggestion>();
    vi.mocked(mdApi.suggestCaseGtin).mockReturnValueOnce(reply.promise);
    const { queryClient } = renderApp("/ana-veriler/birim-donusumleri");

    await userEvent.click(await screen.findByRole("button", { name: "Yeni" }));
    const dialog = await screen.findByRole("dialog");
    await choose(dialog, "Birim", "KOLI - Koli");
    await choose(dialog, "Malzeme", "MAM-1 - Bulaşık deterjanı 750 ml");
    await userEvent.click(within(dialog).getByRole("button", { name: "Koli GTIN'i öner" }));
    await waitFor(() => expect(mdApi.suggestCaseGtin).toHaveBeenCalledWith(6));
    await choose(dialog, "Malzeme", "MAM-2 - Cam temizleyici 500 ml");
    reply.resolve({ gtin: "18690000000019", reason: "" });

    // Yanıt işlendi; MAM-1'in koli GTIN'i MAM-2'nin dönüşümüne yazılmaz.
    await waitFor(() => expect(queryClient.isMutating()).toBe(0));
    expect(within(dialog).getByLabelText(/Koli GTIN'i/)).toHaveValue("");
    expect(within(dialog).getByRole("button", { name: "Koli GTIN'i öner" })).toBeEnabled();
  });

  it("'Koli GTIN'i öner' yanıtı koli dışı birime geçildikten sonra gelirse gizli alana yazılmaz", async () => {
    records([finished]);
    const reply = deferred<mdApi.CaseGtinSuggestion>();
    vi.mocked(mdApi.suggestCaseGtin).mockReturnValueOnce(reply.promise);
    vi.mocked(mdApi.saveRecord).mockResolvedValue({
      ...caseConversion,
      unit: 1,
      unit_code: "KG",
      gtin: "",
      gtin_locked: false,
    });
    const { queryClient } = renderApp("/ana-veriler/birim-donusumleri");

    await userEvent.click(await screen.findByRole("button", { name: "Yeni" }));
    const dialog = await screen.findByRole("dialog");
    await choose(dialog, "Malzeme", "MAM-1 - Bulaşık deterjanı 750 ml");
    await choose(dialog, "Birim", "KOLI - Koli");
    await userEvent.click(await within(dialog).findByRole("button", { name: "Koli GTIN'i öner" }));
    await waitFor(() => expect(mdApi.suggestCaseGtin).toHaveBeenCalledWith(6));
    await choose(dialog, "Birim", "KG - Kilogram");
    reply.resolve({ gtin: "18690000000019", reason: "" });

    // Yanıt işlendi; koli GTIN'i gizlenen alana yazılmaz, KG dönüşümü GTIN'siz kaydedilir.
    await waitFor(() => expect(queryClient.isMutating()).toBe(0));
    expect(within(dialog).queryByLabelText(/Koli GTIN'i/)).not.toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText(/Temel birim karşılığı/), "1");
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(mdApi.saveRecord).toHaveBeenCalledWith("conversions", null, {
        material: 6,
        unit: 1,
        factor_to_base: "1",
        gtin: "",
      }),
    );
  });

  it("'Koli GTIN'i öner' hatası malzeme değiştikten sonra gelirse gösterilmez", async () => {
    const other: Material = { ...finished, id: 8, code: "MAM-2", name: "Cam temizleyici 500 ml" };
    records([finished, other]);
    const reply = deferred<mdApi.CaseGtinSuggestion>();
    vi.mocked(mdApi.suggestCaseGtin).mockReturnValueOnce(reply.promise);
    const { queryClient } = renderApp("/ana-veriler/birim-donusumleri");

    await userEvent.click(await screen.findByRole("button", { name: "Yeni" }));
    const dialog = await screen.findByRole("dialog");
    await choose(dialog, "Birim", "KOLI - Koli");
    await choose(dialog, "Malzeme", "MAM-1 - Bulaşık deterjanı 750 ml");
    await userEvent.click(within(dialog).getByRole("button", { name: "Koli GTIN'i öner" }));
    await waitFor(() => expect(mdApi.suggestCaseGtin).toHaveBeenCalledWith(6));
    await choose(dialog, "Malzeme", "MAM-2 - Cam temizleyici 500 ml");
    reply.reject(httpError(500));

    // MAM-1 isteğinin hatası MAM-2 seçiliyken gösterilmez.
    await waitFor(() => expect(queryClient.isMutating()).toBe(0));
    expect(within(dialog).queryByText(/Beklenmeyen bir hata/)).not.toBeInTheDocument();
    // Seçili malzemenin isteği hata verirse hata görünür.
    vi.mocked(mdApi.suggestCaseGtin).mockRejectedValueOnce(httpError(500));
    await userEvent.click(within(dialog).getByRole("button", { name: "Koli GTIN'i öner" }));
    expect(await within(dialog).findByText(/Beklenmeyen bir hata/)).toBeInTheDocument();
    expect(mdApi.suggestCaseGtin).toHaveBeenLastCalledWith(8);
  });

  it("önerilen koli GTIN'i başka malzemeye geçilince silinir; öneri yeni malzeme için yeniden çıkar", async () => {
    const other: Material = { ...finished, id: 8, code: "MAM-2", name: "Cam temizleyici 500 ml" };
    records([finished, other]);
    vi.mocked(mdApi.suggestCaseGtin).mockResolvedValue({ gtin: "18690000000019", reason: "" });
    vi.mocked(mdApi.saveRecord).mockResolvedValue({
      ...caseConversion,
      material: 8,
      material_code: "MAM-2",
      gtin: "",
      gtin_locked: false,
    });
    renderApp("/ana-veriler/birim-donusumleri");

    await userEvent.click(await screen.findByRole("button", { name: "Yeni" }));
    const dialog = await screen.findByRole("dialog");
    await choose(dialog, "Birim", "KOLI - Koli");
    await choose(dialog, "Malzeme", "MAM-1 - Bulaşık deterjanı 750 ml");
    await userEvent.click(within(dialog).getByRole("button", { name: "Koli GTIN'i öner" }));
    const gtin = within(dialog).getByLabelText(/Koli GTIN'i/);
    await waitFor(() => expect(gtin).toHaveValue("18690000000019"));
    expect(
      within(dialog).queryByRole("button", { name: "Koli GTIN'i öner" }),
    ).not.toBeInTheDocument();

    // MAM-1'in GTIN'inden türetilen koli GTIN'i MAM-2'nin dönüşümünde kalmaz.
    await choose(dialog, "Malzeme", "MAM-2 - Cam temizleyici 500 ml");
    await waitFor(() => expect(gtin).toHaveValue(""));
    expect(within(dialog).getByRole("button", { name: "Koli GTIN'i öner" })).toBeEnabled();
    await userEvent.type(within(dialog).getByLabelText(/Temel birim karşılığı/), "12");
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(mdApi.saveRecord).toHaveBeenCalledWith("conversions", null, {
        material: 8,
        unit: 7,
        factor_to_base: "12",
        gtin: "",
      }),
    );
    expect(mdApi.suggestCaseGtin).toHaveBeenCalledTimes(1);
  });

  it("silinen koli GTIN'i önerisi unutulur: sonra elle yazılan aynı GTIN malzeme değişince kalır", async () => {
    const other: Material = { ...finished, id: 8, code: "MAM-2", name: "Cam temizleyici 500 ml" };
    records([finished, other]);
    vi.mocked(mdApi.suggestCaseGtin).mockResolvedValue({ gtin: "18690000000019", reason: "" });
    renderApp("/ana-veriler/birim-donusumleri");

    await userEvent.click(await screen.findByRole("button", { name: "Yeni" }));
    const dialog = await screen.findByRole("dialog");
    await choose(dialog, "Birim", "KOLI - Koli");
    await choose(dialog, "Malzeme", "MAM-1 - Bulaşık deterjanı 750 ml");
    await userEvent.click(within(dialog).getByRole("button", { name: "Koli GTIN'i öner" }));
    const gtin = within(dialog).getByLabelText(/Koli GTIN'i/);
    await waitFor(() => expect(gtin).toHaveValue("18690000000019"));
    await choose(dialog, "Malzeme", "MAM-2 - Cam temizleyici 500 ml");
    await waitFor(() => expect(gtin).toHaveValue(""));

    // Öneri silinince unutulur: kullanıcının sonra yazdığı GTIN (aynı değer olsa da) kalır.
    await userEvent.type(gtin, "18690000000019");
    await choose(dialog, "Malzeme", "MAM-1 - Bulaşık deterjanı 750 ml");
    await choose(dialog, "Malzeme", "MAM-2 - Cam temizleyici 500 ml");
    expect(gtin).toHaveValue("18690000000019");
  });

  it("elle yazılan koli GTIN'i malzeme değişince kalır (öneri değiştirildiyse de)", async () => {
    const other: Material = { ...finished, id: 8, code: "MAM-2", name: "Cam temizleyici 500 ml" };
    records([finished, other]);
    vi.mocked(mdApi.suggestCaseGtin).mockResolvedValue({ gtin: "18690000000019", reason: "" });
    vi.mocked(mdApi.saveRecord).mockResolvedValue({
      ...caseConversion,
      material: 8,
      material_code: "MAM-2",
      gtin: "28690000000016",
      gtin_locked: false,
    });
    renderApp("/ana-veriler/birim-donusumleri");

    await userEvent.click(await screen.findByRole("button", { name: "Yeni" }));
    const dialog = await screen.findByRole("dialog");
    await choose(dialog, "Birim", "KOLI - Koli");
    await choose(dialog, "Malzeme", "MAM-1 - Bulaşık deterjanı 750 ml");
    await userEvent.click(within(dialog).getByRole("button", { name: "Koli GTIN'i öner" }));
    const gtin = within(dialog).getByLabelText(/Koli GTIN'i/);
    await waitFor(() => expect(gtin).toHaveValue("18690000000019"));
    // Öneri elle değiştirildi: alandaki GTIN artık kullanıcının.
    await userEvent.clear(gtin);
    await userEvent.type(gtin, "28690000000016");

    await choose(dialog, "Malzeme", "MAM-2 - Cam temizleyici 500 ml");
    expect(gtin).toHaveValue("28690000000016");
    await userEvent.type(within(dialog).getByLabelText(/Temel birim karşılığı/), "12");
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(mdApi.saveRecord).toHaveBeenCalledWith("conversions", null, {
        material: 8,
        unit: 7,
        factor_to_base: "12",
        gtin: "28690000000016",
      }),
    );
  });

  it("'Koli GTIN'i öner' yanıtı beklenirken alana yazılan GTIN'i geç gelen öneri değiştirmez", async () => {
    records([finished]);
    const reply = deferred<mdApi.CaseGtinSuggestion>();
    vi.mocked(mdApi.suggestCaseGtin).mockReturnValueOnce(reply.promise);
    vi.mocked(mdApi.saveRecord).mockResolvedValue({
      ...caseConversion,
      gtin: "28690000000016",
      gtin_locked: false,
    });
    const { queryClient } = renderApp("/ana-veriler/birim-donusumleri");

    await userEvent.click(await screen.findByRole("button", { name: "Yeni" }));
    const dialog = await screen.findByRole("dialog");
    await choose(dialog, "Birim", "KOLI - Koli");
    await choose(dialog, "Malzeme", "MAM-1 - Bulaşık deterjanı 750 ml");
    await userEvent.click(within(dialog).getByRole("button", { name: "Koli GTIN'i öner" }));
    await waitFor(() => expect(mdApi.suggestCaseGtin).toHaveBeenCalledWith(6));
    const gtin = within(dialog).getByLabelText(/Koli GTIN'i/);
    await userEvent.type(gtin, "28690000000016");
    reply.resolve({ gtin: "18690000000019", reason: "" });

    // Yanıt işlendi; kullanıcının yazdığı GTIN kalır ve o kaydedilir.
    await waitFor(() => expect(queryClient.isMutating()).toBe(0));
    expect(gtin).toHaveValue("28690000000016");
    await userEvent.type(within(dialog).getByLabelText(/Temel birim karşılığı/), "12");
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(mdApi.saveRecord).toHaveBeenCalledWith("conversions", null, {
        material: 6,
        unit: 7,
        factor_to_base: "12",
        gtin: "28690000000016",
      }),
    );
  });

  /** Kilitli koli GTIN'inin açıklaması. */
  const caseLockHelp =
    "Lotu olan mamulün koli GTIN'i değiştirilemez. Koli içi miktar değişirse yeni miktarla birlikte yeni koli GTIN'i girilir.";
  /** Koli içi miktar değişince koli GTIN'inin açıklaması (eski GTIN'le). */
  const packHelp = (old: string) =>
    `Koli içi miktar değişince yeni koli GTIN'i gerekir (GS1). Eski GTIN ${old} eski miktarıyla arşivlenir; depodaki eski koliler okutulmaya devam eder.`;

  /** Koli dönüşümünü listeden açar (varsayılan: lotu olan mamulün kilitli koli GTIN'i). */
  async function openCase(conversion: mdApi.Conversion = caseConversion) {
    records([finished], [conversion]);
    const { queryClient } = renderApp("/ana-veriler/birim-donusumleri");
    await userEvent.click(await screen.findByText("MAM-1"));
    const dialog = await screen.findByRole("dialog");
    return {
      dialog,
      queryClient,
      factor: within(dialog).getByLabelText(/Temel birim karşılığı/),
      gtin: within(dialog).getByLabelText(/Koli GTIN'i/),
    };
  }

  /** "Temel birim karşılığı"nı siler ve yeni değeri yazar. */
  async function setFactor(factor: HTMLElement, value: string) {
    await userEvent.clear(factor);
    await userEvent.type(factor, value);
  }

  /** Alanın etiketinde zorunlu yıldızı var mı (Mantine `withAsterisk`)? */
  function marksRequired(input: HTMLElement): boolean {
    const label = input.ownerDocument.querySelector(`label[for="${input.id}"]`);
    return label?.hasAttribute("data-required") ?? false;
  }

  it("lotu olan mamulün koli GTIN'i değiştirilemez ve gönderilmez", async () => {
    records([finished], [caseConversion]);
    vi.mocked(mdApi.saveRecord).mockResolvedValue(caseConversion);
    renderApp("/ana-veriler/birim-donusumleri");

    expect(await screen.findByText("18690000000019")).toBeInTheDocument(); // liste sütunu
    await userEvent.click(screen.getByText("MAM-1"));
    const dialog = await screen.findByRole("dialog");
    const gtin = within(dialog).getByLabelText(/Koli GTIN'i/);
    expect(gtin).toBeDisabled();
    expect(gtin).toHaveValue("18690000000019");
    expect(gtin).toHaveAccessibleDescription(caseLockHelp);
    expect(
      within(dialog).queryByRole("button", { name: "Koli GTIN'i öner" }),
    ).not.toBeInTheDocument();
    // Eski koli GTIN'i yoksa liste çıkmaz.
    expect(within(dialog).queryByRole("list")).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(mdApi.saveRecord).toHaveBeenCalledWith("conversions", 21, { factor_to_base: "12" }),
    );
  });

  it("lotu olan mamulde koli içi miktar değişince koli GTIN'i açılır, boşalır ve yeni GTIN'le kaydedilir", async () => {
    vi.mocked(mdApi.suggestCaseGtin).mockResolvedValue({ gtin: "28690000000016", reason: "" });
    vi.mocked(mdApi.saveRecord).mockResolvedValue({
      ...caseConversion,
      factor_to_base: "24.000000",
      gtin: "28690000000016",
    });
    const { dialog, factor, gtin } = await openCase();
    expect(gtin).toBeDisabled();
    expect(marksRequired(gtin)).toBe(false);

    await setFactor(factor, "24");
    expect(gtin).toBeEnabled();
    expect(gtin).toHaveValue("");
    expect(marksRequired(gtin)).toBe(true);
    expect(gtin).toHaveAccessibleDescription(packHelp("18690000000019"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Koli GTIN'i öner" }));
    await waitFor(() => expect(gtin).toHaveValue("28690000000016"));
    expect(mdApi.suggestCaseGtin).toHaveBeenCalledWith(6);

    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    // Yeni miktar yeni koli GTIN'iyle birlikte gönderilir (eskisini sunucu arşivler).
    expect(mdApi.saveRecord).toHaveBeenCalledWith("conversions", 21, {
      factor_to_base: "24",
      gtin: "28690000000016",
    });
  });

  it.each([
    [
      "elle yazılan",
      async (_dialog: HTMLElement, gtin: HTMLElement) => {
        await userEvent.type(gtin, "28690000000016");
      },
    ],
    [
      "önerilen",
      async (dialog: HTMLElement, gtin: HTMLElement) => {
        await userEvent.click(within(dialog).getByRole("button", { name: "Koli GTIN'i öner" }));
        await waitFor(() => expect(gtin).toHaveValue("28690000000016"));
      },
    ],
  ])(
    "koli içi miktar silinip yeniden yazılınca %s yeni koli GTIN'i kalır ve gönderilir",
    async (_name, enterGtin) => {
      vi.mocked(mdApi.suggestCaseGtin).mockResolvedValue({ gtin: "28690000000016", reason: "" });
      vi.mocked(mdApi.saveRecord).mockResolvedValue({
        ...caseConversion,
        factor_to_base: "36.000000",
        gtin: "28690000000016",
      });
      const { dialog, factor, gtin } = await openCase();
      await setFactor(factor, "24");
      await enterGtin(dialog, gtin);

      // Boş miktar kayıttaki miktar değildir: alan açık ve zorunlu kalır, yeni GTIN durur.
      await userEvent.clear(factor);
      expect(gtin).toBeEnabled();
      expect(gtin).toHaveValue("28690000000016");
      expect(marksRequired(gtin)).toBe(true);
      await userEvent.type(factor, "36");
      expect(gtin).toBeEnabled();
      expect(gtin).toHaveValue("28690000000016");

      await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
      expect(mdApi.saveRecord).toHaveBeenCalledWith("conversions", 21, {
        factor_to_base: "36",
        gtin: "28690000000016",
      });
    },
  );

  it("koli içi miktar kayıttakinden farklı kalarak düzeltilince (24 → 26) yeni koli GTIN'i kalır ve gönderilir", async () => {
    vi.mocked(mdApi.saveRecord).mockResolvedValue({
      ...caseConversion,
      factor_to_base: "26.000000",
      gtin: "28690000000016",
    });
    const { dialog, factor, gtin } = await openCase();
    await setFactor(factor, "24");
    await userEvent.type(gtin, "28690000000016");

    // Alan yalnızca kilit açılıp kapanınca boşalır; açıkken miktarın her değişiminde değil.
    await userEvent.type(factor, "{backspace}6");
    expect(factor).toHaveValue("26");
    expect(gtin).toBeEnabled();
    expect(gtin).toHaveValue("28690000000016");

    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(mdApi.saveRecord).toHaveBeenCalledWith("conversions", 21, {
        factor_to_base: "26",
        gtin: "28690000000016",
      }),
    );
  });

  it.each([
    ["12", "12"],
    ["12,0", "12.0"],
    ["12.000000", "12.000000"],
    ["+12", "+12"],
  ])(
    "kayıttaki miktara (%s) dönülünce koli GTIN'i kayıttaki GTIN'le yeniden kilitlenir",
    async (same, sent) => {
      vi.mocked(mdApi.saveRecord).mockResolvedValue(caseConversion);
      const { dialog, factor, gtin } = await openCase();
      await setFactor(factor, "24");
      await userEvent.type(gtin, "28690000000016");
      expect(gtin).toHaveValue("28690000000016");

      // Miktarlar sunucudaki gibi sayı olarak karşılaştırılır: "12", "12,0", "12.000000" ve "+12"
      // kayıttaki 12'dir.
      await setFactor(factor, same);
      expect(gtin).toBeDisabled();
      expect(gtin).toHaveValue("18690000000019");
      expect(marksRequired(gtin)).toBe(false);
      expect(gtin).toHaveAccessibleDescription(caseLockHelp);
      expect(
        within(dialog).queryByRole("button", { name: "Koli GTIN'i öner" }),
      ).not.toBeInTheDocument();
      await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
      await waitFor(() => expect(mdApi.saveRecord).toHaveBeenCalled());
      // Kilitli koli GTIN'i gönderilmez.
      expect(vi.mocked(mdApi.saveRecord).mock.calls[0]).toEqual([
        "conversions",
        21,
        { factor_to_base: sent },
      ]);
    },
  );

  it.each([
    [
      "yeni koli GTIN'i girilmezse",
      "",
      {
        code: "case_gtin_required",
        detail:
          "Koli içi miktar değişince GS1 yeni koli GTIN'i ister: yeni koli GTIN'ini de girin. Eski GTIN eski miktarıyla arşivlenir; depodaki eski koliler okutulmaya devam eder.",
      },
    ],
    [
      "arşivdeki eski koli GTIN'i girilirse",
      "28690000000016",
      {
        code: "gtin_taken",
        detail: "Bu GTIN MAM-1 malzemesinin eski koli GTIN'i (arşivde); bir daha kullanılamaz.",
      },
    ],
  ])("koli içi miktar değişip %s sunucunun hatası formda görünür", async (_name, typed, body) => {
    vi.mocked(mdApi.saveRecord).mockRejectedValue(httpError(400, body));
    const { dialog, factor, gtin } = await openCase();
    await setFactor(factor, "24");
    if (typed) await userEvent.type(gtin, typed);
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));

    const error = await within(dialog).findByText(body.detail);
    expect(alertStyle(error)).toContain("--mantine-color-red-light"); // kırmızı
    expect(mdApi.saveRecord).toHaveBeenCalledWith("conversions", 21, {
      factor_to_base: "24",
      gtin: typed,
    });
    // Alan açık kalır: GTIN düzeltilip yeniden kaydedilebilir.
    expect(gtin).toBeEnabled();
    expect(gtin).toHaveValue(typed);
  });

  it("eksi miktar da kayıttakinden farklıdır (sunucudaki gibi): koli GTIN'i açılır, yeni GTIN'le gönderilir", async () => {
    // Sunucu -12'yi değişmiş miktar sayar (yeni koli GTIN'i ister), sıfırdan büyük olma kuralını
    // sonra denetler.
    const detail = "Dönüşüm katsayısı sıfırdan büyük olmalıdır.";
    vi.mocked(mdApi.saveRecord).mockRejectedValue(
      httpError(400, {
        code: "validation_error",
        detail: "Gönderilen bilgiler geçersiz.",
        errors: { non_field_errors: [detail] },
      }),
    );
    const { dialog, factor, gtin } = await openCase();
    await setFactor(factor, "-12");
    expect(gtin).toBeEnabled();
    expect(gtin).toHaveValue("");
    expect(marksRequired(gtin)).toBe(true);
    expect(gtin).toHaveAccessibleDescription(packHelp("18690000000019"));

    await userEvent.type(gtin, "28690000000016");
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    const error = await within(dialog).findByText(detail);
    expect(alertStyle(error)).toContain("--mantine-color-red-light"); // kırmızı
    expect(mdApi.saveRecord).toHaveBeenCalledWith("conversions", 21, {
      factor_to_base: "-12",
      gtin: "28690000000016",
    });
  });

  it("eski koli GTIN'leri koli GTIN'inin altında en yeniden eskiye listelenir", async () => {
    const changed: mdApi.Conversion = {
      ...caseConversion,
      base_unit_code: "LT",
      factor_to_base: "9.000000",
      gtin: "38690000000013",
      retired_gtins: [
        {
          gtin: "28690000000016",
          factor_to_base: "4.500000",
          replaced_by: "38690000000013",
          retired_at: "2027-03-11T22:30:00Z", // İstanbul'da 12.03.2027
          retired_by_name: "Ayşe Planlama",
        },
        {
          gtin: "18690000000019",
          factor_to_base: "12.000000",
          replaced_by: "28690000000016",
          retired_at: "2026-11-05T10:00:00+03:00",
          retired_by_name: "Ayşe Planlama",
        },
      ],
    };
    const { dialog, factor, gtin } = await openCase(changed);
    const rows = () =>
      within(within(dialog).getByRole("list", { name: "Eski koli GTIN'leri:" }))
        .getAllByRole("listitem")
        .map((item) => item.textContent);
    const expected = [
      "28690000000016 · 1 koli = 4,5 LT · 12.03.2027'de değişti",
      "18690000000019 · 1 koli = 12 LT · 05.11.2026'da değişti",
    ];
    expect(rows()).toEqual(expected);
    // Koli içi miktar yeniden değişirken de liste kalır; açıklama bugünkü GTIN'i anlatır.
    await setFactor(factor, "18");
    expect(gtin).toHaveAccessibleDescription(packHelp("38690000000013"));
    expect(rows()).toEqual(expected);
  });

  it("kilitsiz koli dönüşümünde miktar değişince koli GTIN'i kalır; eski koli GTIN'leri yine görünür", async () => {
    // Ör. mamulden hammaddeye çevrilmiş malzeme: kilit yok ama arşiv kalır.
    const unlocked: mdApi.Conversion = {
      ...caseConversion,
      gtin_locked: false,
      retired_gtins: [
        {
          gtin: "28690000000016",
          factor_to_base: "6.000000",
          replaced_by: "18690000000019",
          retired_at: "2026-11-05T10:00:00+03:00",
          retired_by_name: "Ayşe Planlama",
        },
      ],
    };
    vi.mocked(mdApi.saveRecord).mockResolvedValue({ ...unlocked, factor_to_base: "24.000000" });
    const { dialog, factor, gtin } = await openCase(unlocked);
    expect(gtin).toBeEnabled();
    expect(
      within(within(dialog).getByRole("list", { name: "Eski koli GTIN'leri:" })).getByRole(
        "listitem",
      ),
    ).toHaveTextContent("28690000000016 · 1 koli = 6 ADET · 05.11.2026'da değişti");

    await setFactor(factor, "24");
    expect(gtin).toHaveValue("18690000000019");
    expect(marksRequired(gtin)).toBe(false);
    expect(within(dialog).queryByText(/Koli içi miktar değişince/)).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(mdApi.saveRecord).toHaveBeenCalledWith("conversions", 21, {
        factor_to_base: "24",
        gtin: "18690000000019",
      }),
    );
  });

  it("'Koli GTIN'i öner' yanıtı kayıttaki miktara dönüldükten sonra gelirse kilitli alana yazılmaz", async () => {
    const reply = deferred<mdApi.CaseGtinSuggestion>();
    vi.mocked(mdApi.suggestCaseGtin).mockReturnValueOnce(reply.promise);
    const { dialog, queryClient, factor, gtin } = await openCase();
    await setFactor(factor, "24");
    await userEvent.click(within(dialog).getByRole("button", { name: "Koli GTIN'i öner" }));
    await waitFor(() => expect(mdApi.suggestCaseGtin).toHaveBeenCalledWith(6));
    await setFactor(factor, "12");
    reply.resolve({ gtin: "28690000000016", reason: "" });

    // Yanıt işlendi; kayıttaki GTIN kilitli alanda kalır.
    await waitFor(() => expect(queryClient.isMutating()).toBe(0));
    expect(gtin).toBeDisabled();
    expect(gtin).toHaveValue("18690000000019");
    // Miktar yeniden değişince alan boş gelir; öneri yeniden istenebilir.
    await setFactor(factor, "24");
    expect(gtin).toHaveValue("");
    expect(within(dialog).getByRole("button", { name: "Koli GTIN'i öner" })).toBeEnabled();
  });

  it("öneri nedeni kayıttaki miktara dönülünce kalkar, miktar yeniden değişince geri gelmez", async () => {
    const reason = "Boş koli GTIN'i kalmadı (gösterge haneleri 1-8 kullanılmış).";
    vi.mocked(mdApi.suggestCaseGtin).mockResolvedValue({ gtin: null, reason });
    const { dialog, factor, gtin } = await openCase();
    await setFactor(factor, "24");
    await userEvent.click(within(dialog).getByRole("button", { name: "Koli GTIN'i öner" }));
    expect(await within(dialog).findByText(reason)).toBeInTheDocument();

    await setFactor(factor, "12");
    expect(within(dialog).queryByText(reason)).not.toBeInTheDocument();
    await setFactor(factor, "24");
    expect(gtin).toHaveValue("");
    expect(within(dialog).queryByText(reason)).not.toBeInTheDocument();
  });
});
