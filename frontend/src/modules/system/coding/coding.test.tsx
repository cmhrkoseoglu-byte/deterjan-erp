import { QueryObserver } from "@tanstack/react-query";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../../api/auth";
import * as codingApi from "../../../api/coding";
import type { CodeTypeRow, RevertPreview } from "../../../api/coding";
import * as labelsApi from "../../../api/labels";
import type { Gs1Settings } from "../../../api/labels";
import * as opsApi from "../../../api/ops";
import type { BackupRun, SystemStatus } from "../../../api/ops";
import * as workflowApi from "../../../api/workflow";
import { formatDateTime } from "../../../i18n/format";
import { httpError, page, userWith } from "../../../test/fixtures";
import { renderApp } from "../../../test/render";

vi.mock("../../../api/auth");
vi.mock("../../../api/coding");
vi.mock("../../../api/labels", async (importOriginal) => ({
  ...(await importOriginal<typeof labelsApi>()),
  getGs1Settings: vi.fn(),
  updateGs1Settings: vi.fn(),
  getLabelSettings: vi.fn(),
}));
vi.mock("../../../api/ops");
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
const EQUIPMENT = row({
  key: "masterdata.equipment",
  label: "Ekipman",
  prefix: "",
  type_field: "equipment_type",
  type_prefixes: { MIXING_TANK: "KRT", FILLING_LINE: "DLM" },
  format: "",
  next: "",
  longest: "",
  last_number: 0,
  types: [
    {
      value: "MIXING_TANK",
      label: "Karıştırma tankı",
      prefix: "KRT",
      format: "KRT-0000000",
      next: "KRT-0000004",
      last_number: 3,
    },
    {
      value: "FILLING_LINE",
      label: "Dolum hattı",
      prefix: "DLM",
      format: "DLM-0000000",
      next: "DLM-0000003",
      last_number: 2,
    },
  ],
  samples: [],
});
const LOCATION_TYPE = row({
  key: "masterdata.location",
  label: "Lokasyon",
  prefix: "LOC",
  format: "LOC-0000000",
  next: "LOC-0000001",
  last_number: 0,
});
const RUN: codingApi.CodeMigrationRun = {
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

function code(prefix: string, number: number): string {
  return `${prefix}-${String(number).padStart(7, "0")}`;
}

/** Önizleme taklidi: düzenlenen önekin sayacı (yeni önek 0'dan) ve yazılan sıradaki numara. */
function previewOf(base: CodeTypeRow) {
  return async (_key: string, body: codingApi.CodePreviewRequest) => {
    if (base.types.length) {
      const types = base.types.map((type) => {
        const prefix = body.type_prefixes?.[type.value] ?? type.prefix;
        const typed = body.counters?.[prefix];
        const last =
          typed !== undefined ? typed - 1 : prefix === type.prefix ? type.last_number : 0;
        return { ...type, prefix, last_number: last, next: code(prefix, last + 1) };
      });
      return { valid: true, error: null, example: { ...base, types } };
    }
    const prefix = body.prefix ?? base.prefix;
    const typed = body.counters?.[prefix];
    const last = typed !== undefined ? typed - 1 : prefix === base.prefix ? base.last_number : 0;
    return {
      valid: true,
      error: null,
      example: { ...base, prefix, last_number: last, next: code(prefix, last + 1) },
    };
  };
}

async function confirmSave(dialog: HTMLElement) {
  const save = within(dialog).getByRole("button", { name: "Kaydet" });
  await waitFor(() => expect(save).toBeEnabled());
  await userEvent.click(save);
  const confirm = await screen.findByText(/verilmiş olanlar değişmez/);
  await userEvent.click(
    within(confirm.closest("section") ?? document.body).getByRole("button", { name: "Kaydet" }),
  );
}

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
    vi.mocked(codingApi.listRecodeRuns).mockResolvedValue(page([]));
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

  it("geçmiş bölümü uygulanan kod göçlerini de listeler; geri alma Kod göçündedir", async () => {
    vi.mocked(codingApi.listRecodeRuns).mockResolvedValue(page([RUN]));
    renderApp("/sistem/kodlama?bolum=gecmis");

    expect(await screen.findByText("Malzeme (Göç #7)")).toBeInTheDocument();
    expect(screen.getByText("Henüz biçim değişikliği yok.")).toBeInTheDocument();
    expect(screen.getByText(/Göçü geri almak için Kod göçü bölümünü/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Geri al" })).not.toBeInTheDocument();
  });

  it("önek değişince sayaç yeni önekten gelir; yazılan sayaç önizlemeye ve kayda gider", async () => {
    vi.mocked(codingApi.previewCodeType).mockImplementation(previewOf(MATERIAL));
    vi.mocked(codingApi.updateCodeType).mockResolvedValue({ ...MATERIAL, prefix: "HAM" });
    renderApp("/sistem/kodlama");

    await userEvent.click(await screen.findByRole("button", { name: "Düzenle: Malzeme" }));
    const dialog = await screen.findByRole("dialog", { name: "Biçim: Malzeme" });
    const counter = within(dialog).getByRole("textbox", { name: "Sıradaki numara" });
    const preview = within(dialog).getByTestId("coding-preview");
    await waitFor(() => expect(counter).toHaveValue("25"));
    const prefix = within(dialog).getByRole("textbox", { name: "Önek" });
    await userEvent.clear(prefix);
    await userEvent.type(prefix, "HAM");
    // Gösterilen numara eski önekin (MLZ: 25) değil, düzenlenen önekin sayacıdır.
    await waitFor(() => expect(counter).toHaveValue("1"));
    expect(preview).toHaveTextContent("HAM-0000001");

    // Eski önekteki değere eşit olsa da yazılan numara önizlemeye ve kayda gider.
    await userEvent.clear(counter);
    expect(counter).toHaveValue("");
    await userEvent.type(counter, "25");
    await waitFor(() => expect(preview).toHaveTextContent("HAM-0000025"));
    expect(codingApi.previewCodeType).toHaveBeenLastCalledWith("masterdata.material", {
      prefix: "HAM",
      width: 7,
      counters: { HAM: 25 },
    });
    await userEvent.type(within(dialog).getByLabelText(/Değişiklik notu/), "Hammadde öneki");
    await confirmSave(dialog);

    await waitFor(() =>
      expect(codingApi.updateCodeType).toHaveBeenCalledWith("masterdata.material", {
        prefix: "HAM",
        width: 7,
        is_active: false,
        note: "Hammadde öneki",
        counters: { HAM: 25 },
      }),
    );
  });

  it("boşaltılan sayaç düzenlenen önekin numarasına döner; önek aynıysa sayaç gönderilmez", async () => {
    vi.mocked(codingApi.previewCodeType).mockImplementation(previewOf(MATERIAL));
    vi.mocked(codingApi.updateCodeType).mockResolvedValue(MATERIAL);
    renderApp("/sistem/kodlama");

    await userEvent.click(await screen.findByRole("button", { name: "Düzenle: Malzeme" }));
    const dialog = await screen.findByRole("dialog", { name: "Biçim: Malzeme" });
    const counter = within(dialog).getByRole("textbox", { name: "Sıradaki numara" });
    await waitFor(() => expect(counter).toHaveValue("25"));
    await userEvent.clear(counter);
    await userEvent.tab();
    expect(counter).toHaveValue("25");
    await userEvent.click(within(dialog).getByLabelText(/Biçimi etkinleştir/));
    await userEvent.type(within(dialog).getByLabelText(/Değişiklik notu/), "Etkin");
    await confirmSave(dialog);

    await waitFor(() =>
      expect(codingApi.updateCodeType).toHaveBeenCalledWith("masterdata.material", {
        prefix: "MLZ",
        width: 7,
        is_active: true,
        note: "Etkin",
      }),
    );
  });

  it("önek değişip sayaç yazılmasa da gösterilen numara yeni önekle kaydedilir", async () => {
    vi.mocked(codingApi.previewCodeType).mockImplementation(previewOf(MATERIAL));
    vi.mocked(codingApi.updateCodeType).mockResolvedValue({ ...MATERIAL, prefix: "HAM" });
    renderApp("/sistem/kodlama");

    await userEvent.click(await screen.findByRole("button", { name: "Düzenle: Malzeme" }));
    const dialog = await screen.findByRole("dialog", { name: "Biçim: Malzeme" });
    const counter = within(dialog).getByRole("textbox", { name: "Sıradaki numara" });
    await waitFor(() => expect(counter).toHaveValue("25"));
    const prefix = within(dialog).getByRole("textbox", { name: "Önek" });
    await userEvent.clear(prefix);
    await userEvent.type(prefix, "HAM");
    await waitFor(() => expect(counter).toHaveValue("1"));
    expect(codingApi.previewCodeType).toHaveBeenLastCalledWith("masterdata.material", {
      prefix: "HAM",
      width: 7,
    });
    await userEvent.type(within(dialog).getByLabelText(/Değişiklik notu/), "Hammadde öneki");
    await confirmSave(dialog);

    await waitFor(() =>
      expect(codingApi.updateCodeType).toHaveBeenCalledWith("masterdata.material", {
        prefix: "HAM",
        width: 7,
        is_active: false,
        note: "Hammadde öneki",
        counters: { HAM: 1 },
      }),
    );
  });

  it("türe göre önekte sayaç değişen önekten gelir; önek değişen ve yazılan sayaçlar kaydedilir", async () => {
    vi.mocked(codingApi.listCodeTypes).mockResolvedValue([EQUIPMENT]);
    vi.mocked(codingApi.previewCodeType).mockImplementation(previewOf(EQUIPMENT));
    vi.mocked(codingApi.updateCodeType).mockResolvedValue(EQUIPMENT);
    renderApp("/sistem/kodlama");

    await userEvent.click(await screen.findByRole("button", { name: "Düzenle: Ekipman" }));
    const dialog = await screen.findByRole("dialog", { name: "Biçim: Ekipman" });
    const tank = within(dialog).getByRole("textbox", { name: "Sıradaki numara: Karıştırma tankı" });
    const line = within(dialog).getByRole("textbox", { name: "Sıradaki numara: Dolum hattı" });
    await waitFor(() => expect(tank).toHaveValue("4"));
    const tankPrefix = within(dialog).getByRole("textbox", { name: "Önek: Karıştırma tankı" });
    await userEvent.clear(tankPrefix);
    await userEvent.type(tankPrefix, "TNK");
    await waitFor(() => expect(tank).toHaveValue("1"));
    await userEvent.clear(line);
    await userEvent.type(line, "3");
    const preview = within(dialog).getByTestId("coding-preview");
    await waitFor(() => expect(preview).toHaveTextContent("Karıştırma tankı: TNK-0000001"));
    expect(preview).toHaveTextContent("Dolum hattı: DLM-0000003");
    expect(codingApi.previewCodeType).toHaveBeenLastCalledWith("masterdata.equipment", {
      width: 7,
      type_prefixes: { MIXING_TANK: "TNK", FILLING_LINE: "DLM" },
      counters: { DLM: 3 },
    });
    await userEvent.type(within(dialog).getByLabelText(/Değişiklik notu/), "Tank öneki");
    await confirmSave(dialog);

    await waitFor(() =>
      expect(codingApi.updateCodeType).toHaveBeenCalledWith("masterdata.equipment", {
        width: 7,
        type_prefixes: { MIXING_TANK: "TNK", FILLING_LINE: "DLM" },
        is_active: false,
        note: "Tank öneki",
        counters: { TNK: 1, DLM: 3 },
      }),
    );
  });

  it("sıra hanesi silinince en küçük değere atlamaz; aralık dışında önizleme ve kayıt bekler", async () => {
    vi.mocked(codingApi.previewCodeType).mockResolvedValue({
      valid: true,
      error: null,
      example: PRODUCTION,
    });
    renderApp("/sistem/kodlama?bolum=belge");

    await userEvent.click(await screen.findByRole("button", { name: "Düzenle: Üretim emri" }));
    const dialog = await screen.findByRole("dialog", { name: "Biçim: Üretim emri" });
    const width = within(dialog).getByRole("textbox", { name: "Sıra hanesi" });
    const save = within(dialog).getByRole("button", { name: "Kaydet" });
    await waitFor(() => expect(width).toHaveValue("5"));
    await userEvent.type(within(dialog).getByLabelText(/Değişiklik notu/), "Altı hane");
    await userEvent.clear(width);
    expect(width).toHaveValue(""); // en küçük değere (4) atlamaz
    expect(save).toBeDisabled();
    await userEvent.type(width, "6");
    expect(width).toHaveValue("6");
    await waitFor(() =>
      expect(codingApi.previewCodeType).toHaveBeenLastCalledWith("document.UE", {
        prefix: "UE",
        width: 6,
        year_format: "YYYY",
      }),
    );
    await waitFor(() => expect(save).toBeEnabled());

    await userEvent.clear(width);
    await userEvent.type(width, "9");
    expect(within(dialog).getByText("Sıra hanesi 4-7 arasında olmalıdır.")).toBeInTheDocument();
    expect(save).toBeDisabled();
    await userEvent.tab(); // çıkışta sınıra çekilir
    expect(width).toHaveValue("7");
    await waitFor(() => expect(save).toBeEnabled());
    const widths = vi.mocked(codingApi.previewCodeType).mock.calls.map(([, body]) => body.width);
    expect(widths).not.toContain(9);

    await userEvent.clear(width);
    await userEvent.tab(); // boş bırakılırsa kayıtlı haneye döner
    expect(width).toHaveValue("5");
  });

  it("önizleme isteği hata verirse mesajı gösterir ve kaydetmeyi engeller", async () => {
    vi.mocked(codingApi.previewCodeType).mockRejectedValue(
      httpError(500, { detail: "Önizleme alınamadı." }),
    );
    renderApp("/sistem/kodlama");

    await userEvent.click(await screen.findByRole("button", { name: "Düzenle: Malzeme" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Değişiklik notu/), "Deneme");
    expect(await within(dialog).findByText("Önizleme alınamadı.")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Kaydet" })).toBeDisabled();
  });
});

describe("Sistem > Kodlama sistematiği > Kod göçü", () => {
  const run = RUN;
  const hoursAgo = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString();
  function backup(extra: Partial<BackupRun> = {}): BackupRun {
    return {
      id: 1,
      kind: "backup",
      kind_display: "Gece yedeği",
      run_id: "r1",
      source_run_id: "",
      started_at: hoursAgo(3),
      finished_at: hoursAgo(3),
      status: "ok",
      status_display: "Başarılı",
      message: "",
      database_bytes: 1,
      media_bytes: 1,
      media_files: 1,
      tables: 1,
      rows: 1,
      offsite: "ok",
      offsite_display: "Kopyalandı",
      offsite_message: "",
      mismatches: [],
      ...extra,
    };
  }
  function status(runs: BackupRun[]): SystemStatus {
    return { checks: [], disks: [], load_15: null, cpu_count: null, queue_length: null, runs };
  }
  function revertPreview(extra: Partial<RevertPreview> = {}): RevertPreview {
    return {
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
      ...extra,
    };
  }
  async function chooseType(label: string) {
    await userEvent.click(await screen.findByRole("textbox", { name: "Kod türü" }));
    await userEvent.click(await screen.findByRole("option", { name: label }));
  }

  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(authApi.fetchCsrf).mockResolvedValue();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("admin"));
    vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
    vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
    vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
    vi.mocked(codingApi.listCodeTypes).mockResolvedValue([MATERIAL, UNIT, PRODUCTION]);
    vi.mocked(codingApi.listRecodeRuns).mockResolvedValue(page([]));
    vi.mocked(opsApi.fetchSystemStatus).mockResolvedValue(status([backup()]));
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

  it("uygula düğmesinin yanında son yedeğin zamanını ve durumunu gösterir", async () => {
    const finished = hoursAgo(3);
    vi.mocked(opsApi.fetchSystemStatus).mockResolvedValue(
      status([
        backup({ id: 2, kind: "restore_test", status: "failed", status_display: "Başarısız" }),
        backup({ finished_at: finished }),
      ]),
    );
    renderApp("/sistem/kodlama?bolum=goc");

    await chooseType("Malzeme");
    const notice = await screen.findByTestId("migration-backup");
    await waitFor(() =>
      expect(notice).toHaveTextContent(`Son yedek: ${formatDateTime(finished)} (Başarılı)`),
    );
    expect(notice).not.toHaveTextContent("Son 24 saatte başarılı yedek yok.");
    expect(
      within(notice).getByRole("link", { name: "Sistem durumunda son yedekleri gör" }),
    ).toHaveAttribute("href", "/sistem/durum");
  });

  it("son 24 saatte başarılı yedek yoksa uyarır (uygulamayı engellemez)", async () => {
    const failed = hoursAgo(2);
    vi.mocked(opsApi.fetchSystemStatus).mockResolvedValue(
      status([
        backup({ id: 3, finished_at: failed, status: "failed", status_display: "Başarısız" }),
        backup({ id: 2, finished_at: hoursAgo(30) }),
      ]),
    );
    renderApp("/sistem/kodlama?bolum=goc");

    await chooseType("Malzeme");
    const notice = await screen.findByTestId("migration-backup");
    await waitFor(() =>
      expect(notice).toHaveTextContent(`Son yedek: ${formatDateTime(failed)} (Başarısız)`),
    );
    expect(notice).toHaveTextContent("Son 24 saatte başarılı yedek yok.");
    await userEvent.type(screen.getByLabelText(/Göç notu/), "Canlı kodlar");
    expect(screen.getByRole("button", { name: "1 kodu taşı" })).toBeEnabled();
  });

  it("değişecek kod yoksa boş tablo yerine yalnız bilgi gösterir", async () => {
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
      ],
      change_count: 0,
      keep_count: 1,
      problem_count: 0,
      checksum: "x",
    });
    renderApp("/sistem/kodlama?bolum=goc");

    await chooseType("Malzeme");
    expect(
      await screen.findByText("Değişecek kod yok; bütün kodlar biçime uyuyor."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Eski kod" })).not.toBeInTheDocument();
    expect(screen.queryByText("0 kod değişecek, 1 kod aynı kalacak.")).not.toBeInTheDocument();
    expect(screen.queryByTestId("migration-backup")).not.toBeInTheDocument();
  });

  it("değişecek kod yok ama öneki tanımsız kayıt varsa sorunu söyler", async () => {
    vi.mocked(codingApi.previewRecode).mockResolvedValue({
      key: "masterdata.equipment",
      label: "Ekipman",
      active: true,
      rows: [
        {
          id: 1,
          label: "X-1 - Yeni tür",
          old: "X-1",
          new: "",
          action: "problem",
          is_active: true,
          problem: "Bu türün öneki tanımlı değil.",
        },
      ],
      change_count: 0,
      keep_count: 0,
      problem_count: 1,
      checksum: "x",
    });
    renderApp("/sistem/kodlama?bolum=goc");

    await chooseType("Malzeme");
    expect(
      await screen.findByText("Öneki tanımsız kayıtlar var; önce biçimi düzeltin."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Değişecek kod yok; bütün kodlar biçime uyuyor."),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Bu türün öneki tanımlı değil.")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Göç notu/)).not.toBeInTheDocument();
  });

  it("göç notu tür değişince silinir; vazgeçilen geri alma notu başka göçe taşınmaz", async () => {
    vi.mocked(codingApi.listCodeTypes).mockResolvedValue([MATERIAL, LOCATION_TYPE]);
    vi.mocked(codingApi.listRecodeRuns).mockResolvedValue(page([{ ...run, id: 9 }, run]));
    vi.mocked(codingApi.previewRevert).mockImplementation(async (id) => revertPreview({ run: id }));
    renderApp("/sistem/kodlama?bolum=goc");

    await chooseType("Malzeme");
    await userEvent.type(await screen.findByLabelText(/Göç notu/), "Malzeme notu");
    await chooseType("Lokasyon");
    await waitFor(() =>
      expect(codingApi.previewRecode).toHaveBeenCalledWith("masterdata.location"),
    );
    expect(await screen.findByLabelText(/Göç notu/)).toHaveValue("");

    await userEvent.click(screen.getAllByRole("button", { name: "Geri al" })[1]);
    let dialog = await screen.findByRole("dialog", { name: "Göç #7: geri al" });
    await userEvent.type(within(dialog).getByLabelText(/Geri alma notu/), "Hatalı göç");
    await userEvent.click(within(dialog).getByRole("button", { name: "Vazgeç" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await userEvent.click(screen.getAllByRole("button", { name: "Geri al" })[0]);
    dialog = await screen.findByRole("dialog", { name: "Göç #9: geri al" });
    expect(within(dialog).getByLabelText(/Geri alma notu/)).toHaveValue("");
  });

  it("göç listesi yüklenemezse hatayı gösterir, 'henüz göç yok' demez", async () => {
    vi.mocked(codingApi.listRecodeRuns).mockRejectedValue(
      httpError(500, { detail: "Göçler alınamadı." }),
    );
    renderApp("/sistem/kodlama?bolum=goc");

    expect(await screen.findByText("Göçler alınamadı.")).toBeInTheDocument();
    expect(screen.queryByText("Henüz kod göçü yapılmadı.")).not.toBeInTheDocument();
  });

  it("geri alma önizlemesi hata verirse ya da göç zaten geri alındıysa açıkça söyler", async () => {
    vi.mocked(codingApi.listRecodeRuns).mockResolvedValue(page([run, { ...run, id: 9 }]));
    vi.mocked(codingApi.previewRevert).mockImplementation(async (id) => {
      if (id === 9) throw httpError(400, { code: "run_not_found", detail: "Kod göçü bulunamadı." });
      return revertPreview({
        rows: [
          {
            id: 2,
            label: "DENEME - Deneme",
            old: "DENEME",
            new: "MLZ-0000025",
            current: "DENEME",
            action: "skip",
          },
        ],
        revert_count: 0,
        already_reverted: true,
      });
    });
    renderApp("/sistem/kodlama?bolum=goc");

    await userEvent.click((await screen.findAllByRole("button", { name: "Geri al" }))[0]);
    let dialog = await screen.findByRole("dialog", { name: "Göç #7: geri al" });
    expect(await within(dialog).findByText("Bu göç zaten geri alındı.")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "0 kaydı geri al" })).toBeDisabled();
    expect(within(dialog).queryByLabelText(/Geri alma notu/)).not.toBeInTheDocument();
    // Liste yenilenir; başka biri geri aldıysa "Geri alındı" görünür.
    await waitFor(() => expect(codingApi.listRecodeRuns).toHaveBeenCalledTimes(2));
    await userEvent.click(within(dialog).getByRole("button", { name: "Vazgeç" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    await userEvent.click(screen.getAllByRole("button", { name: "Geri al" })[1]);
    dialog = await screen.findByRole("dialog", { name: "Göç #9: geri al" });
    expect(await within(dialog).findByText("Kod göçü bulunamadı.")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "0 kaydı geri al" })).toBeDisabled();
  });
});

describe("Sistem > Kodlama sistematiği > Çıktılar", () => {
  const coa: codingApi.OutputDocumentRow = {
    key: "quality.coa",
    label: "Analiz sertifikası",
    group: "Kalite",
    formats: ["PDF"],
    legal: false,
    suggested_code: "FR-KAL-001",
    doc_code: "",
    first_issue_date: null,
    is_active: false,
    revision_no: null,
    revision_date: null,
    template_version: 1,
    template_changed: false,
    revisions: [],
  };
  const revision: codingApi.OutputRevision = {
    id: 1,
    revision_no: 1,
    revision_date: "2026-10-15",
    change_note: "Lot alanı eklendi",
    approved_by_name: "Kalite Müdürü",
    approved_on: "2026-10-14",
    template_version: 1,
    created_at: "2026-10-14T10:00:00+03:00",
    created_by_name: "Sistem Yöneticisi",
  };
  const waybill: codingApi.OutputDocumentRow = {
    ...coa,
    key: "sales.waybill",
    label: "İrsaliye",
    group: "Sevkiyat",
    legal: true,
    suggested_code: "FR-SVK-001",
    doc_code: "FR-SVK-001",
    first_issue_date: "2026-01-10",
    is_active: true,
    revision_no: 1,
    revision_date: "2026-10-15",
    template_changed: true,
    revisions: [revision],
  };

  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(authApi.fetchCsrf).mockResolvedValue();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("admin"));
    vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
    vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
    vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
    vi.mocked(codingApi.listCodeTypes).mockResolvedValue([MATERIAL]);
    vi.mocked(codingApi.listOutputs).mockResolvedValue([waybill, coa]);
  });

  it("çıktıları gruplarıyla, öneriyle, revizyon ve bant durumuyla listeler", async () => {
    renderApp("/sistem/kodlama?bolum=cikti");

    expect(await screen.findByText("Analiz sertifikası")).toBeInTheDocument();
    const groups = screen.getAllByRole("columnheader").map((cell) => cell.textContent);
    // Gruplar Türkçe sırayla: Kalite, Sevkiyat.
    expect(groups.filter((text) => text === "Kalite" || text === "Sevkiyat")).toEqual([
      "Kalite",
      "Sevkiyat",
    ]);
    expect(screen.getByText("Öneri: FR-KAL-001")).toBeInTheDocument();
    expect(screen.getByText("Basılmıyor")).toBeInTheDocument();
    expect(screen.getByText("FR-SVK-001")).toBeInTheDocument();
    expect(screen.getByText("Rev. 01 · 15.10.2026")).toBeInTheDocument();
    expect(screen.getByText("Basılıyor")).toBeInTheDocument();
    expect(screen.getByText("Yasal belge")).toBeInTheDocument();
    expect(screen.getByText("Şablon değişti")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Düzenle: İrsaliye" }));
    const dialog = await screen.findByRole("dialog", { name: "Çıktı: İrsaliye" });
    expect(within(dialog).getByText(/mali müşavirinize danışın/)).toBeInTheDocument();
    expect(within(dialog).getByText(/yeni revizyon girin/)).toBeInTheDocument();
    expect(within(dialog).getByText("Lot alanı eklendi")).toBeInTheDocument();
    expect(within(dialog).getByText("Yeni revizyon: Rev. 02")).toBeInTheDocument();
    // Revizyonu olan çıktıda revizyon no seçilmez (birer artar).
    expect(within(dialog).queryByLabelText(/Revizyon no/)).not.toBeInTheDocument();
  });

  it("doküman no ve ilk yayın tarihini notla kaydeder; revizyonsuz bant açılamaz", async () => {
    vi.mocked(codingApi.updateOutput).mockResolvedValue({
      ...coa,
      doc_code: "FR-KAL-001",
      first_issue_date: "2026-01-10",
    });
    renderApp("/sistem/kodlama?bolum=cikti");

    await userEvent.click(
      await screen.findByRole("button", { name: "Düzenle: Analiz sertifikası" }),
    );
    const dialog = await screen.findByRole("dialog", { name: "Çıktı: Analiz sertifikası" });
    expect(within(dialog).getByLabelText(/Çıktıya basılsın/)).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText("Doküman no"), "fr-kal-001");
    fireEvent.change(within(dialog).getByLabelText(/İlk yayın tarihi/), {
      target: { value: "2026-01-10" },
    });
    const save = within(dialog).getByRole("button", { name: "Kaydet" });
    expect(save).toBeDisabled(); // not zorunlu
    await userEvent.type(within(dialog).getByLabelText(/Değişiklik notu/), "Doküman listesi");
    await userEvent.click(save);

    await waitFor(() =>
      expect(codingApi.updateOutput).toHaveBeenCalledWith("quality.coa", {
        note: "Doküman listesi",
        doc_code: "FR-KAL-001",
        first_issue_date: "2026-01-10",
      }),
    );
  });

  it("ilk revizyonu kalite sistemindeki numarasıyla, onayla ekler", async () => {
    vi.mocked(codingApi.addOutputRevision).mockResolvedValue({
      ...coa,
      revision_no: 3,
      revision_date: "2026-10-01",
      revisions: [{ ...revision, revision_no: 3 }],
    });
    renderApp("/sistem/kodlama?bolum=cikti");

    await userEvent.click(
      await screen.findByRole("button", { name: "Düzenle: Analiz sertifikası" }),
    );
    const dialog = await screen.findByRole("dialog", { name: "Çıktı: Analiz sertifikası" });
    expect(within(dialog).getByText("İlk revizyon")).toBeInTheDocument();
    const add = within(dialog).getByRole("button", { name: "Revizyonu ekle" });
    expect(add).toBeDisabled(); // açıklama ve onaylayan zorunlu
    const number = within(dialog).getByLabelText(/Revizyon no/);
    await userEvent.clear(number);
    await userEvent.type(number, "3");
    fireEvent.change(within(dialog).getByLabelText(/Yürürlük tarihi/), {
      target: { value: "2026-10-01" },
    });
    fireEvent.change(within(dialog).getByLabelText(/Onay tarihi/), {
      target: { value: "2026-09-30" },
    });
    await userEvent.type(within(dialog).getByLabelText(/^Onaylayan/), "Kalite Müdürü");
    await userEvent.type(within(dialog).getByLabelText(/Değişiklik açıklaması/), "İlk yayın");
    await userEvent.click(add);
    const confirm = await screen.findByText(/sonradan değiştirilemez/);
    await userEvent.click(
      within(confirm.closest("section") ?? document.body).getByRole("button", {
        name: "Revizyonu ekle",
      }),
    );

    await waitFor(() =>
      expect(codingApi.addOutputRevision).toHaveBeenCalledWith("quality.coa", {
        revision_date: "2026-10-01",
        change_note: "İlk yayın",
        approved_by_name: "Kalite Müdürü",
        approved_on: "2026-09-30",
        revision_no: 3,
      }),
    );
  });
});

describe("Sistem > Kodlama sistematiği > GS1", () => {
  const GS1: Gs1Settings = {
    company_prefix: "8690000",
    extension_digit: 0,
    next_sscc_serial: 41,
    next_item_reference: null,
    sscc_enabled: true,
    gtin_suggestion_enabled: false,
    item_reference_digits: 5,
    updated_at: "2026-11-05T10:00:00+03:00",
    updated_by_name: "Sistem Yöneticisi",
  };

  async function openEditor() {
    await userEvent.click(await screen.findByRole("button", { name: "Düzenle: GS1" }));
    return screen.findByRole("dialog", { name: "GS1 ayarları" });
  }

  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(authApi.fetchCsrf).mockResolvedValue();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("admin"));
    vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
    vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
    vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
    vi.mocked(codingApi.listCodeTypes).mockResolvedValue([MATERIAL, UNIT]);
    vi.mocked(labelsApi.getGs1Settings).mockResolvedValue(GS1);
  });

  it("ayarları, SSCC ve GTIN önerisi durumunu gösterir; öteki bölümler çalışır", async () => {
    renderApp("/sistem/kodlama?bolum=gs1");

    const table = await screen.findByTestId("gs1-settings");
    expect(within(table).getByText("8690000")).toBeInTheDocument();
    expect(within(table).getByText("41")).toBeInTheDocument();
    expect(within(table).getByText("SSCC açık")).toBeInTheDocument();
    expect(within(table).getByText("GTIN önerisi kapalı")).toBeInTheDocument();
    expect(within(table).getByText("Tanımlı değil")).toBeInTheDocument(); // ürün referansı
    expect(table).toHaveTextContent(`${formatDateTime(GS1.updated_at)} · Sistem Yöneticisi`);
    expect(screen.getByRole("radio", { name: "GS1" })).toBeChecked();

    await userEvent.click(screen.getByText("Ana veri kodları"));
    expect(await screen.findByText("MLZ-0000025")).toBeInTheDocument();
    expect(screen.queryByTestId("gs1-settings")).not.toBeInTheDocument();
  });

  it("uzantı hanesini ve ürün referansını notla kaydeder; önek aynıysa onay sorulmaz", async () => {
    vi.mocked(labelsApi.updateGs1Settings).mockResolvedValue({
      ...GS1,
      extension_digit: 3,
      next_item_reference: 12,
      gtin_suggestion_enabled: true,
    });
    renderApp("/sistem/kodlama?bolum=gs1");

    const dialog = await openEditor();
    const save = within(dialog).getByRole("button", { name: "Kaydet" });
    expect(save).toBeDisabled(); // değişiklik yok
    expect(within(dialog).getByRole("textbox", { name: "Sıradaki SSCC seri no" })).toBeDisabled();
    const extension = within(dialog).getByRole("textbox", { name: "SSCC uzantı hanesi" });
    await userEvent.clear(extension);
    await userEvent.type(extension, "3");
    await userEvent.type(
      within(dialog).getByRole("textbox", { name: "Sıradaki ürün referansı" }),
      "12",
    );
    expect(save).toBeDisabled(); // not zorunlu
    await userEvent.type(within(dialog).getByLabelText(/Değişiklik notu/), "Yeni seri");
    await userEvent.click(save);

    await waitFor(() =>
      expect(labelsApi.updateGs1Settings).toHaveBeenCalledWith({
        extension_digit: 3,
        next_item_reference: 12,
        note: "Yeni seri",
      }),
    );
    expect(screen.queryByText(/yeni önekte devam eder/)).not.toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const table = screen.getByTestId("gs1-settings");
    expect(within(table).getByText("GTIN önerisi açık")).toBeInTheDocument();
    expect(table).toHaveTextContent("12 (5 hane)");
  });

  it("önek değişince onay ister; sunucunun reddi pencerede görünür", async () => {
    vi.mocked(labelsApi.updateGs1Settings).mockRejectedValue(
      httpError(400, {
        code: "busy",
        detail: "Başka bir işlem sürüyor; birkaç saniye sonra yeniden deneyin.",
      }),
    );
    renderApp("/sistem/kodlama?bolum=gs1");

    const dialog = await openEditor();
    const prefix = within(dialog).getByRole("textbox", { name: "Firma öneki" });
    await userEvent.clear(prefix);
    await userEvent.type(prefix, "8691234");
    await userEvent.type(within(dialog).getByLabelText(/Değişiklik notu/), "GS1 Türkiye yeni önek");
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    const confirm = await screen.findByRole("dialog", { name: "Emin misiniz?" });
    expect(confirm).toHaveTextContent(
      "Firma öneki değişiyor. SSCC seri no yeni önekte devam eder; basılmış etiketler değişmez. Kaydedilsin mi?",
    );
    expect(labelsApi.updateGs1Settings).not.toHaveBeenCalled();
    await userEvent.click(within(confirm).getByRole("button", { name: "Kaydet" }));

    await waitFor(() =>
      expect(labelsApi.updateGs1Settings).toHaveBeenCalledWith({
        company_prefix: "8691234",
        note: "GS1 Türkiye yeni önek",
      }),
    );
    expect(
      await within(dialog).findByText(
        "Başka bir işlem sürüyor; birkaç saniye sonra yeniden deneyin.",
      ),
    ).toBeInTheDocument();
  });

  it("önek değişince eski ürün referansı silinir; yeni önekte yazılan referans gönderilir", async () => {
    vi.mocked(labelsApi.getGs1Settings).mockResolvedValue({
      ...GS1,
      next_item_reference: 12,
      gtin_suggestion_enabled: true,
    });
    vi.mocked(labelsApi.updateGs1Settings).mockResolvedValue({
      ...GS1,
      company_prefix: "86912345",
      next_item_reference: 7,
      gtin_suggestion_enabled: true,
      item_reference_digits: 4,
    });
    renderApp("/sistem/kodlama?bolum=gs1");

    const dialog = await openEditor();
    const reference = within(dialog).getByRole("textbox", { name: "Sıradaki ürün referansı" });
    expect(reference).toHaveValue("12");
    const prefix = within(dialog).getByRole("textbox", { name: "Firma öneki" });
    await userEvent.clear(prefix);
    await userEvent.type(prefix, "86912345");
    // Referans önekin numaralamasıdır: yeni önekte ilk boş referans girilir (4 hane).
    expect(reference).toHaveValue("");
    expect(within(dialog).getByText(/Önek değişince ürün referansı silinir/)).toHaveTextContent(
      "(0-9999)",
    );
    await userEvent.type(reference, "7");
    await userEvent.type(within(dialog).getByLabelText(/Değişiklik notu/), "Yeni GS1 üyeliği");
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    const confirm = await screen.findByRole("dialog", { name: "Emin misiniz?" });
    await userEvent.click(within(confirm).getByRole("button", { name: "Kaydet" }));

    await waitFor(() =>
      expect(labelsApi.updateGs1Settings).toHaveBeenCalledWith({
        company_prefix: "86912345",
        next_item_reference: 7,
        note: "Yeni GS1 üyeliği",
      }),
    );
  });

  it("kayıttan sonra etiket ayarları yenilenir (etiket ayarları ve palet bölümü GS1'i gösterir)", async () => {
    vi.mocked(labelsApi.updateGs1Settings).mockResolvedValue({ ...GS1, extension_digit: 3 });
    vi.mocked(labelsApi.getLabelSettings).mockResolvedValue({
      company_name: "Inncos",
      gs1_company_prefix: "8690000",
      sscc_extension_digit: 0,
      next_sscc_serial: 41,
      default_printer: null,
      default_printer_code: null,
      sscc_enabled: true,
      updated_at: "2026-11-05T10:00:00+03:00",
    });
    const { queryClient } = renderApp("/sistem/kodlama?bolum=gs1");
    // Etiket ayarlarını gösteren açık bir ekranın yerine aynı anahtarı izleyen sorgu.
    const observer = new QueryObserver(queryClient, {
      queryKey: labelsApi.labelQueryKeys.settings,
      queryFn: labelsApi.getLabelSettings,
    });
    const unsubscribe = observer.subscribe(() => {});
    await waitFor(() => expect(labelsApi.getLabelSettings).toHaveBeenCalledTimes(1));

    const dialog = await openEditor();
    const extension = within(dialog).getByRole("textbox", { name: "SSCC uzantı hanesi" });
    await userEvent.clear(extension);
    await userEvent.type(extension, "3");
    await userEvent.type(within(dialog).getByLabelText(/Değişiklik notu/), "Yeni uzantı");
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(labelsApi.getLabelSettings).toHaveBeenCalledTimes(2));
    unsubscribe();
  });

  it("geçersiz önek ve hane sınırını aşan ürün referansı kaydı engeller", async () => {
    renderApp("/sistem/kodlama?bolum=gs1");

    const dialog = await openEditor();
    await userEvent.type(within(dialog).getByLabelText(/Değişiklik notu/), "Deneme");
    const save = within(dialog).getByRole("button", { name: "Kaydet" });
    const prefix = within(dialog).getByRole("textbox", { name: "Firma öneki" });
    const reference = within(dialog).getByRole("textbox", { name: "Sıradaki ürün referansı" });
    await userEvent.clear(prefix);
    await userEvent.type(prefix, "86900");
    expect(within(dialog).getByText("Firma öneki 6-12 rakam olmalıdır.")).toBeInTheDocument();
    expect(reference).toBeDisabled();
    expect(save).toBeDisabled();

    await userEvent.type(prefix, "00"); // 8690000: 7 haneli önek, ürün referansı 5 hane
    expect(reference).toBeEnabled();
    await userEvent.type(reference, "100000");
    expect(
      within(dialog).getByText("Ürün referansı en çok 5 hanedir (0-99999)."),
    ).toBeInTheDocument();
    expect(save).toBeDisabled();
    await userEvent.clear(reference);
    await userEvent.type(reference, "99999");
    expect(save).toBeEnabled();
    expect(labelsApi.updateGs1Settings).not.toHaveBeenCalled();
  });

  it("önek silinince ürün referansı da silinir; onay SSCC ve GTIN önerisinin kapanacağını söyler", async () => {
    vi.mocked(labelsApi.getGs1Settings).mockResolvedValue({
      ...GS1,
      next_item_reference: 12,
      gtin_suggestion_enabled: true,
    });
    vi.mocked(labelsApi.updateGs1Settings).mockResolvedValue({
      ...GS1,
      company_prefix: "",
      next_item_reference: null,
      sscc_enabled: false,
      gtin_suggestion_enabled: false,
      item_reference_digits: null,
    });
    renderApp("/sistem/kodlama?bolum=gs1");

    const dialog = await openEditor();
    const reference = within(dialog).getByRole("textbox", { name: "Sıradaki ürün referansı" });
    expect(reference).toHaveValue("12");
    await userEvent.clear(within(dialog).getByRole("textbox", { name: "Firma öneki" }));
    expect(reference).toBeDisabled();
    expect(reference).toHaveValue("");
    await userEvent.type(within(dialog).getByLabelText(/Değişiklik notu/), "GS1 kullanılmıyor");
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    const confirm = await screen.findByRole("dialog", { name: "Emin misiniz?" });
    expect(confirm).toHaveTextContent(
      "Firma öneki siliniyor. SSCC palet etiketi ve GTIN önerisi kapanır; basılmış etiketler değişmez. Kaydedilsin mi?",
    );
    await userEvent.click(within(confirm).getByRole("button", { name: "Kaydet" }));

    await waitFor(() =>
      expect(labelsApi.updateGs1Settings).toHaveBeenCalledWith({
        company_prefix: "",
        next_item_reference: null,
        note: "GS1 kullanılmıyor",
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const table = screen.getByTestId("gs1-settings");
    expect(within(table).getByText("SSCC kapalı")).toBeInTheDocument();
    expect(within(table).getAllByText("Tanımlı değil")).toHaveLength(2); // önek ve ürün referansı
  });
});
