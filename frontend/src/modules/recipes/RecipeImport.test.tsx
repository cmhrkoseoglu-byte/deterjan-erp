import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../api/auth";
import * as recipesApi from "../../api/recipes";
import { page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";

vi.mock("../../api/auth");
vi.mock("../../api/recipes", async (importOriginal) => ({
  ...(await importOriginal<typeof recipesApi>()),
  listRecipes: vi.fn(),
  uploadRecipeImport: vi.fn(),
}));

describe("reçete içe aktarma", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(authApi.fetchCsrf).mockResolvedValue();
    vi.mocked(recipesApi.listRecipes).mockResolvedValue(page([]));
  });

  it("planlama dosyayı önizler ve aktarır", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    const report = {
      kind: "recipes" as const,
      total: 2,
      valid: 2,
      invalid: 0,
      to_create: 2,
      to_update: 0,
      file_errors: [],
      rows: [
        { row: 2, code: "RC-BUL / HM-SU", action: "create" as const, errors: [] },
        { row: 3, code: "RC-BUL / HM-LAS", action: "create" as const, errors: [] },
      ],
    };
    vi.mocked(recipesApi.uploadRecipeImport)
      .mockResolvedValueOnce({ ...report, imported: false })
      .mockResolvedValueOnce({ ...report, imported: true });
    renderApp("/receteler");

    await userEvent.click(await screen.findByRole("button", { name: "Excel'den içe aktar" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/yeni bir taslak sürüm/)).toBeInTheDocument();
    const file = new File(["x"], "receteler.xlsx");
    await userEvent.upload(dialog.querySelector("input[type=file]") as HTMLInputElement, file);
    await userEvent.click(within(dialog).getByRole("button", { name: "Önizle" }));
    expect(await within(dialog).findByText("RC-BUL / HM-LAS")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "2 satırı aktar" }));
    await waitFor(() => expect(recipesApi.uploadRecipeImport).toHaveBeenLastCalledWith(file, true));
  });

  it("laboratuvar da içe aktarabilir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("laboratuvar"));
    renderApp("/receteler");
    expect(await screen.findByRole("button", { name: "Excel'den içe aktar" })).toBeInTheDocument();
  });
});
