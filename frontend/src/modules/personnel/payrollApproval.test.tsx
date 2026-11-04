// Bordro onayı (4. adım): onay penceresi (denetimler, "okudum", ödeme tarihi), onaylı ayın
// kilidi, ücret pusulası, yeniden açma, ödeme tarihi düzeltmesi, onay geçmişi ve yeniden açılan
// ayda kartı değişen kişiler.
import { notifications } from "@mantine/notifications";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../api/auth";
import * as payrollApi from "../../api/payroll";
import type { PayrollRow } from "../../api/payroll";
import * as workflowApi from "../../api/workflow";
import { httpError, page, userWith } from "../../test/fixtures";
import {
  approval,
  approvedState,
  AYSE,
  CAN,
  ECE,
  item,
  month,
  payrollState,
} from "../../test/payrollFixtures";
import { renderApp } from "../../test/render";

vi.mock("../../api/auth");
vi.mock("../../api/workflow");
vi.mock("../../api/payroll", async (importOriginal) => ({
  // Adresler, sorgu anahtarları ve hata ayrıştırma gerçek kalır.
  ...(await importOriginal<typeof payrollApi>()),
  getPayrollMonth: vi.fn(),
  listParameterSets: vi.fn(),
  listPayrollItems: vi.fn(),
  approvePayroll: vi.fn(),
  reopenPayroll: vi.fn(),
  setPaymentDate: vi.fn(),
  setFollowCard: vi.fn(),
}));

const AYSE_ITEMS: PayrollRow = { ...AYSE, items: [item()] };
const RUN = {
  id: 7,
  number: "BR-2026-00001",
  year: 2026,
  month: 10,
  status: "APPROVED" as const,
  status_display: "Onaylandı",
  current: approval(),
};

// Bildirimler testte çizilmez (Notifications yok): gösterilen metin yakalanır.
const shown = (message: string) =>
  expect(notifications.show).toHaveBeenCalledWith(expect.objectContaining({ message }));

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(notifications, "show").mockReturnValue("bildirim");
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  vi.mocked(payrollApi.listParameterSets).mockResolvedValue([]);
  vi.mocked(payrollApi.listPayrollItems).mockResolvedValue(page([]));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("bordro onayı", () => {
  it("onay penceresi okunması istenen uyarıyı ve ödeme tarihini ister", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({
        attendance_approved: true,
        attendance_number: "PU-2026-00010",
        rows: [AYSE, ECE],
        payroll: payrollState({
          gates: [
            {
              code: "exit_in_month",
              level: "acknowledge",
              employees: [{ id: 3, full_name: "Ece Ak" }],
            },
            {
              code: "external_items",
              level: "notice",
              employees: [{ id: 2, full_name: "Can Kaya" }],
            },
          ],
        }),
      }),
    );
    vi.mocked(payrollApi.approvePayroll).mockResolvedValue(RUN);
    renderApp("/personel/bordro?ay=2026-10");
    expect(await screen.findByText("Bordro taslak")).toBeInTheDocument();
    expect(screen.getByText("Bordro onaya hazır")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Bordroyu onayla" }));
    const dialog = await screen.findByRole("dialog", { name: "Ekim 2026 bordrosunu onayla" });
    expect(within(dialog).getByText(/2 kişi ERP'de, 1 kişi mali müşavirde/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Can Kaya/)).toBeInTheDocument();
    const confirm = within(dialog).getByRole("button", { name: "Onayla ve kilitle" });
    expect(confirm).toBeDisabled();
    const date = within(dialog).getByLabelText(/Ödeme tarihi/);
    await user.type(date, "2026-09-30");
    expect(within(dialog).getByText(/01\.10\.2026 ile 31\.01\.2027 arasında olmalı/)).toBeVisible();
    await user.clear(date);
    await user.type(date, "2026-11-25");
    expect(within(dialog).getByText(/ay sonundan 20 günden fazla sonra/)).toBeVisible();
    expect(confirm).toBeDisabled(); // "okudum" işaretlenmedi
    await user.click(within(dialog).getByRole("checkbox", { name: /Okudum: Ay içinde çıkış/ }));
    expect(confirm).toBeEnabled();
    await user.click(confirm);
    await waitFor(() =>
      expect(payrollApi.approvePayroll).toHaveBeenCalledWith(2026, 10, {
        payment_date: "2026-11-25",
        fingerprint: "f1",
        acknowledged: ["exit_in_month"],
      }),
    );
    await waitFor(() => shown("Ekim 2026 bordrosu onaylandı (BR-2026-00001)."));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: /bordrosunu onayla/ })).not.toBeInTheDocument(),
    );
  });

  it("engelleyen denetimler kişileriyle yazılır; onay düğmesi kapalı kalır", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({
        payroll: payrollState({
          gates: [
            { code: "attendance_open", level: "block", employees: [] },
            {
              code: "missing_wage",
              level: "block",
              employees: [1, 2, 3, 4, 5, 6, 7].map((id) => ({ id, full_name: `Kişi ${id}` })),
            },
          ],
        }),
      }),
    );
    renderApp("/personel/bordro?ay=2026-10");
    expect(await screen.findByText(/Onayı engelleyen 2 konu var/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Bordroyu onayla" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Puantaj onaylanmadı")).toBeInTheDocument();
    expect(
      within(dialog).getByText(/Kişi 1, Kişi 2, Kişi 3, Kişi 4, Kişi 5 ve 2 kişi daha/),
    ).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText(/Ödeme tarihi/), "2026-11-10");
    expect(within(dialog).getByRole("button", { name: "Onayla ve kilitle" })).toBeDisabled();
  });

  it("sunucunun reddi pencerede yazılır ve ay yenilenir", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(month());
    vi.mocked(payrollApi.approvePayroll).mockRejectedValue(
      httpError(400, {
        code: "payroll_not_ready",
        detail: "Ekim 2026 bordrosu onaylanamaz: ücret eksik: Ayşe Demir.",
        gates: [
          {
            code: "missing_wage",
            level: "block",
            employees: [{ id: 1, full_name: "Ayşe Demir" }],
          },
        ],
      }),
    );
    renderApp("/personel/bordro?ay=2026-10");
    await user.click(await screen.findByRole("button", { name: "Bordroyu onayla" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Ödeme tarihi/), "2026-11-10");
    await user.click(within(dialog).getByRole("button", { name: "Onayla ve kilitle" }));
    expect(
      await within(dialog).findByText(/bordrosu onaylanamaz: ücret eksik: Ayşe Demir/),
    ).toBeVisible();
    // Ay yeniden okunur: denetimler pencerede yeni haliyle görünür.
    await waitFor(() => expect(payrollApi.getPayrollMonth).toHaveBeenCalledTimes(2));
  });

  it("okunması istenen denetimin bütün kişileri yazılır; kişiler değişince işaret kalkar", async () => {
    const user = userEvent.setup();
    const people = [1, 2, 3, 4, 5, 6, 7].map((id) => ({ id, full_name: `Kişi ${id}` }));
    const exits = (employees: typeof people) =>
      month({
        payroll: payrollState({
          gates: [{ code: "exit_in_month", level: "acknowledge", employees }],
        }),
      });
    vi.mocked(payrollApi.getPayrollMonth)
      .mockResolvedValueOnce(exits(people.slice(0, 6)))
      .mockResolvedValue({
        ...exits(people),
        payroll: { ...exits(people).payroll, fingerprint: "f2" },
      });
    vi.mocked(payrollApi.approvePayroll).mockRejectedValue(
      httpError(400, { code: "payroll_changed", detail: "Ekim 2026 bordrosu ... değişti" }),
    );
    renderApp("/personel/bordro?ay=2026-10");
    await user.click(await screen.findByRole("button", { name: "Bordroyu onayla" }));
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText("Kişi 1, Kişi 2, Kişi 3, Kişi 4, Kişi 5, Kişi 6"),
    ).toBeInTheDocument();
    const box = within(dialog).getByRole("checkbox", { name: /Okudum: Ay içinde çıkış/ });
    expect(box).toHaveAccessibleDescription("Kişi 1, Kişi 2, Kişi 3, Kişi 4, Kişi 5, Kişi 6");
    await user.click(box);
    await user.type(within(dialog).getByLabelText(/Ödeme tarihi/), "2026-11-10");
    const confirm = within(dialog).getByRole("button", { name: "Onayla ve kilitle" });
    await user.click(confirm);
    await waitFor(() => expect(payrollApi.approvePayroll).toHaveBeenCalledTimes(1));
    expect(vi.mocked(payrollApi.approvePayroll).mock.calls[0][2].acknowledged).toEqual([
      "exit_in_month",
    ]);
    // Hesap yenilendi, denetime yedinci kişi eklendi: işaret kalkar, onay kapanır.
    expect(
      await within(dialog).findByText(/Kişi 1, Kişi 2, Kişi 3, Kişi 4, Kişi 5, Kişi 6, Kişi 7/),
    ).toBeInTheDocument();
    const refreshed = within(dialog).getByRole("checkbox", { name: /Okudum: Ay içinde çıkış/ });
    expect(refreshed).not.toBeChecked();
    expect(refreshed).toHaveAccessibleDescription(/Kişi 7$/);
    expect(confirm).toBeDisabled();
  });

  it("yeniden açılan ayda kartı değişen kişiler ve saklanacak işaretleri onay penceresinde yazar", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({
        payroll: payrollState({
          card_changes: [
            {
              employee: 1,
              full_name: "Ayşe Demir",
              approved_external: false,
              approved_bes: false,
              card_external: true,
              card_bes: false,
              following: false,
              stored_external: false,
              stored_bes: false,
              figure_keeps_external: false,
            },
            {
              employee: 2,
              full_name: "Deniz Ak",
              approved_external: false,
              approved_bes: true,
              card_external: true,
              card_bes: false,
              following: true,
              stored_external: true,
              stored_bes: false,
              figure_keeps_external: false,
            },
            {
              employee: 3,
              full_name: "Ece Su",
              approved_external: true,
              approved_bes: false,
              card_external: false,
              card_bes: false,
              following: true,
              stored_external: true,
              stored_bes: false,
              figure_keeps_external: true,
            },
          ],
        }),
      }),
    );
    renderApp("/personel/bordro?ay=2026-10");
    await user.click(await screen.findByRole("button", { name: "Bordroyu onayla" }));
    const dialog = await screen.findByRole("dialog", { name: "Ekim 2026 bordrosunu onayla" });
    const line = (text: string) => within(dialog).getByText(text).parentElement;
    // Kartı izlenmeyen kişi onaydaki, kartı izleyen kişi kartın işaretleriyle saklanır.
    expect(
      line("Ayşe Demir: onayda ERP'de, BES yok; kartta mali müşavirde, BES yok"),
    ).toHaveTextContent("Onayda saklanacak: ERP'de, BES yok");
    const followed = line("Deniz Ak: onayda ERP'de, BES'e dahil; kartta mali müşavirde, BES yok");
    expect(followed).toHaveTextContent("kartı izliyor");
    const badge = within(dialog).getAllByText("kartı izliyor")[0];
    expect(badge.closest("p")?.querySelector("div")).toBeNull();
    expect(followed).toHaveTextContent("Onayda saklanacak: mali müşavirde, BES yok");
    expect(followed).not.toHaveTextContent("rakam kaldırılana kadar");
    // Kartı izliyor (kart ERP) ama girilmiş mali müşavir rakamı onu mali müşavirde tutar.
    const figure = line("Ece Su: onayda mali müşavirde, BES yok; kartta ERP'de, BES yok");
    expect(figure).toHaveTextContent("Onayda saklanacak: mali müşavirde, BES yok");
    expect(figure).toHaveTextContent(
      "O aya mali müşavir rakamı girilmiş: rakam kaldırılana kadar mali müşavirde kalır.",
    );
    expect(within(dialog).getByText(/onaydan önce Ay hazırlığında "Kartı izle"/)).toBeVisible();
    expect(within(dialog).queryByRole("button", { name: /Kartı izle/ })).not.toBeInTheDocument();
  });

  it("birim süzgeçli ayda onay denetimi yok: onay düğmesi kapalı", async () => {
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({ payroll: payrollState({ gates: null, fingerprint: null }) }),
    );
    renderApp("/personel/bordro?ay=2026-10");
    expect(await screen.findByRole("button", { name: "Bordroyu onayla" })).toBeDisabled();
  });

  it("önceki ay onaylanmadıysa ay hazırlığı o aya götürür", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({
        month: 11,
        period_label: "Kasım 2026",
        payroll: payrollState({ previous_open: true }),
      }),
    );
    renderApp("/personel/bordro?ay=2026-11");
    expect(
      await screen.findByText("Ekim 2026 bordrosu onaylanmadı: aylar sırayla onaylanır"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "O aya git" }));
    await waitFor(() => expect(payrollApi.getPayrollMonth).toHaveBeenLastCalledWith(2026, 10));
  });
});

describe("onaylı bordro", () => {
  beforeEach(() => {
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({
        attendance_approved: true,
        attendance_number: "PU-2026-00010",
        rows: [AYSE_ITEMS, CAN],
        payroll: approvedState(),
      }),
    );
  });

  it("ay kilitlidir: durum, pusula bağlantıları, kalemler ve devirler yalnızca okunur", async () => {
    const user = userEvent.setup();
    renderApp("/personel/bordro?ay=2026-10&gorunum=kalemler");
    expect(
      await screen.findByText("Bordro onaylı · BR-2026-00001 · ödeme 10.11.2026"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Bordro onaylı \(BR-2026-00001\): ay kilitli/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Bordroyu onayla" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Devirler" })).toBeDisabled();
    expect(screen.getByRole("link", { name: "Ücret pusulaları (PDF)" })).toHaveAttribute(
      "href",
      "/api/v1/personnel/payroll/2026/10/payslips.pdf",
    );
    expect(screen.getByRole("button", { name: "Kalem ekle" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Toplu ekle" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Geçen aydan kopyala" })).toBeDisabled();
    const items = screen.getByTestId("payroll-items");
    expect(within(items).queryByRole("button")).not.toBeInTheDocument();
    // Dökümde tek kişinin pusulası; kalem eklenemez.
    await user.click(screen.getByRole("radio", { name: "Bordro" }));
    await user.click(await screen.findByRole("button", { name: "Döküm: Ayşe Demir" }));
    const drawer = await screen.findByRole("dialog", { name: "Ayşe Demir · Ekim 2026" });
    expect(within(drawer).getByRole("link", { name: "Ücret pusulası (PDF)" })).toHaveAttribute(
      "href",
      "/api/v1/personnel/payroll/2026/10/payslips.pdf?employee=1",
    );
    await user.click(within(drawer).getByRole("tab", { name: /Ek ödeme ve kesinti/ }));
    expect(within(drawer).getByRole("button", { name: "Kalem ekle" })).toBeDisabled();
    expect(within(drawer).queryByRole("button", { name: /Düzelt/ })).not.toBeInTheDocument();
  });

  it("gerekçeyle yeniden açılır", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.reopenPayroll).mockResolvedValue({
      ...RUN,
      status: "OPEN",
      current: null,
    });
    renderApp("/personel/bordro?ay=2026-10");
    await user.click(await screen.findByRole("button", { name: "Yeniden aç" }));
    const dialog = await screen.findByRole("dialog", { name: "Ekim 2026 bordrosunu yeniden aç" });
    const confirm = within(dialog).getByRole("button", { name: "Yeniden aç" });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/Yeniden açma gerekçesi/), "Prim eksik");
    await user.click(confirm);
    await waitFor(() =>
      expect(payrollApi.reopenPayroll).toHaveBeenCalledWith(2026, 10, "Prim eksik"),
    );
    await waitFor(() => shown("Ekim 2026 bordrosu yeniden açıldı."));
  });

  it("yeniden açma reddedilirse ay yenilenir", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.reopenPayroll).mockRejectedValue(
      httpError(400, {
        code: "later_payroll_approved",
        detail: "Kasım 2026 bordrosu onaylı (BR-2026-00002); aylar sondan başa açılır.",
      }),
    );
    renderApp("/personel/bordro?ay=2026-10");
    await user.click(await screen.findByRole("button", { name: "Yeniden aç" }));
    const dialog = await screen.findByRole("dialog", { name: "Ekim 2026 bordrosunu yeniden aç" });
    await user.type(within(dialog).getByLabelText(/Yeniden açma gerekçesi/), "Prim eksik");
    await user.click(within(dialog).getByRole("button", { name: "Yeniden aç" }));
    expect(await within(dialog).findByText(/aylar sondan başa açılır/)).toBeVisible();
    await waitFor(() => expect(payrollApi.getPayrollMonth).toHaveBeenCalledTimes(2));
  });

  it("yalnızca en son onaylı ay yeniden açılır", async () => {
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({ payroll: approvedState({ can_reopen: false }) }),
    );
    renderApp("/personel/bordro?ay=2026-10");
    expect(await screen.findByRole("button", { name: "Yeniden aç" })).toBeDisabled();
  });

  it("ödeme tarihi gerekçeyle düzeltilir", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.setPaymentDate).mockResolvedValue(RUN);
    renderApp("/personel/bordro?ay=2026-10");
    await user.click(await screen.findByRole("button", { name: "Ödeme tarihini düzelt" }));
    const dialog = await screen.findByRole("dialog", { name: "Ekim 2026 · ödeme tarihi" });
    const save = within(dialog).getByRole("button", { name: "Kaydet" });
    expect(save).toBeDisabled(); // tarih aynı, gerekçe yok
    const date = within(dialog).getByLabelText(/Ödeme tarihi/);
    await user.clear(date);
    await user.type(date, "2026-11-25");
    expect(within(dialog).getByText(/ay sonundan 20 günden fazla sonra/)).toBeVisible();
    await user.clear(date);
    await user.type(date, "2026-11-12");
    expect(within(dialog).queryByText(/ay sonundan 20 günden fazla sonra/)).not.toBeInTheDocument();
    await user.type(within(dialog).getByLabelText(/Gerekçe/), "Banka tatili");
    await user.click(save);
    await waitFor(() =>
      expect(payrollApi.setPaymentDate).toHaveBeenCalledWith(2026, 10, {
        payment_date: "2026-11-12",
        reason: "Banka tatili",
      }),
    );
  });

  it("ödeme tarihi düzeltmesi reddedilirse ay yenilenir", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.setPaymentDate).mockRejectedValue(
      httpError(400, { code: "payroll_not_approved", detail: "Ekim 2026 bordrosu onaylı değil." }),
    );
    renderApp("/personel/bordro?ay=2026-10");
    await user.click(await screen.findByRole("button", { name: "Ödeme tarihini düzelt" }));
    const dialog = await screen.findByRole("dialog", { name: "Ekim 2026 · ödeme tarihi" });
    const date = within(dialog).getByLabelText(/Ödeme tarihi/);
    await user.clear(date);
    await user.type(date, "2026-11-12");
    await user.type(within(dialog).getByLabelText(/Gerekçe/), "Banka tatili");
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    expect(await within(dialog).findByText(/bordrosu onaylı değil/)).toBeVisible();
    await waitFor(() => expect(payrollApi.getPayrollMonth).toHaveBeenCalledTimes(2));
  });

  it("onay geçmişi eski onayın çıktılarına bağlantı verir", async () => {
    const user = userEvent.setup();
    const first = approval({
      reopened_at: "2026-11-04T09:00:00+03:00",
      reopened_by_name: "Yönetim",
      reopen_reason: "Prim eksik",
    });
    const second = approval({ sequence: 2, payment_date: "2026-11-12" });
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({ payroll: approvedState({ approval: second, history: [first, second] }) }),
    );
    renderApp("/personel/bordro?ay=2026-10");
    await user.click(await screen.findByRole("button", { name: "Onay geçmişi" }));
    const dialog = await screen.findByRole("dialog", { name: "Ekim 2026 · onay geçmişi" });
    expect(within(dialog).getByText(/Yeniden açıldı: Yönetim · .* · Prim eksik/)).toBeVisible();
    expect(within(dialog).getByText("geçersiz")).toBeVisible();
    expect(within(dialog).getByText("geçerli")).toBeVisible();
    expect(
      within(dialog).getByRole("link", { name: "Bordro listesi (PDF): 2. onay" }),
    ).toHaveAttribute("href", "/api/v1/personnel/payroll/2026/10/register.pdf?approval=2");
    expect(
      within(dialog).getByRole("link", { name: "Bordro listesi (PDF): 1. onay (geçersiz)" }),
    ).toHaveAttribute("href", "/api/v1/personnel/payroll/2026/10/register.pdf?approval=1");
    expect(within(dialog).getByRole("link", { name: "Excel: 1. onay (geçersiz)" })).toHaveAttribute(
      "href",
      "/api/v1/personnel/payroll/2026/10/xlsx/?approval=1",
    );
  });
});

describe("yeniden açılan ay", () => {
  it("kartı değişen kişi listelenir ve kartın işaretlerine geçirilir", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({
        payroll: payrollState({
          run: 7,
          number: "BR-2026-00001",
          history: [approval({ reopened_at: "2026-11-04T09:00:00+03:00", reopen_reason: "x" })],
          card_changes: [
            {
              employee: 1,
              full_name: "Ayşe Demir",
              approved_external: false,
              approved_bes: false,
              card_external: true,
              card_bes: false,
              following: false,
              stored_external: false,
              stored_bes: false,
              figure_keeps_external: false,
            },
            {
              employee: 2,
              full_name: "Ece Su",
              approved_external: true,
              approved_bes: false,
              card_external: false,
              card_bes: false,
              following: true,
              stored_external: true,
              stored_bes: false,
              figure_keeps_external: true,
            },
          ],
        }),
      }),
    );
    vi.mocked(payrollApi.setFollowCard).mockResolvedValue({
      ...RUN,
      status: "OPEN",
      current: null,
    });
    renderApp("/personel/bordro?ay=2026-10");
    expect(
      await screen.findByText("Ayşe Demir: onayda ERP'de, BES yok; kartta mali müşavirde, BES yok"),
    ).toBeInTheDocument();
    // Kartı izleyen kişiyi girilmiş mali müşavir rakamı mali müşavirde tutar: satırında yazar.
    expect(
      screen.getByText("Ece Su: onayda mali müşavirde, BES yok; kartta ERP'de, BES yok")
        .parentElement,
    ).toHaveTextContent("rakam kaldırılana kadar mali müşavirde kalır");
    await user.click(screen.getByRole("button", { name: "Kartı izle: Ayşe Demir" }));
    await waitFor(() =>
      expect(payrollApi.setFollowCard).toHaveBeenCalledWith(2026, 10, {
        employee: 1,
        follow: true,
      }),
    );
    await waitFor(() => shown("Ayşe Demir kartın bugünkü işaretleriyle hesaplanacak."));
  });

  it("kartı izleme reddedilirse ay yenilenir; satırda düğme küçülmez", async () => {
    const user = userEvent.setup();
    vi.mocked(payrollApi.getPayrollMonth).mockResolvedValue(
      month({
        payroll: payrollState({
          run: 7,
          number: "BR-2026-00001",
          history: [approval({ reopened_at: "2026-11-04T09:00:00+03:00", reopen_reason: "x" })],
          card_changes: [
            {
              employee: 1,
              full_name: "Ayşe Demir",
              approved_external: false,
              approved_bes: false,
              card_external: true,
              card_bes: false,
              following: false,
              stored_external: false,
              stored_bes: false,
              figure_keeps_external: false,
            },
          ],
        }),
      }),
    );
    vi.mocked(payrollApi.setFollowCard).mockRejectedValue(
      httpError(400, {
        code: "payroll_approved",
        detail: "Ekim 2026 bordrosu onaylı (BR-2026-00001).",
      }),
    );
    renderApp("/personel/bordro?ay=2026-10");
    const button = await screen.findByRole("button", { name: "Kartı izle: Ayşe Demir" });
    // Dar ekranda metin sarılır, düğme küçülmez (etiketi kırpılmaz).
    expect(button.parentElement).toHaveStyle({ flexShrink: "0", whiteSpace: "nowrap" });
    const text = screen.getByText(
      "Ayşe Demir: onayda ERP'de, BES yok; kartta mali müşavirde, BES yok",
    ).parentElement as HTMLElement;
    expect(getComputedStyle(text).minWidth).toMatch(/^0(px)?$/);
    await user.click(button);
    expect(await screen.findByText(/bordrosu onaylı \(BR-2026-00001\)/)).toBeVisible();
    await waitFor(() => expect(payrollApi.getPayrollMonth).toHaveBeenCalledTimes(2));
  });
});
