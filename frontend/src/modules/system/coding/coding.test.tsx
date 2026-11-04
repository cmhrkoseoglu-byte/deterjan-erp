import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../../api/auth";
import * as codingApi from "../../../api/coding";
import type { CodeTypeRow } from "../../../api/coding";
import * as workflowApi from "../../../api/workflow";
import { page, userWith } from "../../../test/fixtures";
import { renderApp } from "../../../test/render";

vi.mock("../../../api/auth");
vi.mock("../../../api/coding");
vi.mock("../../../api/workflow");

function row(extra: Partial<CodeTypeRow>): CodeTypeRow {
  return {
    key: "masterdata.material",
    kind: "master",
    label: "Malzeme",
    configurable: true,
    locked: false,
    free: false,
    scanned: true,
    prefix: "MLZ",
    width: 7,
    type_field: "",
    type_prefixes: {},
    year_format: "",
    date_format: "",
    is_active: false,
    revision: 0,
    updated_at: null,
    updated_by: "",
    format: "MLZ-0000000",
    next: "MLZ-0000025",
    longest: "MLZ-9999999",
    last_number: 24,
    types: [],
    samples: ["MLZ-0000001"],
    ...extra,
  };
}

const MATERIAL = row({});
const UNIT = row({
  key: "masterdata.unitofmeasure",
  kind: "standard",
  label: "Birim",
  configurable: false,
  samples: ["ADET", "KG"],
});
const PRODUCTION = row({
  key: "document.UE",
  kind: "document",
  label: "Üretim emri",
  prefix: "UE",
  width: 5,
  year_format: "YYYY",
  format: "UE-2026-00000",
  next: "UE-2026-00009",
  longest: "UE-2026-99999",
  last_number: 8,
  samples: [],
});
const WAYBILL = row({
  key: "document.SV",
  kind: "document",
  label: "Sevkiyat (irsaliye no)",
  configurable: false,
  locked: true,
  prefix: "SV",
  width: 5,
  year_format: "YYYY",
  format: "SV-2026-00000",
  next: "SV-2026-00001",
  last_number: 0,
  samples: [],
});
const PURCHASE_LOT = row({
  key: "lot.H",
  kind: "lot",
  label: "Satın alma lotu (mal kabul)",
  prefix: "H",
  width: 3,
  date_format: "YYYYMMDD",
  format: "H-20261104-000",
  next: "H-20261104-001",
  longest: "H-20261104-999",
  last_number: 0,
  samples: [],
});

describe("Sistem > Kodlama sistematiği", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(authApi.fetchCsrf).mockResolvedValue();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("admin"));
    vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
    vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
    vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
    vi.mocked(codingApi.listCodeTypes).mockResolvedValue([
      MATERIAL,
      UNIT,
      PRODUCTION,
      WAYBILL,
      PURCHASE_LOT,
    ]);
    vi.mocked(codingApi.previewCodeType).mockResolvedValue({
      valid: true,
      error: null,
      example: MATERIAL,
    });
    vi.mocked(codingApi.listCodeRevisions).mockResolvedValue(page([]));
  });

  it("ana veri kodlarını ve standart kodları gösterir", async () => {
    renderApp("/sistem/kodlama");

    expect(await screen.findByText("Malzeme")).toBeInTheDocument();
    expect(screen.getByText("MLZ-0000000")).toBeInTheDocument();
    expect(screen.getByText("MLZ-0000025")).toBeInTheDocument();
    expect(screen.getByText("Kapalı")).toBeInTheDocument();
    expect(screen.getByText("Standart kod")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Düzenle: Birim" })).not.toBeInTheDocument();
  });

  it("malzeme biçimini notla ve onayla etkinleştirir", async () => {
    vi.mocked(codingApi.updateCodeType).mockResolvedValue({ ...MATERIAL, is_active: true });
    renderApp("/sistem/kodlama");

    await userEvent.click(await screen.findByRole("button", { name: "Düzenle: Malzeme" }));
    const dialog = await screen.findByRole("dialog", { name: "Biçim: Malzeme" });
    expect(await within(dialog).findByText("MLZ-0000025")).toBeInTheDocument();
    expect(within(dialog).getByTestId("coding-preview")).toHaveTextContent("Sıradaki");
    const save = within(dialog).getByRole("button", { name: "Kaydet" });
    expect(save).toBeDisabled(); // not zorunlu
    await userEvent.click(within(dialog).getByLabelText(/Biçimi etkinleştir/));
    await userEvent.type(within(dialog).getByLabelText(/Değişiklik notu/), "Canlıya geçiş");
    await waitFor(() => expect(save).toBeEnabled());
    await userEvent.click(save);
    const confirm = await screen.findByText(/verilmiş olanlar değişmez/);
    await userEvent.click(
      within(confirm.closest("section") ?? document.body).getByRole("button", { name: "Kaydet" }),
    );

    await waitFor(() =>
      expect(codingApi.updateCodeType).toHaveBeenCalledWith("masterdata.material", {
        prefix: "MLZ",
        width: 7,
        is_active: true,
        note: "Canlıya geçiş",
      }),
    );
  });

  it("önizlemedeki kural ihlali kaydetmeyi engeller", async () => {
    vi.mocked(codingApi.previewCodeType).mockResolvedValue({
      valid: false,
      error: { code: "prefix_in_use", detail: "“KAT” öneki Malzeme kategorisi için kullanılıyor." },
      example: null,
    });
    renderApp("/sistem/kodlama");

    await userEvent.click(await screen.findByRole("button", { name: "Düzenle: Malzeme" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Değişiklik notu/), "Deneme");
    expect(await within(dialog).findByText(/öneki Malzeme kategorisi için/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Kaydet" })).toBeDisabled();
  });

  it("belge numaralarında irsaliye numarası değiştirilemez", async () => {
    renderApp("/sistem/kodlama?bolum=belge");

    expect(await screen.findByText("Üretim emri")).toBeInTheDocument();
    expect(screen.getByText("UE-2026-00009")).toBeInTheDocument();
    expect(screen.getByText("Değiştirilemez")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Düzenle: Üretim emri" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Düzenle: Sevkiyat (irsaliye no)" }),
    ).not.toBeInTheDocument();
  });

  it("lot tarih biçimini ISO 8601 seçenekleriyle düzenler", async () => {
    vi.mocked(codingApi.updateCodeType).mockResolvedValue(PURCHASE_LOT);
    renderApp("/sistem/kodlama?bolum=lot");

    await userEvent.click(
      await screen.findByRole("button", { name: "Düzenle: Satın alma lotu (mal kabul)" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("Tarih")).toHaveValue(
      "YYYYAAGG: ISO 8601 takvim tarihi (20261104)",
    );
  });

  it("geçmiş bölümü biçim değişikliklerini listeler", async () => {
    vi.mocked(codingApi.listCodeRevisions).mockResolvedValue(
      page([
        {
          id: 1,
          key: "masterdata.material",
          label: "Malzeme",
          revision: 1,
          prefix: "MLZ",
          type_prefixes: {},
          width: 7,
          year_format: "",
          date_format: "",
          is_active: true,
          counters: { MLZ: 25 },
          note: "Biçim etkinleştirildi",
          changed_at: "2026-11-04T18:00:00+03:00",
          changed_by_name: "Sistem Yöneticisi",
        },
      ]),
    );
    renderApp("/sistem/kodlama?bolum=gecmis");

    expect(await screen.findByText("Biçim etkinleştirildi")).toBeInTheDocument();
    expect(screen.getByText("Malzeme (Rev. 1)")).toBeInTheDocument();
    expect(screen.getByText(/MLZ sayacı: sıradaki 25/)).toBeInTheDocument();
  });
});
