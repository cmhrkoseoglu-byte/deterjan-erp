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

describe("Sistem > Kodlama sistematiği > Kod göçü", () => {
  const run: codingApi.CodeMigrationRun = {
    id: 7,
    key: "masterdata.material",
    label: "Malzeme",
    kind: "apply",
    mapping: [{ id: 2, label: "DENEME - Deneme", old: "DENEME", new: "MLZ-0000025" }],
    note: "Göç",
    reverts: null,
    reverted: false,
    count: 1,
    created_at: "2026-11-04T19:00:00+03:00",
    created_by_name: "Sistem Yöneticisi",
  };

  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(authApi.fetchCsrf).mockResolvedValue();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("admin"));
    vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
    vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
    vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
    vi.mocked(codingApi.listCodeTypes).mockResolvedValue([MATERIAL, UNIT, PRODUCTION]);
    vi.mocked(codingApi.listRecodeRuns).mockResolvedValue(page([]));
    vi.mocked(codingApi.previewRecode).mockResolvedValue({
      key: "masterdata.material",
      label: "Malzeme",
      active: true,
      rows: [
        {
          id: 1,
          label: "MLZ-0000001 - SLES",
          old: "MLZ-0000001",
          new: "MLZ-0000001",
          action: "keep",
          is_active: true,
          problem: "",
        },
        {
          id: 2,
          label: "DENEME - Deneme",
          old: "DENEME",
          new: "MLZ-0000025",
          action: "change",
          is_active: false,
          problem: "",
        },
      ],
      change_count: 1,
      keep_count: 1,
      problem_count: 0,
      checksum: "abc123",
    });
  });

  it("önizler, yalnız değişecekleri gösterir, notla ve onayla uygular", async () => {
    vi.mocked(codingApi.applyRecode).mockResolvedValue(run);
    renderApp("/sistem/kodlama?bolum=goc");

    await userEvent.click(await screen.findByRole("textbox", { name: "Kod türü" }));
    expect(screen.queryByRole("option", { name: "Birim" })).not.toBeInTheDocument();
    await userEvent.click(await screen.findByRole("option", { name: "Malzeme" }));
    expect(await screen.findByText("1 kod değişecek, 1 kod aynı kalacak.")).toBeInTheDocument();
    expect(screen.getByText("MLZ-0000025")).toBeInTheDocument();
    expect(screen.getByText("(pasif)")).toBeInTheDocument();
    expect(screen.queryByText("MLZ-0000001 - SLES")).not.toBeInTheDocument();

    const apply = screen.getByRole("button", { name: "1 kodu taşı" });
    expect(apply).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Göç notu/), "Canlı kodlar");
    await userEvent.click(apply);
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Malzeme: 1 kod yeni biçime taşınsın mı?");
    await userEvent.click(within(dialog).getByRole("button", { name: "1 kodu taşı" }));
    await waitFor(() =>
      expect(codingApi.applyRecode).toHaveBeenCalledWith(
        "masterdata.material",
        "abc123",
        "Canlı kodlar",
      ),
    );
  });

  it("uygulanan göçü notla geri alır", async () => {
    vi.mocked(codingApi.listRecodeRuns).mockResolvedValue(page([run]));
    vi.mocked(codingApi.previewRevert).mockResolvedValue({
      run: 7,
      key: "masterdata.material",
      label: "Malzeme",
      rows: [
        {
          id: 2,
          label: "MLZ-0000025 - Deneme",
          old: "DENEME",
          new: "MLZ-0000025",
          current: "MLZ-0000025",
          action: "revert",
        },
      ],
      revert_count: 1,
      already_reverted: false,
    });
    vi.mocked(codingApi.revertRecode).mockResolvedValue({ ...run, id: 8, kind: "revert" });
    renderApp("/sistem/kodlama?bolum=goc");

    expect(await screen.findByText("Malzeme (Göç #7)")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Geri al" }));
    const dialog = await screen.findByRole("dialog", { name: "Göç #7: geri al" });
    expect(await within(dialog).findByText("Geri döner")).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText(/Geri alma notu/), "Hatalı göç");
    await userEvent.click(within(dialog).getByRole("button", { name: "1 kaydı geri al" }));
    await waitFor(() => expect(codingApi.revertRecode).toHaveBeenCalledWith(7, "Hatalı göç"));
  });
});
