import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as attachmentsApi from "../../api/attachments";
import * as authApi from "../../api/auth";
import * as labelsApi from "../../api/labels";
import * as mdApi from "../../api/masterdata";
import * as qualityApi from "../../api/quality";
import type {
  QualityDecision,
  Sample,
  SampleDetail,
  SpecLine,
  TestResult,
} from "../../api/quality";
import * as workflowApi from "../../api/workflow";
import { httpError, page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";
import { recordPath } from "../../workflow/recordLinks";

vi.mock("../../api/auth");
vi.mock("../../api/attachments", async (importOriginal) => ({
  ...(await importOriginal<typeof attachmentsApi>()),
  listAttachments: vi.fn(),
}));
vi.mock("../../api/labels", async (importOriginal) => ({
  ...(await importOriginal<typeof labelsApi>()),
  listPrinters: vi.fn(),
  getLabelSettings: vi.fn(),
}));
vi.mock("../../api/quality", async (importOriginal) => ({
  ...(await importOriginal<typeof qualityApi>()),
  sampleQueue: vi.fn(),
  listSamples: vi.fn(),
  getSample: vi.fn(),
  recordResult: vi.fn(),
  decide: vi.fn(),
  listDecisions: vi.fn(),
  reviewDecision: vi.fn(),
  listSpecifications: vi.fn(),
}));
vi.mock("../../api/masterdata", async (importOriginal) => ({
  ...(await importOriginal<typeof mdApi>()),
  listRecords: vi.fn(),
}));
vi.mock("../../api/workflow");

function sample(overrides: Partial<Sample> = {}): Sample {
  return {
    id: 31,
    number: "NM-2026-00001",
    status: "PENDING",
    status_display: "Bekliyor",
    lot: 7,
    lot_no: "H-261015-001",
    lot_status: "QUARANTINE",
    material: 50,
    material_code: "SLES",
    material_name: "SLES %70",
    material_type: "RAW",
    stage: "INCOMING",
    stage_display: "Giriş kontrolü",
    origin: "GOODS_RECEIPT",
    origin_display: "Mal kabul",
    specification: 2,
    specification_label: "v1",
    taken_by: 1,
    taken_by_name: "Depo",
    taken_at: "2026-10-15T10:00:00+03:00",
    retain_location: null,
    retain_location_code: null,
    note: "",
    decided_at: null,
    created_by_name: "Depo",
    created_at: "2026-10-15T10:00:00+03:00",
    waiting_minutes: 45,
    ...overrides,
  };
}

function specLine(overrides: Partial<SpecLine> = {}): SpecLine {
  return {
    id: 101,
    specification: 2,
    sequence: 1,
    test: 1,
    test_code: "PH",
    test_name: "pH",
    result_type: "NUMERIC",
    unit: "",
    decimal_places: 2,
    min_value: "6.0000",
    max_value: "8.0000",
    target_value: "7.0000",
    text_expected: null,
    is_mandatory: true,
    ...overrides,
  };
}

function result(overrides: Partial<TestResult> = {}): TestResult {
  return {
    id: 501,
    spec_line: 101,
    test_code: "PH",
    numeric_value: "9.1000",
    text_value: "",
    passed: null,
    is_within_spec: false,
    measured_by_name: "Laboratuvar",
    measured_at: "2026-10-15T11:00:00+03:00",
    instrument: "",
    note: "",
    superseded_by: null,
    created_at: "2026-10-15T11:00:00+03:00",
    ...overrides,
  };
}

function detail(overrides: Partial<SampleDetail> = {}): SampleDetail {
  return {
    ...sample(),
    lines: [
      { line: specLine(), current: null, history: [] },
      {
        line: specLine({
          id: 102,
          sequence: 2,
          test: 8,
          test_code: "GORUNUS",
          test_name: "Görünüş",
          result_type: "TEXT",
          min_value: null,
          max_value: null,
          target_value: null,
          text_expected: "Berrak",
        }),
        current: null,
        history: [],
      },
    ],
    decisions: [],
    missing_tests: ["PH", "GORUNUS"],
    out_of_spec_tests: [],
    default_release_location: 5,
    allowed_transitions: ["IN_TEST", "AWAITING_APPROVAL", "DECIDED", "CANCELLED"],
    cancel_reason: "",
    coa_available: false,
    ...overrides,
  };
}

/** pH spesifikasyon dışı (9,1), görünüş uygun: karar verilebilir, serbest bırakılamaz. */
function outOfSpecDetail(): SampleDetail {
  const base = detail();
  return detail({
    status: "IN_TEST",
    status_display: "Testte",
    lines: [
      { ...base.lines[0], current: result(), history: [] },
      {
        ...base.lines[1],
        current: result({
          id: 502,
          spec_line: 102,
          test_code: "GORUNUS",
          numeric_value: null,
          text_value: "BERRAK",
          is_within_spec: true,
        }),
      },
    ],
    missing_tests: [],
    out_of_spec_tests: ["PH"],
    allowed_transitions: ["AWAITING_APPROVAL", "DECIDED", "CANCELLED"],
  });
}

function pendingDecision(): QualityDecision {
  return {
    id: 61,
    sample: 31,
    sample_number: "NM-2026-00001",
    lot_no: "H-261015-001",
    material_code: "SLES",
    material_name: "SLES %70",
    decision: "CONDITIONAL_RELEASE",
    decision_display: "Şartlı kabul",
    reason: "pH sınırda, müşteri onaylı",
    decided_by_name: "Laboratuvar",
    decided_at: "2026-10-15T12:00:00+03:00",
    release_location: 5,
    release_location_code: "HM-01",
    approval_status: "PENDING",
    approval_status_display: "Onay bekliyor",
    approved_by_name: null,
    approved_at: null,
    approval_note: "",
  };
}

const locations = [
  { id: 2, code: "KAR-01", name: "Karantina", location_type: "QUARANTINE", is_active: true },
  { id: 5, code: "HM-01", name: "Hammadde rafı", location_type: "STORAGE", is_active: true },
];

beforeEach(() => {
  vi.mocked(attachmentsApi.listAttachments).mockResolvedValue([]);
  vi.mocked(labelsApi.listPrinters).mockResolvedValue([]);
  vi.mocked(labelsApi.getLabelSettings).mockResolvedValue({
    company_name: "",
    gs1_company_prefix: "",
    sscc_extension_digit: 0,
    next_sscc_serial: 1,
    default_printer: null,
    default_printer_code: null,
    sscc_enabled: false,
    updated_at: "2026-10-15T09:00:00+03:00",
  });
  vi.resetAllMocks();
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  vi.mocked(workflowApi.fetchComments).mockResolvedValue([]);
  vi.mocked(workflowApi.fetchRecordHistory).mockResolvedValue([]);
  vi.mocked(mdApi.listRecords).mockImplementation(async (endpoint) =>
    endpoint === "locations" ? page(locations) : page([]),
  );
  vi.mocked(qualityApi.sampleQueue).mockResolvedValue(page([sample()]));
  vi.mocked(qualityApi.listSamples).mockResolvedValue(page([sample()]));
  vi.mocked(qualityApi.listDecisions).mockResolvedValue(page([]));
  vi.mocked(qualityApi.listSpecifications).mockResolvedValue(page([]));
  vi.mocked(qualityApi.getSample).mockResolvedValue(detail());
});

describe("kalite sekmeleri", () => {
  it("laboratuvar numune kuyruğuna düşer, satır numuneye götürür", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("laboratuvar"));
    const { router } = renderApp("/kalite");
    expect(await screen.findByRole("tab", { name: "Numune kuyruğu", selected: true }));
    const queue = await screen.findByTestId("sample-queue");
    expect(queue).toHaveTextContent("H-261015-001");
    expect(queue).toHaveTextContent("Giriş kontrolü");
    expect(screen.queryByRole("tab", { name: "Şartlı kabul onayı" })).toBeNull();
    await user.click(within(queue).getByText("NM-2026-00001"));
    await waitFor(() => expect(router.state.location.pathname).toBe("/kalite/numuneler/31"));
  });

  it("yönetim şartlı kabul onayına düşer ve onaylar", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    vi.mocked(qualityApi.listDecisions).mockResolvedValue(page([pendingDecision()]));
    vi.mocked(qualityApi.reviewDecision).mockResolvedValue({
      ...pendingDecision(),
      approval_status: "APPROVED",
    });
    renderApp("/kalite");
    expect(await screen.findByRole("tab", { name: "Şartlı kabul onayı", selected: true }));
    expect(screen.queryByRole("tab", { name: "Numune kuyruğu" })).toBeNull();
    const table = await screen.findByTestId("pending-approvals");
    await user.click(within(table).getByRole("button", { name: "Reddet" }));
    let dialog = await screen.findByRole("dialog");
    // Ret nedeni zorunlu.
    expect(within(dialog).getByRole("button", { name: "Reddet" })).toBeDisabled();
    await user.click(within(dialog).getByRole("button", { name: "Vazgeç" }));
    await user.click(within(table).getByRole("button", { name: "Onayla" }));
    dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Onayla" }));
    await waitFor(() => expect(qualityApi.reviewDecision).toHaveBeenCalledWith(61, true, ""));
  });

  it("depo kalite sayfasına giremez; numune kaydı detaya gider", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    renderApp("/kalite");
    expect(await screen.findByText(/yetkiniz yok/i));
    expect(recordPath({ model: "quality.sample", id: 31, repr: "" })).toBe("/kalite/numuneler/31");
  });
});

describe("numune", () => {
  it("sonuç girerken sınır dışı değeri kırmızı gösterir ve kaydeder", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("laboratuvar"));
    vi.mocked(qualityApi.recordResult).mockResolvedValue(detail());
    renderApp("/kalite/numuneler/31");

    expect(await screen.findByRole("heading", { name: "Numune NM-2026-00001" }));
    const results = screen.getByTestId("results");
    expect(results).toHaveTextContent("6,00 – 8,00");
    expect(results).toHaveTextContent("Berrak");
    expect(screen.getByText("Eksik zorunlu test: PH, GORUNUS")).toBeInTheDocument();

    const input = within(results).getByRole("textbox", { name: "pH" });
    await user.type(input, "9,1");
    expect(within(results).getByText("Spesifikasyon dışı")).toBeInTheDocument();
    const [save] = within(results).getAllByRole("button", { name: "Kaydet" });
    await user.click(save);
    await waitFor(() =>
      expect(qualityApi.recordResult).toHaveBeenCalledWith(
        31,
        expect.objectContaining({ spec_line: 101, numeric_value: "9.1", note: "" }),
      ),
    );
  });

  it("düzeltme nedeni zorunlu; eski sonuç geçmişte kalır", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("laboratuvar"));
    const data = outOfSpecDetail();
    data.lines[0].history = [result({ id: 400, numeric_value: "9.5000", superseded_by: 501 })];
    vi.mocked(qualityApi.getSample).mockResolvedValue(data);
    vi.mocked(qualityApi.recordResult).mockResolvedValue(data);
    renderApp("/kalite/numuneler/31");

    const value = await screen.findByTestId("result-PH");
    expect(value).toHaveTextContent("9,10");
    expect(screen.getByText("1 eski sonuç")).toBeInTheDocument();
    const results = screen.getByTestId("results");
    await user.click(within(results).getAllByRole("button", { name: "Düzelt" })[0]);
    await user.type(within(results).getByRole("textbox", { name: "pH" }), "7,2");
    const save = within(results).getByRole("button", { name: "Kaydet" });
    expect(save).toBeDisabled();
    await user.type(
      within(results).getByRole("textbox", { name: /Düzeltme nedeni/ }),
      "Tekrar ölçüm",
    );
    await user.click(save);
    await waitFor(() =>
      expect(qualityApi.recordResult).toHaveBeenCalledWith(
        31,
        expect.objectContaining({ numeric_value: "7.2", note: "Tekrar ölçüm" }),
      ),
    );
  });

  it("spec dışı sonuçla serbest bırakma kapalı; şartlı kabul gerekçeyle gönderilir", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("laboratuvar"));
    vi.mocked(qualityApi.getSample).mockResolvedValue(outOfSpecDetail());
    vi.mocked(qualityApi.decide).mockResolvedValue(outOfSpecDetail() as SampleDetail);
    renderApp("/kalite/numuneler/31");

    await user.click(await screen.findByRole("button", { name: "Karar ver" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("radio", { name: "Serbest bırak" })).toBeDisabled();
    // Yeniden işleme yalnızca bulk lot içindir.
    expect(within(dialog).queryByRole("radio", { name: "Yeniden işleme" })).toBeNull();
    expect(within(dialog).getByRole("radio", { name: "Şartlı kabul" })).toBeChecked();
    const submit = within(dialog).getByRole("button", { name: "Karar ver" });
    expect(submit).toBeDisabled();
    await user.type(within(dialog).getByRole("textbox", { name: /Gerekçe/ }), "Müşteri onaylı");
    await user.click(submit);
    await waitFor(() =>
      expect(qualityApi.decide).toHaveBeenCalledWith(31, {
        decision: "CONDITIONAL_RELEASE",
        reason: "Müşteri onaylı",
        release_location: 5,
      }),
    );
  });

  it("zorunlu test eksikken karar seçilemez ve gönderilemez", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("laboratuvar"));
    renderApp("/kalite/numuneler/31");
    await user.click(await screen.findByRole("button", { name: "Karar ver" }));
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText(
        "Zorunlu testlerin sonucu girilmeden karar verilemez. Eksik: PH, GORUNUS",
      ),
    ).toBeInTheDocument();
    expect(within(dialog).getByRole("radio", { name: "Serbest bırak" })).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Karar ver" })).toBeDisabled();
  });

  it("karar hatasını pencerede gösterir", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("laboratuvar"));
    vi.mocked(qualityApi.getSample).mockResolvedValue(detail({ missing_tests: [] }));
    vi.mocked(qualityApi.decide).mockRejectedValue(
      httpError(400, { code: "lot_already_decided", detail: "Lot serbest; karar verilemez." }),
    );
    renderApp("/kalite/numuneler/31");
    await user.click(await screen.findByRole("button", { name: "Karar ver" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Karar ver" }));
    expect(await within(dialog).findByText("Lot serbest; karar verilemez.")).toBeInTheDocument();
  });

  it("serbest bırakılan numunede analiz sertifikası bağlantısı vardır", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo", "laboratuvar"));
    vi.mocked(qualityApi.getSample).mockResolvedValue(
      detail({
        status: "DECIDED",
        status_display: "Karar verildi",
        lot_status: "RELEASED",
        missing_tests: [],
        allowed_transitions: [],
        coa_available: true,
      }),
    );
    renderApp("/kalite/numuneler/31");
    expect(await screen.findByRole("link", { name: "Analiz sertifikası (PDF)" })).toHaveAttribute(
      "href",
      "/api/v1/quality/samples/31/coa.pdf",
    );
    expect(screen.queryByRole("button", { name: "Karar ver" })).toBeNull();
  });
});
