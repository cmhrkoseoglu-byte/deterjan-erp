import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../api/auth";
import * as mdApi from "../../api/masterdata";
import type { Material } from "../../api/masterdata";
import { httpError, page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";

vi.mock("../../api/auth");
vi.mock("../../api/masterdata", async (importOriginal) => {
  const original = await importOriginal<typeof mdApi>();
  return {
    ...original,
    listRecords: vi.fn(),
    saveRecord: vi.fn(),
    setRecordActive: vi.fn(),
    uploadImport: vi.fn(),
  };
});

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
});
