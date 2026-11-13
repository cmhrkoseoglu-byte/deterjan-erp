import { notifications } from "@mantine/notifications";
import { act, screen, waitFor, within } from "@testing-library/react";
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
import { formatWorkedHours, parseWorkedHours } from "./attendanceFormat";

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
    return {
      date,
      weekday,
      rest: weekday === 6,
      holiday_name: "",
      half_day: false,
      expected_hours: "9.00",
    };
  });
}

function grid(extra: Partial<AttendanceGrid> = {}): AttendanceGrid {
  const days = columns(2026, 9);
  const cells: AttendanceCell[] = days.map((day) => ({
    date: day.date,
    status: day.rest ? "WEEKLY_REST" : "WORKED",
    code: day.rest ? "HT" : "Ç",
    overtime_hours: "0.00",
    holiday_half_worked: false,
    worked_hours: null,
    short_day: false,
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
    payroll: null,
    daily_hours: "9.00",
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
          short_days: 0,
          full_days: 21,
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

/** İlk iş günü (ve istenirse sütunu) değiştirilmiş tablo. */
function gridWithDay(
  cell: Partial<AttendanceCell>,
  column: Partial<AttendanceColumn> = {},
): AttendanceGrid {
  const base = grid();
  const { date } = firstWorkday(base);
  return {
    ...base,
    days: base.days.map((day) => (day.date === date ? { ...day, ...column } : day)),
    rows: [
      {
        ...base.rows[0],
        cells: base.rows[0].cells.map((item) => (item.date === date ? { ...item, ...cell } : item)),
      },
    ],
  };
}

/** İlk iş gününün penceresini açar; `state` hücre düğmesinin adındaki durumdur. */
async function openDay(user: ReturnType<typeof userEvent.setup>, state = "Çalıştı") {
  const table = await screen.findByTestId("attendance");
  const { date } = firstWorkday(grid());
  await user.click(
    within(table).getByRole("button", { name: `Ayşe Demir ${formatDate(date)}: ${state}` }),
  );
  return screen.findByRole("dialog", { name: /Ayşe Demir · / });
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
        worked_hours: null,
        short_day: false,
        overtime_hours: "2.5",
        holiday_half_worked: false,
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

  it("yarım gün tatilde öğleden sonra çalışma yalnızca çalışılan güne işaretlenir", async () => {
    const user = userEvent.setup();
    const base = grid();
    const target = firstWorkday(base);
    const index = base.days.findIndex((day) => day.date === target.date);
    // Başka bir yarım gün tatil daha önce işaretlenmiş: tabloda Ç½ görünür. Tatili sonradan
    // kaldırılmış işaretli gün ise düz Ç görünür (bordro ve Excel gibi).
    const worked = (after: number) =>
      base.rows[0].cells.findIndex((cell, i) => i > after && cell.status === "WORKED");
    const other = worked(index);
    const stale = worked(other);
    const days = base.days.map((day, i) =>
      i === index || i === other
        ? { ...day, holiday_name: "Arife", half_day: true, expected_hours: "4.50" }
        : day,
    );
    const marked = base.rows[0].cells.map((cell, i) =>
      i === other || i === stale ? { ...cell, holiday_half_worked: true } : cell,
    );
    vi.mocked(attendanceApi.getAttendanceGrid).mockResolvedValue({
      ...base,
      days,
      rows: [{ ...base.rows[0], cells: marked }],
    });
    renderApp("/personel/puantaj?ay=2026-09");
    const table = await screen.findByTestId("attendance");
    expect(within(table).getAllByText("Ç½")).toHaveLength(1);
    expect(
      within(table).getByRole("button", {
        name: `Ayşe Demir ${formatDate(days[stale].date)}: Çalıştı`,
      }),
    ).toHaveTextContent(/^Ç$/);
    await user.click(
      within(table).getByRole("button", { name: `Ayşe Demir ${formatDate(target.date)}: Çalıştı` }),
    );
    const dialog = await screen.findByRole("dialog");
    const half = within(dialog).getByLabelText(/Öğleden sonra da çalıştı/);
    expect(half).toBeEnabled();
    expect(half).not.toBeChecked();
    await user.click(half);
    await user.click(within(dialog).getByRole("textbox", { name: "Durum" }));
    await user.click(await screen.findByRole("option", { name: "Yİ · Yıllık izin" }));
    expect(within(dialog).getByLabelText(/Öğleden sonra da çalıştı/)).toBeDisabled();
    await user.click(within(dialog).getByRole("textbox", { name: "Durum" }));
    await user.click(await screen.findByRole("option", { name: "Ç · Çalıştı" }));
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(attendanceApi.setAttendanceDay).toHaveBeenCalledWith(
        expect.objectContaining({ status: "WORKED", holiday_half_worked: true }),
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

  it("bordrosu onaylı ayın puantajı yeniden açılamaz", async () => {
    vi.mocked(attendanceApi.getAttendanceGrid).mockResolvedValue(
      grid({
        status: "APPROVED",
        month_record: RECORD,
        payroll: { number: "BR-2026-00001", status: "APPROVED" },
      }),
    );
    renderApp("/personel/puantaj?ay=2026-09");
    await screen.findByTestId("attendance");
    expect(screen.getByRole("button", { name: "Yeniden aç" })).toBeDisabled();
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

describe("çalışılan saat ve yarım gün", () => {
  const INVALID = "Çalışılan saat 0'dan büyük, en çok 24 olabilir; en çok iki ondalık (ör. 4,5).";

  it("eksik saat yazılınca yarım gün işaretli gelir; saat ve işaret kaydedilir", async () => {
    const user = userEvent.setup();
    renderApp("/personel/puantaj?ay=2026-09");
    const dialog = await openDay(user);
    const hours = within(dialog).getByLabelText("Çalışılan saat");
    const short = within(dialog).getByLabelText(/Yarım gün çalıştı/);
    expect(hours).toBeEnabled();
    expect(hours).toHaveValue("");
    expect(
      within(dialog).getByText(
        "Bu gün için çalışma saati: 9. Boş bırakırsanız tam gün sayılır; fazla mesaiyi buraya yazmayın.",
      ),
    ).toBeInTheDocument();
    // Açıklama bordro etkisini söyler.
    expect(
      within(dialog).getByText(
        "Çalışılan saat bu günün çalışma saatinin altındaysa işaretli gelir. Yarım gün saymayacaksanız işareti kaldırın; saat kayıtlı kalır. Bordroda yarım gün çalışılan her gün için günlük ücretin yarısı kesilir (hafta tatili ya da tam gün tatile Ç yazılan günde kesilmez).",
      ),
    ).toBeInTheDocument();
    // Saat yazılmadan kutu görünür ama kapalıdır.
    expect(short).toBeDisabled();
    expect(short).not.toBeChecked();

    await user.type(hours, "4,5");
    expect(short).toBeEnabled();
    expect(short).toBeChecked();
    const live = within(dialog).getByText(
      "Gün YG olarak kaydedilecek; bordroda yarım günlük ücret kesilir.",
    );
    expect(live).toBeVisible();
    expect(live).toHaveAttribute("aria-live", "polite");
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(attendanceApi.setAttendanceDay).toHaveBeenCalledWith({
        employee: 5,
        date: firstWorkday(grid()).date,
        status: "WORKED",
        worked_hours: "4.5",
        short_day: true,
        overtime_hours: "0",
        holiday_half_worked: false,
        note: "",
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("hafta tatiline Ç yazılmış günde YG ücret kesmez; pencere bunu söyler", async () => {
    const user = userEvent.setup();
    vi.mocked(attendanceApi.getAttendanceGrid).mockResolvedValue(gridWithDay({}, { rest: true }));
    renderApp("/personel/puantaj?ay=2026-09");
    const dialog = await openDay(user);
    const short = within(dialog).getByLabelText(/Yarım gün çalıştı/);
    await user.type(within(dialog).getByLabelText("Çalışılan saat"), "4,5");
    expect(short).toBeChecked();
    expect(
      within(dialog).getByText(
        "Gün YG olarak kaydedilecek; takvimde tatil olduğu için bordroda ücret kesilmez.",
      ),
    ).toBeVisible();
    expect(
      within(dialog).queryByText(
        "Gün YG olarak kaydedilecek; bordroda yarım günlük ücret kesilir.",
      ),
    ).not.toBeInTheDocument();
  });

  it("işaret kaldırılırsa gün Ç kalır; saat düzeltilince işaret geri gelmez", async () => {
    const user = userEvent.setup();
    renderApp("/personel/puantaj?ay=2026-09");
    const dialog = await openDay(user);
    const hours = within(dialog).getByLabelText("Çalışılan saat");
    const short = within(dialog).getByLabelText(/Yarım gün çalıştı/);
    await user.type(hours, "8,5");
    expect(short).toBeChecked();
    await user.click(short);
    expect(short).not.toBeChecked();
    expect(within(dialog).getByText("Saat kaydedilir, gün Ç kalır; ücret kesilmez.")).toBeVisible();
    // Kullanıcının seçimi pencere kapanana kadar geçerlidir: saat düzeltilince öneri geri gelmez.
    await user.clear(hours);
    await user.type(hours, "8");
    expect(short).toBeEnabled();
    expect(short).not.toBeChecked();
    // Durum değişip geri dönünce de: saat ve seçim yerinde kalır.
    await user.click(within(dialog).getByRole("textbox", { name: "Durum" }));
    await user.click(await screen.findByRole("option", { name: "Yİ · Yıllık izin" }));
    await user.click(within(dialog).getByRole("textbox", { name: "Durum" }));
    await user.click(await screen.findByRole("option", { name: "Ç · Çalıştı" }));
    expect(within(dialog).getByLabelText("Çalışılan saat")).toHaveValue("8");
    expect(within(dialog).getByLabelText(/Yarım gün çalıştı/)).toBeEnabled();
    expect(within(dialog).getByLabelText(/Yarım gün çalıştı/)).not.toBeChecked();
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(attendanceApi.setAttendanceDay).toHaveBeenCalledWith(
        expect.objectContaining({ worked_hours: "8", short_day: false }),
      ),
    );
  });

  it("kayıtlı 8,5 saatli işaretsiz gün not değişikliğiyle işaretsiz kalır", async () => {
    const user = userEvent.setup();
    vi.mocked(attendanceApi.getAttendanceGrid).mockResolvedValue(
      gridWithDay({ worked_hours: "8.50", short_day: false, explicit: true }),
    );
    renderApp("/personel/puantaj?ay=2026-09");
    const dialog = await openDay(user);
    expect(within(dialog).getByLabelText("Çalışılan saat")).toHaveValue("8,5");
    const short = within(dialog).getByLabelText(/Yarım gün çalıştı/);
    expect(short).toBeEnabled();
    expect(short).not.toBeChecked();
    expect(within(dialog).getByText("Saat kaydedilir, gün Ç kalır; ücret kesilmez.")).toBeVisible();
    await user.type(within(dialog).getByLabelText(/Not/), "Erken çıktı");
    expect(short).not.toBeChecked();
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(attendanceApi.setAttendanceDay).toHaveBeenCalledWith({
        employee: 5,
        date: firstWorkday(grid()).date,
        status: "WORKED",
        worked_hours: "8.5",
        short_day: false,
        overtime_hours: "0",
        holiday_half_worked: false,
        note: "Erken çıktı",
      }),
    );
  });

  it("saat değişince öneri yeniden gelir; kayıtlı saate dönülünce kayıtlı karar", async () => {
    const user = userEvent.setup();
    vi.mocked(attendanceApi.getAttendanceGrid).mockResolvedValue(
      gridWithDay({ worked_hours: "8.50", short_day: false, explicit: true }),
    );
    renderApp("/personel/puantaj?ay=2026-09");
    const dialog = await openDay(user);
    const hours = within(dialog).getByLabelText("Çalışılan saat");
    const short = within(dialog).getByLabelText(/Yarım gün çalıştı/);
    await user.clear(hours);
    await user.type(hours, "6");
    expect(short).toBeChecked();
    // Karşılaştırma sayıcadır: "8,50" kayıtlı 8,5 ile aynıdır.
    await user.clear(hours);
    await user.type(hours, "8,50");
    expect(short).not.toBeChecked();
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(attendanceApi.setAttendanceDay).toHaveBeenCalledWith(
        expect.objectContaining({ worked_hours: "8.50", short_day: false }),
      ),
    );
  });

  it("kayıtlı 4,5 saatli yarım gün korunur", async () => {
    const user = userEvent.setup();
    vi.mocked(attendanceApi.getAttendanceGrid).mockResolvedValue(
      gridWithDay({ code: "YG", worked_hours: "4.50", short_day: true, explicit: true }),
    );
    renderApp("/personel/puantaj?ay=2026-09");
    const dialog = await openDay(user, "Çalıştı, yarım gün");
    expect(within(dialog).getByLabelText("Çalışılan saat")).toHaveValue("4,5");
    expect(within(dialog).getByLabelText(/Yarım gün çalıştı/)).toBeChecked();
    await user.type(within(dialog).getByLabelText(/Not/), "Hastane");
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(attendanceApi.setAttendanceDay).toHaveBeenCalledWith({
        employee: 5,
        date: firstWorkday(grid()).date,
        status: "WORKED",
        worked_hours: "4.5",
        short_day: true,
        overtime_hours: "0",
        holiday_half_worked: false,
        note: "Hastane",
      }),
    );
  });

  it("saat temizlenince yarım gün işareti gönderilmez", async () => {
    const user = userEvent.setup();
    vi.mocked(attendanceApi.getAttendanceGrid).mockResolvedValue(
      gridWithDay({ code: "YG", worked_hours: "4.50", short_day: true, explicit: true }),
    );
    renderApp("/personel/puantaj?ay=2026-09");
    const dialog = await openDay(user, "Çalıştı, yarım gün");
    const hours = within(dialog).getByLabelText("Çalışılan saat");
    const short = within(dialog).getByLabelText(/Yarım gün çalıştı/);
    // Kutu kaldırılıp yeniden işaretlenir: kullanıcının seçimi "işaretli"dir.
    await user.click(short);
    await user.click(short);
    expect(short).toBeChecked();
    await user.clear(hours);
    expect(short).toBeDisabled();
    expect(short).not.toBeChecked();
    expect(within(dialog).queryByText(/olarak kaydedilecek/)).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(attendanceApi.setAttendanceDay).toHaveBeenCalledWith({
        employee: 5,
        date: firstWorkday(grid()).date,
        status: "WORKED",
        worked_hours: null,
        short_day: false,
        overtime_hours: "0",
        holiday_half_worked: false,
        note: "",
      }),
    );
  });

  it("günün çalışma saatini aşan ya da geçersiz saat kaydedilmez", async () => {
    const user = userEvent.setup();
    renderApp("/personel/puantaj?ay=2026-09");
    const dialog = await openDay(user);
    const hours = within(dialog).getByLabelText("Çalışılan saat");
    const save = within(dialog).getByRole("button", { name: "Kaydet" });
    await user.type(hours, "10");
    expect(within(dialog).getByLabelText(/Yarım gün çalıştı/)).toBeDisabled();
    await user.click(save);
    expect(
      within(dialog).getByText("En çok 9 yazılabilir; fazlasını fazla mesaiye yazın."),
    ).toBeVisible();
    expect(attendanceApi.setAttendanceDay).not.toHaveBeenCalled();

    for (const text of ["0", "25", "4,555", "dört"]) {
      await user.clear(hours);
      await user.type(hours, text);
      await user.click(save);
      expect(within(dialog).getByText(INVALID)).toBeVisible();
      expect(attendanceApi.setAttendanceDay).not.toHaveBeenCalled();
    }

    // Günün çalışma saatine eşit saat tam gündür: işaretsiz gider (sunucu saati kaydetmez).
    await user.clear(hours);
    await user.type(hours, "9");
    await user.click(save);
    await waitFor(() =>
      expect(attendanceApi.setAttendanceDay).toHaveBeenCalledWith(
        expect.objectContaining({ worked_hours: "9", short_day: false }),
      ),
    );
  });

  it("çalışılan gün dışında saat alanı kapalıdır ve saat gönderilmez", async () => {
    const user = userEvent.setup();
    renderApp("/personel/puantaj?ay=2026-09");
    const dialog = await openDay(user);
    const hours = within(dialog).getByLabelText("Çalışılan saat");
    await user.type(hours, "4,5");
    await user.click(within(dialog).getByRole("textbox", { name: "Durum" }));
    await user.click(await screen.findByRole("option", { name: "Yİ · Yıllık izin" }));
    expect(hours).toBeDisabled();
    expect(hours).toHaveValue("");
    expect(hours).toHaveAccessibleDescription(
      "Çalışılan saat yalnızca çalışılan güne (Ç) girilir.",
    );
    expect(within(dialog).queryByLabelText(/Yarım gün çalıştı/)).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(attendanceApi.setAttendanceDay).toHaveBeenCalledWith(
        expect.objectContaining({ status: "ANNUAL_LEAVE", worked_hours: null, short_day: false }),
      ),
    );
  });

  it("günlük çalışma saati yokken saat girilemez; onay penceresi saat söylemez", async () => {
    const user = userEvent.setup();
    const base = grid({ daily_hours: null });
    vi.mocked(attendanceApi.getAttendanceGrid).mockResolvedValue({
      ...base,
      days: base.days.map((day) => ({ ...day, expected_hours: null })),
    });
    renderApp("/personel/puantaj?ay=2026-09");
    await screen.findByTestId("attendance");
    expect(screen.getByRole("link", { name: "Günlük çalışma saati belirlenmedi" })).toHaveAttribute(
      "href",
      "/personel/tatiller",
    );
    const dialog = await openDay(user);
    expect(within(dialog).getByLabelText("Çalışılan saat")).toBeDisabled();
    expect(
      within(dialog).getByText("Günlük çalışma saati belirlenmedi (Personel > Tatil takvimi)."),
    ).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/Yarım gün çalıştı/)).toBeDisabled();
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(attendanceApi.setAttendanceDay).toHaveBeenCalledWith(
        expect.objectContaining({ worked_hours: null, short_day: false }),
      ),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Ayı onayla" }));
    const confirm = await screen.findByRole("dialog");
    expect(within(confirm).getByText(/Eylül 2026 puantajı onaylansın mı\?/)).toBeInTheDocument();
    expect(within(confirm).queryByText(/saatle onaylanacak/)).not.toBeInTheDocument();
  });

  it("fazla mesaisi olan güne eksik saat yazılamaz; fazla mesai sessizce silinmez", async () => {
    const user = userEvent.setup();
    vi.mocked(attendanceApi.getAttendanceGrid).mockResolvedValue(
      gridWithDay({ overtime_hours: "2.00", explicit: true }),
    );
    renderApp("/personel/puantaj?ay=2026-09");
    const dialog = await openDay(user);
    const overtime = within(dialog).getByLabelText(/Fazla mesai/);
    await user.type(within(dialog).getByLabelText("Çalışılan saat"), "4,5");
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    expect(
      within(dialog).getByText(
        "Çalışılan saat günün çalışma saatinin altındayken fazla mesai girilmez.",
      ),
    ).toBeVisible();
    expect(overtime).toHaveValue("2");
    expect(attendanceApi.setAttendanceDay).not.toHaveBeenCalled();

    await user.clear(overtime);
    await user.click(within(dialog).getByRole("button", { name: "Kaydet" }));
    await waitFor(() =>
      expect(attendanceApi.setAttendanceDay).toHaveBeenCalledWith(
        expect.objectContaining({ worked_hours: "4.5", short_day: true, overtime_hours: "0" }),
      ),
    );
  });

  it("yarım gün tatilde saat yarıdır; öğleden sonra işaretiyle eksik saat yazılamaz", async () => {
    const user = userEvent.setup();
    vi.mocked(attendanceApi.getAttendanceGrid).mockResolvedValue(
      gridWithDay(
        { holiday_half_worked: true, explicit: true },
        { holiday_name: "Arife", half_day: true, expected_hours: "4.50" },
      ),
    );
    renderApp("/personel/puantaj?ay=2026-09");
    const dialog = await openDay(user);
    const hours = within(dialog).getByLabelText("Çalışılan saat");
    const half = within(dialog).getByLabelText(/Öğleden sonra da çalıştı/);
    const save = within(dialog).getByRole("button", { name: "Kaydet" });
    expect(
      within(dialog).getByText(
        "Bu gün yarım gün tatil; çalışma saati 4,5. Boş bırakırsanız tam gün sayılır.",
      ),
    ).toBeInTheDocument();
    await user.type(hours, "5");
    await user.click(save);
    expect(
      within(dialog).getByText(
        "En çok 4,5 yazılabilir; öğleden sonra da çalışıldıysa saati boş bırakıp “Öğleden sonra da çalıştı”yı işaretleyin.",
      ),
    ).toBeVisible();
    expect(attendanceApi.setAttendanceDay).not.toHaveBeenCalled();

    await user.clear(hours);
    await user.type(hours, "3");
    await user.click(save);
    expect(
      within(dialog).getByText(
        "“Öğleden sonra da çalıştı” işaretliyken çalışılan saat günün çalışma saatinin altında olamaz.",
      ),
    ).toBeVisible();
    // İşaret sessizce kaldırılmaz; kullanıcı kaldırınca gün kaydedilir.
    expect(half).toBeChecked();
    expect(attendanceApi.setAttendanceDay).not.toHaveBeenCalled();
    await user.click(half);
    await user.click(save);
    await waitFor(() =>
      expect(attendanceApi.setAttendanceDay).toHaveBeenCalledWith(
        expect.objectContaining({
          worked_hours: "3",
          short_day: true,
          holiday_half_worked: false,
        }),
      ),
    );
  });

  it("tabloda yarım gün (YG), saat satırı ve toplamlar görünür", async () => {
    const data = gridWithDay({
      code: "YG",
      worked_hours: "4.50",
      short_day: true,
      explicit: true,
    });
    // Saati eksik ama yarım gün sayılmayan ikinci gün Ç kalır; saati kodun altında görünür.
    const second = data.rows[0].cells.filter((cell) => cell.status === "WORKED")[1];
    data.rows[0].cells = data.rows[0].cells.map((cell) =>
      cell.date === second.date ? { ...cell, worked_hours: "8.50", explicit: true } : cell,
    );
    data.rows[0].totals = { ...data.rows[0].totals, short_days: 1, full_days: 20 };
    vi.mocked(attendanceApi.getAttendanceGrid).mockResolvedValue(data);
    renderApp("/personel/puantaj?ay=2026-09");
    const table = await screen.findByTestId("attendance");
    const short = within(table).getByRole("button", {
      name: `Ayşe Demir ${formatDate(firstWorkday(grid()).date)}: Çalıştı, yarım gün`,
    });
    expect(short).toHaveTextContent(/^YG4,5$/);
    expect(short).toHaveAttribute("title", "Çalıştı · Yarım gün çalıştı · Çalışılan saat: 4,5");
    const plain = within(table).getByRole("button", {
      name: `Ayşe Demir ${formatDate(second.date)}: Çalıştı`,
    });
    expect(plain).toHaveTextContent(/^Ç8,5$/);
    expect(plain).toHaveAttribute("title", "Çalıştı · Çalışılan saat: 8,5");
    expect(within(table).getByText("2,5")).toBeInTheDocument(); // FM toplamı
    expect(screen.getByText("YG yarım gün çalıştı")).toBeInTheDocument();
    expect(screen.getByText("½ yarım gün tatil")).toBeInTheDocument();

    // Toplamlarda Ç tam gün çalışılan günlerdir (21 çalışılan günün 20'si); YG hemen yanındadır.
    const headers = within(table).getAllByRole("columnheader");
    const index = headers.findIndex((header) => header.textContent === "YG");
    expect(headers[index - 1]).toHaveTextContent(/^Ç$/);
    const row = within(table).getByText("Ayşe Demir").closest("tr")!;
    const totals = within(row).getAllByRole("cell");
    expect(totals[index - 1]).toHaveTextContent(/^20$/);
    expect(totals[index]).toHaveTextContent(/^1$/);
  });

  it("ayın günlük çalışma saatini gösterir; onay penceresi saati söyler", async () => {
    const user = userEvent.setup();
    renderApp("/personel/puantaj?ay=2026-09");
    await screen.findByTestId("attendance");
    expect(screen.getByText("Günlük çalışma saati: 9")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Ayı onayla" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Ay günlük 9 saatle onaylanacak\./)).toBeInTheDocument();
  });

  it("onaylı ayda günlük çalışma saati kayıtlı değilse söyler", async () => {
    vi.mocked(attendanceApi.getAttendanceGrid).mockResolvedValue(
      grid({ status: "APPROVED", month_record: RECORD, daily_hours: null }),
    );
    renderApp("/personel/puantaj?ay=2026-09");
    await screen.findByTestId("attendance");
    expect(screen.getByText("Onayda günlük çalışma saati kayıtlı değil")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Günlük çalışma saati/ })).not.toBeInTheDocument();
  });
});

describe("çalışılan saat biçimleri", () => {
  it("girişi okur: virgül, en çok iki ondalık, 0'dan büyük, en çok 24", () => {
    expect(parseWorkedHours(" 4,5 ")).toEqual({ kind: "value", value: "4.5", number: 4.5 });
    expect(parseWorkedHours("0,25")).toEqual({ kind: "value", value: "0.25", number: 0.25 });
    expect(parseWorkedHours("24")).toEqual({ kind: "value", value: "24", number: 24 });
    expect(parseWorkedHours("  ")).toEqual({ kind: "empty" });
    for (const text of ["0", "0,00", "24,01", "100", "4,555", "4,", ",5", "-1", "1e1", "dört"]) {
      expect(parseWorkedHours(text), text).toEqual({ kind: "invalid" });
    }
  });

  it("değeri Türkçe yazar; sıfırı gizlemez", () => {
    expect(formatWorkedHours(null)).toBe("");
    expect(formatWorkedHours("4.50")).toBe("4,5");
    expect(formatWorkedHours("9.00")).toBe("9");
    expect(formatWorkedHours("0.00")).toBe("0");
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
      daily_hours: "9.00",
      updated_at: "2026-10-29T10:00:00+03:00",
    });
    vi.mocked(attendanceApi.saveAttendanceSettings)
      .mockReset()
      .mockResolvedValue({
        rest_weekdays: [5, 6],
        daily_hours: "9.00",
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
    await waitFor(() =>
      expect(attendanceApi.saveAttendanceSettings).toHaveBeenCalledWith({
        rest_weekdays: [5, 6],
        daily_hours: "9",
      }),
    );
  });

  it("günlük çalışma saatini gösterir, doğrular ve hafta tatiliyle birlikte kaydeder", async () => {
    const user = userEvent.setup();
    const show = vi.spyOn(notifications, "show").mockReturnValue("bildirim");
    renderApp("/personel/tatiller?yil=2027");
    const hours = await screen.findByLabelText("Günlük çalışma saati");
    expect(hours).toHaveValue("9");
    expect(screen.getByText("Puantaj ayarları")).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Kaydet" });

    for (const text of ["0", "25", "7,555"]) {
      await user.clear(hours);
      await user.type(hours, text);
      await user.click(save);
      expect(
        screen.getByText(
          "Günlük çalışma saati 0'dan büyük, en çok 24 olmalı; en çok iki ondalıklı bir sayı yazın (ör. 7,5).",
        ),
      ).toBeVisible();
    }
    // Kayıtlı değer boşaltılamaz, yalnızca değiştirilir.
    await user.clear(hours);
    await user.click(save);
    expect(screen.getByText("Günlük çalışma saati boş bırakılamaz.")).toBeVisible();
    expect(attendanceApi.saveAttendanceSettings).not.toHaveBeenCalled();

    await user.type(hours, "7,5");
    await user.click(screen.getByRole("checkbox", { name: "Cumartesi" }));
    await user.click(save);
    await waitFor(() =>
      expect(attendanceApi.saveAttendanceSettings).toHaveBeenCalledWith({
        rest_weekdays: [6, 5],
        daily_hours: "7.5",
      }),
    );
    await waitFor(() =>
      expect(show).toHaveBeenCalledWith(
        expect.objectContaining({ message: "Puantaj ayarları kaydedildi." }),
      ),
    );
    show.mockRestore();
  });

  it("günlük çalışma saati hiç belirlenmediyse boş bırakılabilir ve gönderilmez", async () => {
    const user = userEvent.setup();
    vi.mocked(attendanceApi.getAttendanceSettings).mockResolvedValue({
      rest_weekdays: [6],
      daily_hours: null,
      updated_at: "2026-10-29T10:00:00+03:00",
    });
    renderApp("/personel/tatiller?yil=2027");
    expect(await screen.findByLabelText("Günlük çalışma saati")).toHaveValue("");
    await user.click(screen.getByRole("button", { name: "Kaydet" }));
    await waitFor(() => expect(attendanceApi.saveAttendanceSettings).toHaveBeenCalled());
    // Anahtar hiç gönderilmez: sunucu günlük çalışma saatini yalnızca gönderilirse değiştirir.
    expect(vi.mocked(attendanceApi.saveAttendanceSettings).mock.calls[0]).toStrictEqual([
      { rest_weekdays: [6] },
    ]);
  });

  it("yenilenen hafta tatili ayarı yazılmakta olan günlük çalışma saatini silmez", async () => {
    const user = userEvent.setup();
    const { queryClient } = renderApp("/personel/tatiller?yil=2027");
    const hours = await screen.findByLabelText("Günlük çalışma saati");
    await user.clear(hours);
    await user.type(hours, "7,5");
    // Ayar başka bir oturumda değişti: hafta tatili farklı, günlük çalışma saati aynı.
    vi.mocked(attendanceApi.getAttendanceSettings).mockResolvedValue({
      rest_weekdays: [5, 6],
      daily_hours: "9.00",
      updated_at: "2026-10-30T10:00:00+03:00",
    });
    await act(() =>
      queryClient.invalidateQueries({ queryKey: attendanceApi.attendanceKeys.settings }),
    );
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Cumartesi" })).toBeChecked());
    expect(hours).toHaveValue("7,5");
  });
});
