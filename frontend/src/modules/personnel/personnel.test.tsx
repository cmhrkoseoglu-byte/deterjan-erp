import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../../api/auth";
import * as personnelApi from "../../api/personnel";
import type { Employee, EmployeeDocument } from "../../api/personnel";
import * as workflowApi from "../../api/workflow";
import type { AuditEntry } from "../../api/workflow";
import { httpError, page, userWith } from "../../test/fixtures";
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
    national_id: "",
    birth_date: null,
    birth_place: "",
    education_level: "",
    education_level_display: "",
    school: "",
    field_of_study: "",
    graduation_year: null,
    user: null,
    user_info: null,
    is_active: true,
    created_at: "2026-10-25T10:00:00+03:00",
    updated_at: "2026-10-25T10:00:00+03:00",
    ...extra,
  };
}

const LINKED = { id: 9, username: "dolum1", full_name: "Ayşe Demir", is_active: true };

function document(extra: Partial<EmployeeDocument> = {}): EmployeeDocument {
  return {
    id: 1,
    employee: 5,
    kind: "PAYROLL",
    kind_display: "Bordro",
    original_name: "eylul.pdf",
    size: 2048,
    mime_type: "application/pdf",
    period: "2026-09-01",
    valid_from: null,
    valid_until: null,
    note: "",
    uploaded_by_name: "Demo Yönetim",
    created_at: "2026-10-01T10:00:00+03:00",
    download_url: "/api/v1/personnel/documents/1/download/",
    ...extra,
  };
}

beforeEach(() => {
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  vi.mocked(personnelApi.listEmployees).mockResolvedValue(page([employee()]));
  vi.mocked(personnelApi.listDepartments).mockResolvedValue(["Depo", "Dolum"]);
  vi.mocked(personnelApi.listLinkableUsers).mockResolvedValue([LINKED]);
  vi.mocked(personnelApi.fetchEmployeeHistory).mockResolvedValue([]);
  vi.mocked(personnelApi.listEmployeeDocuments).mockResolvedValue([]);
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
    const nationalId = within(dialog).getByLabelText("TC kimlik no");
    const graduationYear = within(dialog).getByLabelText("Mezuniyet yılı");
    await user.type(nationalId, "12345");
    await user.type(graduationYear, "12");
    await user.click(within(dialog).getByRole("button", { name: "Kartı aç" }));
    expect(within(dialog).getByText("11 haneli bir sayı olmalı.")).toBeInTheDocument();
    expect(within(dialog).getByText("Dört haneli bir yıl yazın.")).toBeInTheDocument();
    expect(personnelApi.createEmployee).not.toHaveBeenCalled();

    await user.clear(nationalId);
    await user.type(nationalId, "100 000 001 46");
    await user.clear(graduationYear);
    await user.type(graduationYear, "2012");
    await user.type(within(dialog).getByLabelText("Doğum yeri"), "İzmir");
    await user.click(within(dialog).getByRole("textbox", { name: "Öğrenim durumu" }));
    await user.click(await screen.findByRole("option", { name: "Lisans" }));
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
        national_id: "10000000146",
        birth_date: null,
        birth_place: "İzmir",
        education_level: "BACHELOR",
        school: "",
        field_of_study: "",
        graduation_year: 2012,
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
    vi.mocked(personnelApi.getEmployee).mockResolvedValue(
      employee({
        user_info: LINKED,
        user: 9,
        national_id: "10000000146",
        birth_date: "1990-05-17",
        birth_place: "İzmir",
        education_level: "BACHELOR",
        education_level_display: "Lisans",
        school: "Ege Üniversitesi",
        graduation_year: 2012,
      }),
    );
    const entry: AuditEntry = {
      id: 1,
      timestamp: "2026-10-25T11:00:00+03:00",
      actor: 1,
      actor_name: "Demo Yönetim",
      action: "update",
      action_label: "Güncelleme",
      changes: {
        hire_date: ["2024-02-01", "2024-03-01"],
        user: [null, 9],
        national_id: [null, "*******0146"],
        education_level: ["HIGH_SCHOOL", "BACHELOR"],
      },
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
    // Kartta TC kimlik no açık, geçmişte maskeli.
    expect(screen.getByText("10000000146")).toBeInTheDocument();
    expect(screen.getByText("TC kimlik no: — → *******0146")).toBeInTheDocument();
    expect(screen.getByText("17.05.1990")).toBeInTheDocument();
    expect(screen.getByText("Lisans")).toBeInTheDocument();
    expect(screen.getByText("Ege Üniversitesi")).toBeInTheDocument();
    expect(screen.getByText("Öğrenim durumu: Lise → Lisans")).toBeInTheDocument();
    expect(await screen.findByText("Henüz belge eklenmedi.")).toBeInTheDocument();
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
      expect(personnelApi.terminateEmployee).toHaveBeenCalledWith(5, "2026-09-30", "", false),
    );
    // Kayıttan sonra pencere kapanır ve kart yenilenir.
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() =>
      expect(vi.mocked(personnelApi.getEmployee).mock.calls.length).toBeGreaterThan(loads),
    );
  });

  const AFTER_EXIT =
    "Çıkış tarihinden (30.09.2026) sonra puantajda kayıtlı 2 gün var: Ekim 2026: 05–06.10 Yİ. " +
    "Kaydederseniz bu günler puantajdan kaldırılır; kişi yeniden işe başlatılsa da geri gelmez.";

  async function openTerminate(user: ReturnType<typeof userEvent.setup>, day = "2026-09-30") {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    vi.mocked(personnelApi.getEmployee).mockResolvedValue(employee());
    renderApp("/personel/5");
    await user.click(await screen.findByRole("button", { name: "İşten ayrıldı" }));
    const dialog = await screen.findByRole("dialog");
    const date = within(dialog).getByLabelText(/İşten çıkış tarihi/);
    await user.clear(date);
    await user.type(date, day);
    return { dialog, date };
  }

  it("çıkıştan sonraki puantaj günlerini listeler ve onayla kaldırır", async () => {
    const user = userEvent.setup();
    const terminate = vi.mocked(personnelApi.terminateEmployee);
    terminate.mockReset();
    terminate
      .mockRejectedValueOnce(httpError(400, { code: "attendance_after_exit", detail: AFTER_EXIT }))
      .mockResolvedValueOnce(employee({ is_active: false, termination_date: "2026-09-30" }));
    const { dialog } = await openTerminate(user);
    expect(within(dialog).getByText("Son çalışma günü (o gün dahil).")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "İşten ayrıldı" }));
    // Günler bir kez (uyarı olarak) listelenir; düğme onay ister.
    expect(await within(dialog).findAllByText(/Ekim 2026: 05–06\.10 Yİ/)).toHaveLength(1);
    await user.click(within(dialog).getByRole("button", { name: "Kaydet ve günleri kaldır" }));
    await waitFor(() => expect(terminate).toHaveBeenLastCalledWith(5, "2026-09-30", "", true));
    expect(terminate).toHaveBeenNthCalledWith(1, 5, "2026-09-30", "", false);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("tarih değişince kaldırma onayı düşer; yeni tarih onaysız gönderilir", async () => {
    const user = userEvent.setup();
    const terminate = vi.mocked(personnelApi.terminateEmployee);
    terminate.mockReset();
    terminate
      .mockRejectedValueOnce(httpError(400, { code: "attendance_after_exit", detail: AFTER_EXIT }))
      .mockResolvedValueOnce(employee({ is_active: false, termination_date: "2026-09-29" }));
    const { dialog, date } = await openTerminate(user);
    await user.click(within(dialog).getByRole("button", { name: "İşten ayrıldı" }));
    expect(await within(dialog).findByText(/05–06\.10 Yİ/)).toBeInTheDocument();
    fireEvent.change(date, { target: { value: "2026-09-29" } });
    expect(within(dialog).queryByText(/05–06\.10 Yİ/)).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "İşten ayrıldı" }));
    await waitFor(() => expect(terminate).toHaveBeenLastCalledWith(5, "2026-09-29", "", false));
    expect(terminate).toHaveBeenCalledTimes(2);
  });

  it("onaylı kayıt reddedilince onay düşer; günler yeniden sorulur", async () => {
    const user = userEvent.setup();
    const terminate = vi.mocked(personnelApi.terminateEmployee);
    terminate.mockReset();
    terminate
      .mockRejectedValueOnce(httpError(400, { code: "attendance_after_exit", detail: AFTER_EXIT }))
      .mockRejectedValueOnce(
        httpError(400, {
          code: "approved_attendance_after_exit",
          detail: "Ayşe Demir, çıkış tarihinden (30.09.2026) sonra da onaylı puantajda görünüyor.",
          months: ["2026-10"],
        }),
      )
      .mockResolvedValueOnce(employee({ is_active: false, termination_date: "2026-09-30" }));
    const { dialog } = await openTerminate(user);
    await user.click(within(dialog).getByRole("button", { name: "İşten ayrıldı" }));
    await user.click(
      await within(dialog).findByRole("button", { name: "Kaydet ve günleri kaldır" }),
    );
    expect(await within(dialog).findByText(/onaylı puantajda görünüyor/)).toBeInTheDocument();
    expect(within(dialog).queryByText(/05–06\.10 Yİ/)).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "İşten ayrıldı" }));
    await waitFor(() => expect(terminate).toHaveBeenLastCalledWith(5, "2026-09-30", "", false));
  });

  it("istek sürerken tarih ve not değiştirilemez", async () => {
    const user = userEvent.setup();
    const terminate = vi.mocked(personnelApi.terminateEmployee);
    terminate.mockReset();
    terminate.mockReturnValueOnce(new Promise(() => {}));
    const { dialog, date } = await openTerminate(user);
    await user.click(within(dialog).getByRole("button", { name: "İşten ayrıldı" }));
    await waitFor(() => expect(date).toBeDisabled());
    expect(within(dialog).getByLabelText(/Not/)).toBeDisabled();
  });

  it("onaylı ay için sunucunun bildirdiği aya bağlantı verir, kaydetmez", async () => {
    const user = userEvent.setup();
    const terminate = vi.mocked(personnelApi.terminateEmployee);
    terminate.mockReset();
    terminate.mockRejectedValueOnce(
      httpError(400, {
        code: "approved_attendance_after_exit",
        detail:
          "Ayşe Demir, çıkış tarihinden (20.08.2026) sonra da onaylı puantajda görünüyor: Eylül 2026 (01–30.09).",
        months: ["2026-09"],
      }),
    );
    const { dialog } = await openTerminate(user, "2026-08-20");
    await user.click(within(dialog).getByRole("button", { name: "İşten ayrıldı" }));
    expect(await within(dialog).findByText(/onaylı puantajda görünüyor/)).toBeInTheDocument();
    // Çıkıştan sonraki günün ayı (Ağustos) açık olabilir; bağlantı onaylı aya gider.
    expect(within(dialog).getByRole("link", { name: "Puantajı aç" })).toHaveAttribute(
      "href",
      "/personel/puantaj?ay=2026-09",
    );
    expect(within(dialog).getByRole("button", { name: "İşten ayrıldı" })).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
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

describe("özlük belgeleri", () => {
  beforeEach(() => {
    vi.mocked(personnelApi.uploadEmployeeDocument).mockClear();
    vi.mocked(personnelApi.removeEmployeeDocument).mockClear();
  });

  it("türüne göre gruplar; sona eren sözleşmeyi işaretler", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    vi.mocked(personnelApi.getEmployee).mockResolvedValue(employee());
    vi.mocked(personnelApi.listEmployeeDocuments).mockResolvedValue([
      document(),
      document({
        id: 2,
        kind: "CONTRACT",
        kind_display: "Sözleşme",
        original_name: "sozlesme-2024.pdf",
        period: null,
        valid_from: "2024-03-01",
        valid_until: "2025-02-28",
        download_url: "/api/v1/personnel/documents/2/download/",
      }),
      document({
        id: 3,
        kind: "CONTRACT",
        kind_display: "Sözleşme",
        original_name: "sozlesme-2025.pdf",
        period: null,
        valid_from: "2025-03-01",
        download_url: "/api/v1/personnel/documents/3/download/",
      }),
    ]);
    renderApp("/personel/5");
    const payrolls = await screen.findByTestId("documents-PAYROLL");
    expect(within(payrolls).getByText("Bordro (1)")).toBeInTheDocument();
    expect(within(payrolls).getByText("Eylül 2026")).toBeInTheDocument();
    expect(within(payrolls).getByRole("link", { name: "eylul.pdf" })).toHaveAttribute(
      "href",
      "/api/v1/personnel/documents/1/download/",
    );
    const contracts = screen.getByTestId("documents-CONTRACT");
    expect(within(contracts).getByText("Sözleşme (2)")).toBeInTheDocument();
    expect(within(contracts).getByText("01.03.2024 – 28.02.2025")).toBeInTheDocument();
    expect(within(contracts).getByText("01.03.2025 – belirsiz süreli")).toBeInTheDocument();
    expect(within(contracts).getAllByText("Sona erdi")).toHaveLength(1);
    expect(screen.queryByTestId("documents-ID_COPY")).not.toBeInTheDocument();
  });

  it("bordroyu dönemiyle yükler; dosya ve dönem zorunlu", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    vi.mocked(personnelApi.getEmployee).mockResolvedValue(employee());
    vi.mocked(personnelApi.uploadEmployeeDocument).mockResolvedValue(document());
    renderApp("/personel/5");
    await user.click(await screen.findByRole("button", { name: "Belge ekle" }));
    const dialog = await screen.findByRole("dialog", { name: "Ayşe Demir · belge ekle" });
    await user.click(within(dialog).getByRole("textbox", { name: "Belge türü" }));
    await user.click(await screen.findByRole("option", { name: "Bordro" }));
    await user.click(within(dialog).getByRole("button", { name: "Yükle" }));
    expect(within(dialog).getAllByText("Bu alan zorunlu.")).toHaveLength(2);

    expect(personnelApi.uploadEmployeeDocument).not.toHaveBeenCalled();

    const file = new File(["%PDF-1.4"], "ekim.pdf", { type: "application/pdf" });
    await userEvent.upload(dialog.querySelector("input[type=file]") as HTMLInputElement, file);
    fireEvent.change(within(dialog).getByLabelText(/Dönem/), { target: { value: "2026-10" } });
    await user.type(within(dialog).getByLabelText(/Not/), "Ekim bordrosu");
    await user.click(within(dialog).getByRole("button", { name: "Yükle" }));
    await waitFor(() =>
      expect(personnelApi.uploadEmployeeDocument).toHaveBeenCalledWith(5, {
        kind: "PAYROLL",
        file,
        period: "2026-10",
        note: "Ekim bordrosu",
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("sözleşmede bitiş başlangıçtan önce olamaz", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("admin"));
    vi.mocked(personnelApi.getEmployee).mockResolvedValue(employee());
    vi.mocked(personnelApi.uploadEmployeeDocument).mockResolvedValue(document());
    renderApp("/personel/5");
    await user.click(await screen.findByRole("button", { name: "Belge ekle" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("textbox", { name: "Belge türü" }));
    await user.click(await screen.findByRole("option", { name: "Sözleşme" }));
    const file = new File(["%PDF-1.4"], "sozlesme.pdf", { type: "application/pdf" });
    await userEvent.upload(dialog.querySelector("input[type=file]") as HTMLInputElement, file);
    await user.type(within(dialog).getByLabelText(/Başlangıç tarihi/), "2025-03-01");
    await user.type(within(dialog).getByLabelText(/Bitiş tarihi/), "2025-02-28");
    await user.click(within(dialog).getByRole("button", { name: "Yükle" }));
    expect(within(dialog).getByText("Bitiş tarihi başlangıçtan önce olamaz.")).toBeInTheDocument();
    expect(personnelApi.uploadEmployeeDocument).not.toHaveBeenCalled();

    await user.clear(within(dialog).getByLabelText(/Bitiş tarihi/));
    await user.click(within(dialog).getByRole("button", { name: "Yükle" }));
    await waitFor(() =>
      expect(personnelApi.uploadEmployeeDocument).toHaveBeenCalledWith(5, {
        kind: "CONTRACT",
        file,
        valid_from: "2025-03-01",
      }),
    );
  });

  it("belgeyi nedeniyle kaldırır", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("yonetim"));
    vi.mocked(personnelApi.getEmployee).mockResolvedValue(employee());
    vi.mocked(personnelApi.listEmployeeDocuments).mockResolvedValue([document()]);
    vi.mocked(personnelApi.removeEmployeeDocument).mockResolvedValue(document());
    renderApp("/personel/5");
    await user.click(await screen.findByRole("button", { name: "Kaldır: eylul.pdf" }));
    const dialog = await screen.findByRole("dialog", { name: "Belgeyi kaldır" });
    expect(within(dialog).getByText("Bordro · eylul.pdf")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Kaldır" }));
    expect(within(dialog).getByText("Bu alan zorunlu.")).toBeInTheDocument();
    expect(personnelApi.removeEmployeeDocument).not.toHaveBeenCalled();

    await user.type(within(dialog).getByLabelText(/Kaldırma nedeni/), "  Yanlış ay ");
    const loads = vi.mocked(personnelApi.listEmployeeDocuments).mock.calls.length;
    await user.click(within(dialog).getByRole("button", { name: "Kaldır" }));
    await waitFor(() =>
      expect(personnelApi.removeEmployeeDocument).toHaveBeenCalledWith(1, "Yanlış ay"),
    );
    await waitFor(() =>
      expect(vi.mocked(personnelApi.listEmployeeDocuments).mock.calls.length).toBeGreaterThan(
        loads,
      ),
    );
  });
});
