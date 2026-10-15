import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../api/auth";
import * as mdApi from "../../api/masterdata";
import * as recipesApi from "../../api/recipes";
import type { RecipeVersionDetail } from "../../api/recipes";
import { page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";

vi.mock("../../api/auth");
vi.mock("../../api/recipes");
vi.mock("../../api/masterdata", async (importOriginal) => ({
  ...(await importOriginal<typeof mdApi>()),
  listRecords: vi.fn(),
}));

function version(overrides: Partial<RecipeVersionDetail> = {}): RecipeVersionDetail {
  return {
    id: 11,
    recipe: 3,
    recipe_code: "R-BUL",
    recipe_name: "Bulaşık deterjanı",
    product: 9,
    version_no: 2,
    status: "DRAFT",
    status_display: "Taslak",
    batch_size: "1000.0000",
    batch_unit: 1,
    batch_unit_code: "KG",
    change_note: "Parfüm artırıldı",
    copied_from: 10,
    copied_from_no: 1,
    approved_by: null,
    approved_by_name: null,
    approved_at: null,
    obsoleted_at: null,
    created_at: "2026-10-15T10:00:00+03:00",
    created_by_name: "Planlama",
    updated_at: "2026-10-15T10:00:00+03:00",
    lines: [
      {
        id: 100,
        version: 11,
        sequence: 1,
        material: 50,
        material_code: "SU",
        material_name: "Şebeke suyu",
        quantity: "600.0000",
        unit: 1,
        unit_code: "KG",
        tolerance_pct: "2.00",
        instruction: "",
        is_water: true,
      },
      {
        id: 101,
        version: 11,
        sequence: 2,
        material: 51,
        material_code: "PARFUM",
        material_name: "Parfüm",
        quantity: "3.0000",
        unit: 1,
        unit_code: "KG",
        tolerance_pct: "1.00",
        instruction: "Yavaşça ekle",
        is_water: false,
      },
    ],
    steps: [],
    can_edit: true,
    can_approve: true,
    ...overrides,
  };
}

const URL = "/receteler/3/surumler/11";

describe("reçete sürümü ekranı", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(authApi.fetchCsrf).mockResolvedValue();
    vi.mocked(mdApi.listRecords).mockResolvedValue(page([]));
    vi.mocked(recipesApi.listVersions).mockResolvedValue([]);
  });

  it("taslakta satır düzenleme ve onay düğmeleri görünür; su işaretlenir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("laboratuvar"));
    vi.mocked(recipesApi.getVersion).mockResolvedValue(version());
    renderApp(URL);

    expect(await screen.findByText("Sürüm 2")).toBeInTheDocument();
    expect(screen.getByText("Taslak")).toBeInTheDocument();
    expect(screen.getByText("SU - Şebeke suyu")).toBeInTheDocument();
    // su satırı işaretlenir (rozet), yine de sıradan malzeme satırıdır (Karar D-1)
    expect(screen.getAllByText("Şebeke suyu")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Satır ekle" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Satırı kaldır" })).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Onayla" })).toBeInTheDocument();
  });

  it("onaylı sürüm kilitlidir; yalnızca kopyalanabilir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    vi.mocked(recipesApi.getVersion).mockResolvedValue(
      version({
        status: "APPROVED",
        status_display: "Onaylı",
        can_edit: false,
        can_approve: false,
      }),
    );
    renderApp(URL);

    expect(await screen.findByText(/değiştirilemez/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Satır ekle" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Onayla" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Kopyala (yeni taslak)" })).toBeInTheDocument();
  });

  it("onaylarken notu gönderir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    vi.mocked(recipesApi.getVersion).mockResolvedValue(version());
    vi.mocked(recipesApi.approveVersion).mockResolvedValue(version({ status: "APPROVED" }));
    renderApp(URL);

    await userEvent.click(await screen.findByRole("button", { name: "Onayla" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Not"), "Lab onayı");
    await userEvent.click(within(dialog).getByRole("button", { name: "Onayla" }));

    await waitFor(() => expect(recipesApi.approveVersion).toHaveBeenCalledWith(11, "Lab onayı"));
  });

  it("satırı onayla kaldırır", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    vi.mocked(recipesApi.getVersion).mockResolvedValue(version());
    vi.mocked(recipesApi.removeLine).mockResolvedValue();
    renderApp(URL);

    const [first] = await screen.findAllByRole("button", { name: "Satırı kaldır" });
    await userEvent.click(first);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("SU satırı taslaktan kaldırılsın mı?")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaldır" }));

    await waitFor(() => expect(recipesApi.removeLine).toHaveBeenCalledWith(100));
  });

  it("başka sürümle karşılaştırır", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    const v1 = version({
      id: 10,
      version_no: 1,
      status: "APPROVED",
      lines: [{ ...version().lines[1], id: 90, quantity: "2.0000" }],
    });
    vi.mocked(recipesApi.getVersion).mockImplementation(async (id) => (id === 10 ? v1 : version()));
    vi.mocked(recipesApi.listVersions).mockResolvedValue([version(), v1]);
    renderApp(URL);

    await userEvent.click(await screen.findByRole("textbox", { name: "Karşılaştırılacak sürüm" }));
    await userEvent.click(await screen.findByRole("option", { name: "v1 (Onaylı)" }));

    expect(await screen.findByText("Değişti")).toBeInTheDocument();
    expect(screen.getByText("Eklendi")).toBeInTheDocument();
  });

  it("üretim rolü reçete ekranına giremez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("uretim"));
    renderApp(URL);

    expect(await screen.findByText("Yetkiniz yok")).toBeInTheDocument();
  });
});
