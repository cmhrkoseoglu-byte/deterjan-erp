import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../api/auth";
import * as personnelApi from "../../api/personnel";
import type { Employee } from "../../api/personnel";
import * as workflowApi from "../../api/workflow";
import type { AuditEntry } from "../../api/workflow";
import { page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";

vi.mock("../../api/auth");
vi.mock("../../api/personnel");
vi.mock("../../api/workflow");

function employee(extra: Partial<Employee> = {}): Employee {
  return {
    id: 5,
    employee_no: "S-0012",
    full_name: "Ayşe Demir",
    department: "Dolum",
    title: "Dolum operatörü",
    hire_date: "2024-03-01",
    termination_date: null,
    phone: "0500 000 00 12",
    emergency_contact_name: "Ali Demir",
    emergency_contact_phone: "0500 000 01 12",
    user: null,
    user_info: null,
    is_active: true,
    created_at: "2026-10-25T10:00:00+03:00",
    updated_at: "2026-10-25T10:00:00+03:00",
    ...extra,
  };
}

const LINKED = { id: 9, username: "dolum1", full_name: "Ayşe Demir", is_active: true };

beforeEach(() => {
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  vi.mocked(personnelApi.listEmployees).mockResolvedValue(page([employee()]));
  vi.mocked(personnelApi.listDepartments).mockResolvedValue(["Depo", "Dolum"]);
  vi.mocked(personnelApi.listLinkableUsers).mockResolvedValue([LINKED]);
  vi.mocked(personnelApi.fetchEmployeeHistory).mockResolvedValue([]);
});

describe("yetki", () => {
  it("menüde yalnız yönetim ve admin görür", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    renderApp("/gorevlerim");
    expect(await screen.findByRole("link", { name: "Personel" })).toHaveAttribute(
      "href",
      "/personel",
    );
  });

  it("diğer roller sayfayı açamaz", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    renderApp("/personel");
    expect(await screen.findByText("Yetkiniz yok")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Personel" })).not.toBeInTheDocument();
    expect(personnelApi.listEmployees).not.toHaveBeenCalled();
  });
});

describe("personel listesi", () => {
  it("çalışanları listeler; arama ve durum süzgeci isteğe gider", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    const { router } = renderApp("/personel");
    const table = await screen.findByTestId("employees");
    expect(within(table).getByText("Ayşe Demir")).toBeInTheDocument();
    expect(within(table).getByText("S-0012")).toBeInTheDocument();
    expect(within(table).getByText("01.03.2024")).toBeInTheDocument();
    expect(personnelApi.listEmployees).toHaveBeenCalledWith(
      expect.objectContaining({ is_active: true, search: "", page: 1 }),
    );

    await user.type(screen.getByLabelText("Ad, sicil no, birim ya da görev ara"), "ayşe");
    await waitFor(() =>
      expect(personnelApi.listEmployees).toHaveBeenLastCalledWith(
        expect.objectContaining({ search: "ayşe" }),
      ),
    );
    await user.click(screen.getByText("Ayrılanlar"));
    await waitFor(() =>
      expect(personnelApi.listEmployees).toHaveBeenLastCalledWith(
        expect.objectContaining({ is_active: false }),
      ),
    );
    await user.click(within(table).getByText("Ayşe Demir"));
    await waitFor(() => expect(router.state.location.pathname).toBe("/personel/5"));
  });

  it("yeni kart açar ve karta gider", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    vi.mocked(personnelApi.createEmployee).mockResolvedValue(employee({ id: 7 }));
    vi.mocked(personnelApi.getEmployee).mockResolvedValue(employee({ id: 7 }));
    const { router } = renderApp("/personel");
    await user.click(await screen.findByRole("button", { name: "Yeni personel" }));
    const dialog = await screen.findByRole("dialog", { name: "Yeni personel kartı" });
    await user.click(within(dialog).getByRole("button", { name: "Kartı aç" }));
    expect(within(dialog).getAllByText("Bu alan zorunlu.")).toHaveLength(2);
    expect(personnelApi.createEmployee).not.toHaveBeenCalled();

    await user.type(within(dialog).getByLabelText(/Ad soyad/), "  Ayşe Demir ");
    await user.type(within(dialog).getByLabelText(/^Birim/), "Dolum");
    await user.type(within(dialog).getByLabelText("Sicil no"), "S-0012");
    await user.click(within(dialog).getByRole("button", { name: "Kartı aç" }));
    await waitFor(() =>
      expect(personnelApi.createEmployee).toHaveBeenCalledWith({
        full_name: "Ayşe Demir",
        employee_no: "S-0012",
        department: "Dolum",
        title: "",
        hire_date: null,
        phone: "",
        emergency_contact_name: "",
        emergency_contact_phone: "",
        user: null,
      }),
    );
    await waitFor(() => expect(router.state.location.pathname).toBe("/personel/7"));
    expect(await screen.findByRole("heading", { name: "Ayşe Demir" })).toBeInTheDocument();
  });
});

describe("personel kartı", () => {
  it("bilgileri ve Türkçe alan adlarıyla geçmişi gösterir", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    vi.mocked(personnelApi.getEmployee).mockResolvedValue(employee({ user_info: LINKED, user: 9 }));
    const entry: AuditEntry = {
      id: 1,
      timestamp: "2026-10-25T11:00:00+03:00",
      actor: 1,
      actor_name: "Demo Yönetim",
      action: "update",
      action_label: "Güncelleme",
      changes: { hire_date: ["2024-02-01", "2024-03-01"], user: [null, 9] },
      note: "",
    };
    vi.mocked(personnelApi.fetchEmployeeHistory).mockResolvedValue([entry]);
    renderApp("/personel/5");
    expect(await screen.findByRole("heading", { name: "Ayşe Demir" })).toBeInTheDocument();
    expect(screen.getByText("Ali Demir")).toBeInTheDocument();
    expect(screen.getByText("dolum1")).toBeInTheDocument();
    expect(
      await screen.findByText("İşe giriş tarihi: 01.02.2024 → 01.03.2024"),
    ).toBeInTheDocument();
    expect(screen.getByText("Sistem kullanıcısı: — → dolum1")).toBeInTheDocument();
  });

  it("işten ayrılışı kaydeder ve açık hesabı hatırlatır", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    vi.mocked(personnelApi.getEmployee).mockResolvedValue(employee({ user_info: LINKED, user: 9 }));
    vi.mocked(personnelApi.terminateEmployee).mockResolvedValue(
      employee({ is_active: false, termination_date: "2026-09-30" }),
    );
    renderApp("/personel/5");
    await user.click(await screen.findByRole("button", { name: "İşten ayrıldı" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/sistem hesabı \(dolum1\) hâlâ açık/)).toBeInTheDocument();
    const date = within(dialog).getByLabelText(/İşten çıkış tarihi/);
    await user.clear(date);
    await user.type(date, "2026-09-30");
    const loads = vi.mocked(personnelApi.getEmployee).mock.calls.length;
    await user.click(within(dialog).getByRole("button", { name: "İşten ayrıldı" }));
    await waitFor(() =>
      expect(personnelApi.terminateEmployee).toHaveBeenCalledWith(5, "2026-09-30", ""),
    );
    // Kayıttan sonra pencere kapanır ve kart yenilenir.
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() =>
      expect(vi.mocked(personnelApi.getEmployee).mock.calls.length).toBeGreaterThan(loads),
    );
  });

  it("ayrılan personeli onayla yeniden çalışır yapar", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("admin"));
    vi.mocked(personnelApi.getEmployee).mockResolvedValue(
      employee({ is_active: false, termination_date: "2026-09-30" }),
    );
    vi.mocked(personnelApi.reinstateEmployee).mockResolvedValue(employee());
    renderApp("/personel/5");
    expect(await screen.findByText("Ayrıldı · 30.09.2026")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Yeniden işe başladı" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Yeniden işe başladı" }));
    await waitFor(() => expect(personnelApi.reinstateEmployee).toHaveBeenCalledWith(5));
  });
});
