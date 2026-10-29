import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as attendanceApi from "../../api/attendance";
import type {
  AttendanceCell,
  AttendanceColumn,
  AttendanceGrid,
  PublicHoliday,
} from "../../api/attendance";
import * as authApi from "../../api/auth";
import * as personnelApi from "../../api/personnel";
import * as workflowApi from "../../api/workflow";
import { formatDate } from "../../i18n/format";
import { page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";

vi.mock("../../api/auth");
vi.mock("../../api/personnel");
vi.mock("../../api/workflow");
vi.mock("../../api/attendance", async (importOriginal) => {
  // Sabitler (OVERTIME_STATUSES, attendanceKeys, attendanceExportUrl) gerçek kalır.
  const actual = await importOriginal<typeof import("../../api/attendance")>();
  return {
    ...actual,
    getAttendanceGrid: vi.fn(),
    setAttendanceDay: vi.fn(),
    setAttendanceRange: vi.fn(),
    approveAttendanceMonth: vi.fn(),
    reopenAttendanceMonth: vi.fn(),
    listHolidays: vi.fn(),
    saveHoliday: vi.fn(),
    removeHoliday: vi.fn(),
    addFixedHolidays: vi.fn(),
    getAttendanceSettings: vi.fn(),
    saveAttendanceSettings: vi.fn(),
  };
});

const EMPLOYEE = {
  id: 5,
  employee_no: "S-0012",
  full_name: "Ayşe Demir",
  department: "Dolum",
  is_active: true,
};

function columns(year: number, month: number): AttendanceColumn[] {
  const length = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return Array.from({ length }, (_, index) => {
    const day = index + 1;
    const weekday = (new Date(Date.UTC(year, month - 1, day)).getUTCDay() + 6) % 7;
    const date = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    return { date, weekday, rest: weekday === 6, holiday_name: "", half_day: false };
  });
}

function grid(extra: Partial<AttendanceGrid> = {}): AttendanceGrid {
  const days = columns(2026, 9);
  const cells: AttendanceCell[] = days.map((day) => ({
    date: day.date,
    status: day.rest ? "WEEKLY_REST" : "WORKED",
    code: day.rest ? "HT" : "Ç",
    overtime_hours: "0.00",
    note: "",
    explicit: false,
    editable: true,
  }));
  const sick = cells.findIndex((cell) => cell.status === "WORKED");
  cells[sick] = { ...cells[sick], status: "SICK_LEAVE", code: "R", explicit: true };
  return {
    year: 2026,
    month: 9,
    period_label: "Eylül 2026",
    status: "OPEN",
    finished: true,
    month_record: null,
    days,
    rows: [
      {
        employee: EMPLOYEE,
        cells,
        totals: {
          days: {
            WORKED: 21,
            WEEKLY_REST: 4,
            PUBLIC_HOLIDAY: 0,
            ANNUAL_LEAVE: 0,
            PAID_LEAVE: 0,
            UNPAID_LEAVE: 0,
            SICK_LEAVE: 1,
            ABSENT: 0,
          },
          missing_days: 1,
          overtime: { WORKED: "2.50", WEEKLY_REST: "0.00", PUBLIC_HOLIDAY: "0.00" },
          overtime_total: "2.50",
        },
      },
    ],
    ...extra,
  };
}

const RECORD = {
  id: 1,
  number: "PU-2026-00001",
  year: 2026,
  month: 9,
  status: "APPROVED" as const,
  status_display: "Onaylandı",
  approved_at: "2026-10-02T09:00:00+03:00",
  approved_by_name: "Demo Yönetim",
};

function firstWorkday(data: AttendanceGrid): AttendanceCell {
  return data.rows[0].cells.find((cell) => cell.status === "WORKED")!;
}

beforeEach(() => {
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  vi.mocked(personnelApi.listDepartments).mockResolvedValue(["Depo", "Dolum"]);
  vi.mocked(personnelApi.listEmployees).mockResolvedValue(page([]));
  vi.mocked(attendanceApi.getAttendanceGrid).mockReset().mockResolvedValue(grid());
  vi.mocked(attendanceApi.setAttendanceDay).mockReset().mockResolvedValue();
  vi.mocked(attendanceApi.setAttendanceRange).mockReset().mockResolvedValue(10);
  vi.mocked(attendanceApi.approveAttendanceMonth).mockReset().mockResolvedValue(RECORD);
  vi.mocked(attendanceApi.reopenAttendanceMonth).mockReset();
});

describe("puantaj tablosu", () => {
  it("kodları ve toplamları gösterir; hücreden gün kaydedilir", async () => {
    const user = userEvent.setup();
    renderApp("/personel/puantaj?ay=2026-09");
    const table = await screen.findByTestId("attendance");
    expect(within(table).getByText("Ayşe Demir")).toBeInTheDocument();
    expect(within(table).getByText("S-0012 · Dolum")).toBeInTheDocument();
    expect(within(table).getAllByText("R").length).toBeGreaterThan(0);
    expect(within(table).getByText("2,5")).toBeInTheDocument(); // FM toplamı
    expect(attendanceApi.getAttendanceGrid).toHaveBeenCalledWith(2026, 9, "");
    expect(screen.getByRole("link", { name: "Excel" })).toHaveAttribute(
      "href",
      "/api/v1/personnel/attendance/2026/9/export/",
    );

    const target = firstWorkday(grid());
    await user.click(
      within(table).getByRole("button", { name: `Ayşe Demir ${formatDate(target.date)}: Çalıştı` }),
    );
    const dialog = await screen.findByRole("dialog", { name: /Ayşe Demir · / });
    const hours = within(dialog).getByLabelText(/Fazla mesai/);
    await user.type(hours, "30");
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    expect(within(dialog).getByText("0 ile 24 arasında bir sayı yazın (ör. 2,5).")).toBeVisible();
    expect(attendanceApi.setAttendanceDay).not.toHaveBeenCalled();

    await user.clear(hours);
    await user.type(hours, "2,5");
    await user.type(within(dialog).getByLabelText(/Not/), "Sipariş");
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(attendanceApi.setAttendanceDay).toHaveBeenCalledWith({
        employee: 5,
        date: target.date,
        status: "WORKED",
        overtime_hours: "2.5",
        note: "Sipariş",
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("izin gününe fazla mesai girilmez", async () => {
    const user = userEvent.setup();
    renderApp("/personel/puantaj?ay=2026-09");
    const table = await screen.findByTestId("attendance");
    const target = firstWorkday(grid());
    await user.click(
      within(table).getByRole("button", { name: `Ayşe Demir ${formatDate(target.date)}: Çalıştı` }),
    );
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("textbox", { name: "Durum" }));
    await user.click(await screen.findByRole("option", { name: "Yİ · Yıllık izin" }));
    expect(within(dialog).getByLabelText(/Fazla mesai/)).toBeDisabled();
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(attendanceApi.setAttendanceDay).toHaveBeenCalledWith(
        expect.objectContaining({ status: "ANNUAL_LEAVE", overtime_hours: "0" }),
      ),
    );
  });

  it("aralık girişi zorunlu alanları ister ve uygular", async () => {
    const user = userEvent.setup();
    renderApp("/personel/puantaj?ay=2026-09");
    await screen.findByTestId("attendance");
    await user.click(screen.getByRole("button", { name: "Aralık gir" }));
    const dialog = await screen.findByRole("dialog", { name: "Aralık gir" });
    await user.click(within(dialog).getByRole("button", { name: "Uygula" }));
    expect(within(dialog).getAllByText("Bu alan zorunlu.")).toHaveLength(4);
    expect(attendanceApi.setAttendanceRange).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("textbox", { name: "Personel" }));
    await user.click(await screen.findByRole("option", { name: "Ayşe Demir (S-0012)" }));
    await user.type(within(dialog).getByLabelText(/Başlangıç/), "2026-09-14");
    await user.type(within(dialog).getByLabelText(/Bitiş/), "2026-09-10");
    await user.click(within(dialog).getByRole("textbox", { name: "Durum" }));
    await user.click(await screen.findByRole("option", { name: "Yİ · Yıllık izin" }));
    await user.click(within(dialog).getByRole("button", { name: "Uygula" }));
    expect(within(dialog).getByText("Bitiş başlangıçtan önce olamaz.")).toBeVisible();

    const end = within(dialog).getByLabelText(/Bitiş/);
    await user.clear(end);
    await user.type(end, "2026-09-25");
    await user.click(within(dialog).getByRole("button", { name: "Uygula" }));
    await waitFor(() =>
      expect(attendanceApi.setAttendanceRange).toHaveBeenCalledWith({
        employee: 5,
        department: "",
        start: "2026-09-14",
        end: "2026-09-25",
        status: "ANNUAL_LEAVE",
        note: "",
      }),
    );
  });

  it("ayı onaylar; bitmemiş ay onaylanamaz", async () => {
    const user = userEvent.setup();
    renderApp("/personel/puantaj?ay=2026-09");
    await screen.findByTestId("attendance");
    await user.click(screen.getByRole("button", { name: "Ayı onayla" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Eylül 2026 puantajı onaylansın mı\?/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Ayı onayla" }));
    await waitFor(() => expect(attendanceApi.approveAttendanceMonth).toHaveBeenCalledWith(2026, 9));

    vi.mocked(attendanceApi.getAttendanceGrid).mockResolvedValue(grid({ finished: false }));
    await user.click(screen.getByRole("button", { name: "Sonraki ay" }));
    await waitFor(() =>
      expect(attendanceApi.getAttendanceGrid).toHaveBeenLastCalledWith(2026, 10, ""),
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "Ayı onayla" })).toBeDisabled());
  });

  it("onaylı ay kilitlidir ve gerekçeyle yeniden açılır", async () => {
    const user = userEvent.setup();
    const locked = grid({ status: "APPROVED", month_record: RECORD });
    locked.rows[0].cells = locked.rows[0].cells.map((cell) => ({
      ...cell,
      explicit: true,
      editable: false,
    }));
    vi.mocked(attendanceApi.getAttendanceGrid).mockResolvedValue(locked);
    vi.mocked(attendanceApi.reopenAttendanceMonth).mockResolvedValue({
      ...RECORD,
      status: "OPEN",
    });
    renderApp("/personel/puantaj?ay=2026-09");
    const table = await screen.findByTestId("attendance");
    expect(screen.getByText("Onaylandı · PU-2026-00001")).toBeInTheDocument();
    expect(within(table).queryAllByRole("button")).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Aralık gir" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Yeniden aç" }));
    const dialog = await screen.findByRole("dialog", { name: "Eylül 2026 · yeniden aç" });
    await user.click(within(dialog).getByRole("button", { name: "Yeniden aç" }));
    expect(within(dialog).getByText("Bu alan zorunlu.")).toBeVisible();
    await user.type(within(dialog).getByLabelText(/Gerekçe/), "Rapor eksik girilmiş");
    await user.click(within(dialog).getByRole("button", { name: "Yeniden aç" }));
    await waitFor(() =>
      expect(attendanceApi.reopenAttendanceMonth).toHaveBeenCalledWith(
        2026,
        9,
        "Rapor eksik girilmiş",
      ),
    );
  });

  it("personel sekmelerinden puantaja geçilir; diğer roller açamaz", async () => {
    const user = userEvent.setup();
    const { router } = renderApp("/personel");
    await user.click(await screen.findByRole("tab", { name: "Puantaj" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/personel/puantaj"));
    expect(await screen.findByTestId("attendance")).toBeInTheDocument();
  });

  it("depo rolü puantajı göremez", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("depo"));
    renderApp("/personel/puantaj");
    expect(await screen.findByText("Yetkiniz yok")).toBeInTheDocument();
    expect(attendanceApi.getAttendanceGrid).not.toHaveBeenCalled();
  });
});

describe("tatil takvimi", () => {
  const HOLIDAYS: PublicHoliday[] = [
    { id: 1, date: "2027-01-01", name: "Yılbaşı", half_day: false },
    { id: 2, date: "2027-10-28", name: "Cumhuriyet Bayramı arifesi", half_day: true },
  ];

  beforeEach(() => {
    vi.mocked(attendanceApi.listHolidays).mockReset().mockResolvedValue(HOLIDAYS);
    vi.mocked(attendanceApi.addFixedHolidays).mockReset().mockResolvedValue([]);
    vi.mocked(attendanceApi.saveHoliday).mockReset().mockResolvedValue(HOLIDAYS[0]);
    vi.mocked(attendanceApi.removeHoliday).mockReset().mockResolvedValue();
    vi.mocked(attendanceApi.getAttendanceSettings).mockResolvedValue({
      rest_weekdays: [6],
      updated_at: "2026-10-29T10:00:00+03:00",
    });
    vi.mocked(attendanceApi.saveAttendanceSettings)
      .mockReset()
      .mockResolvedValue({
        rest_weekdays: [5, 6],
        updated_at: "2026-10-29T10:00:00+03:00",
      });
  });

  it("tatilleri listeler; sabit tatilleri ekler, yeni tatil girer ve kaldırır", async () => {
    const user = userEvent.setup();
    renderApp("/personel/tatiller?yil=2027");
    const table = await screen.findByTestId("holidays");
    expect(within(table).getByText("Yılbaşı")).toBeInTheDocument();
    expect(within(table).getByText("yarım gün")).toBeInTheDocument();
    expect(attendanceApi.listHolidays).toHaveBeenCalledWith(2027);

    await user.click(screen.getByRole("button", { name: "Yılın sabit tatillerini ekle" }));
    await waitFor(() => expect(attendanceApi.addFixedHolidays).toHaveBeenCalledWith(2027));

    await user.click(screen.getByRole("button", { name: "Tatil ekle" }));
    const dialog = await screen.findByRole("dialog", { name: "Tatil ekle" });
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    expect(within(dialog).getAllByText("Bu alan zorunlu.")).toHaveLength(2);
    await user.type(within(dialog).getByLabelText(/Tarih/), "2027-03-09");
    await user.type(within(dialog).getByLabelText(/^Ad/), "Ramazan Bayramı 1. gün");
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(attendanceApi.saveHoliday).toHaveBeenCalledWith(null, {
        date: "2027-03-09",
        name: "Ramazan Bayramı 1. gün",
        half_day: false,
      }),
    );

    await user.click(within(table).getByRole("button", { name: "Kaldır: Yılbaşı" }));
    const confirm = await screen.findByRole("dialog");
    await user.click(within(confirm).getByRole("button", { name: "Kaldır" }));
    await waitFor(() => expect(attendanceApi.removeHoliday).toHaveBeenCalledWith(1));
  });

  it("varsayılan hafta tatili günlerini kaydeder; en az bir gün ister", async () => {
    const user = userEvent.setup();
    renderApp("/personel/tatiller?yil=2027");
    const saturday = await screen.findByRole("checkbox", { name: "Cumartesi" });
    const sunday = screen.getByRole("checkbox", { name: "Pazar" });
    expect(sunday).toBeChecked();
    await user.click(sunday);
    await user.click(screen.getByRole("button", { name: "Kaydet" }));
    expect(screen.getByText("En az bir, en çok altı gün seçin.")).toBeVisible();
    expect(attendanceApi.saveAttendanceSettings).not.toHaveBeenCalled();

    await user.click(saturday);
    await user.click(sunday);
    await user.click(screen.getByRole("button", { name: "Kaydet" }));
    await waitFor(() => expect(attendanceApi.saveAttendanceSettings).toHaveBeenCalledWith([5, 6]));
  });
});
