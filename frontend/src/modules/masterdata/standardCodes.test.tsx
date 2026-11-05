import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../api/auth";
import * as codingApi from "../../api/coding";
import * as mdApi from "../../api/masterdata";
import type { Partner, Unit } from "../../api/masterdata";
import * as standardsApi from "../../api/standards";
import { page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";

vi.mock("../../api/auth");
vi.mock("../../api/coding");
vi.mock("../../api/standards");
vi.mock("../../api/masterdata", async (importOriginal) => ({
  ...(await importOriginal<typeof mdApi>()),
  listRecords: vi.fn(),
  saveRecord: vi.fn(),
}));

const kg = {
  id: 1,
  code: "KG",
  name: "Kilogram",
  kind: "MASS",
  kind_display: "Kütle",
  factor_to_kind_base: "1.000000",
  unece_code: "KGM",
  symbol: "kg",
  is_active: true,
} as unknown as Unit;

const supplier = {
  id: 3,
  code: "TED-000001",
  name: "Alman Kimya",
  tax_office: "",
  tax_number: "",
  address: "",
  phone: "",
  email: "",
  contact_person: "",
  country_code: "DE",
  former_codes: [],
  is_active: true,
} as unknown as Partner;

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(codingApi.suggestCode).mockResolvedValue({
    key: "masterdata.supplier",
    active: false,
    code: null,
    format: "TED-000000",
  });
  vi.mocked(standardsApi.getStandards).mockResolvedValue({
    countries: ["DE", "IQ", "TR"],
    languages: ["tr"],
    default_country: "TR",
    default_language: "tr",
  });
  vi.mocked(mdApi.listRecords).mockImplementation(async (endpoint) => {
    if (endpoint === "units") return page([kg]);
    if (endpoint === "suppliers") return page([supplier]);
    return page([]);
  });
});

describe("birimde standart kodlar", () => {
  it("UN/ECE kodu ve sembol listede görünür, formda girilir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("admin"));
    vi.mocked(mdApi.saveRecord).mockResolvedValue(kg);
    renderApp("/ana-veriler/birimler");

    const row = (await screen.findByText("KGM")).closest("tr")!;
    expect(within(row).getByText("kg")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Yeni" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/koli XCT, palet XPX/)).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText(/^Kod/), "BIDON");
    await userEvent.type(within(dialog).getByLabelText(/^Ad/), "Bidon");
    // "Tür" ve "Tür temel birimine katsayı": ilki tür seçimi.
    await userEvent.click(within(dialog).getAllByRole("textbox", { name: /^Tür/ })[0]);
    await userEvent.click(await screen.findByRole("option", { name: "Adet" }));
    await userEvent.type(within(dialog).getByLabelText(/^UN\/ECE kodu/), "XJY");
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));

    await waitFor(() =>
      expect(mdApi.saveRecord).toHaveBeenCalledWith(
        "units",
        null,
        expect.objectContaining({ code: "BIDON", kind: "COUNT", unece_code: "XJY" }),
      ),
    );
  });
});

describe("caride ülke kodu", () => {
  it("ülke listede görünür; yeni caride Türkiye gelir, listeden değiştirilir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("planlama"));
    vi.mocked(mdApi.saveRecord).mockResolvedValue(supplier);
    renderApp("/ana-veriler/tedarikciler");

    const row = (await screen.findByText("TED-000001")).closest("tr")!;
    expect(within(row).getByText("DE")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Yeni" }));
    const dialog = await screen.findByRole("dialog");
    const country = within(dialog).getByRole("textbox", { name: /^Ülke/ });
    await waitFor(() => expect(country).toHaveValue("Türkiye (TR)"));
    await userEvent.click(country);
    await userEvent.click(await screen.findByRole("option", { name: "Irak (IQ)" }));
    await userEvent.type(within(dialog).getByLabelText(/^Kod/), "TED-000002");
    await userEvent.type(within(dialog).getByLabelText(/^Ünvan/), "Bağdat Kimya");
    await userEvent.click(within(dialog).getByRole("button", { name: "Kaydet" }));

    await waitFor(() =>
      expect(mdApi.saveRecord).toHaveBeenCalledWith(
        "suppliers",
        null,
        expect.objectContaining({ name: "Bağdat Kimya", country_code: "IQ" }),
      ),
    );
  });
});
