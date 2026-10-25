import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { act } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../api/auth";
import type { CurrentUser } from "../api/types";
import * as workflowApi from "../api/workflow";
import { FakeWebSocket } from "../test/fakeWebSocket";
import { renderApp, renderWithProviders } from "../test/render";
import { makeComment, makeNotification, makeTask, page } from "../test/workflowFixtures";
import { RecordPanel } from "./RecordPanel";
import { RECORD_ROUTES } from "./recordLinks";

vi.mock("../api/auth");
vi.mock("../api/workflow");

const depoUser: CurrentUser = {
  id: 7,
  username: "depo1",
  full_name: "Ayşe Yılmaz",
  email: "",
  roles: ["depo"],
  is_superuser: false,
  otp_enabled: false,
  password_change_required: false,
  otp_setup_required: false,
  field_device: false,
  idle_timeout_seconds: 3600,
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(authApi.fetchMe).mockResolvedValue(depoUser);
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
});

describe("Görevlerim", () => {
  it("açık görevleri bekleme süresi ve rolüyle listeler", async () => {
    vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([makeTask()]));
    renderApp("/");

    const card = await screen.findByTestId("task-card");
    expect(within(card).getByText("Malzeme hazırla: UE-2026-00001")).toBeInTheDocument();
    expect(within(card).getByText("Depo")).toBeInTheDocument();
    expect(within(card).getByText("2 sa bekliyor")).toBeInTheDocument();
    expect(workflowApi.fetchTasks).toHaveBeenCalledWith(
      expect.objectContaining({ mine: true, open: true, page: 1 }),
    );
  });

  it("görevi üstlenir ve listeyi tazeler", async () => {
    vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([makeTask()]));
    vi.mocked(workflowApi.claimTask).mockResolvedValue(makeTask({ status: "IN_PROGRESS" }));
    renderApp("/");

    await userEvent.click(await screen.findByRole("button", { name: "Üstlen" }));

    expect(workflowApi.claimTask).toHaveBeenCalledWith(1);
    await waitFor(() => expect(workflowApi.fetchTasks).toHaveBeenCalledTimes(2));
  });

  it("görevi notla tamamlar", async () => {
    vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([makeTask()]));
    vi.mocked(workflowApi.completeTask).mockResolvedValue(makeTask({ status: "DONE" }));
    renderApp("/");

    await userEvent.click(await screen.findByRole("button", { name: "Tamamla" }));
    await userEvent.type(await screen.findByLabelText("Not (isteğe bağlı)"), "Hazır");
    const dialog = screen.getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Tamamla" }));

    expect(workflowApi.completeTask).toHaveBeenCalledWith(1, "Hazır");
  });

  it("yetkisi olmayan görevde düğme göstermez, kaydı tanımlıysa bağlantı verir", async () => {
    RECORD_ROUTES["production.productionorder"] = (id) => `/uretim/emirler/${id}`;
    vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([makeTask({ can_act: false })]));
    renderApp("/");

    const link = await screen.findByRole("link", { name: "Kayda git" });
    expect(link).toHaveAttribute("href", "/uretim/emirler/5");
    expect(screen.queryByRole("button", { name: "Üstlen" })).not.toBeInTheDocument();
    delete RECORD_ROUTES["production.productionorder"];
  });

  it("görev yoksa boş mesaj gösterir", async () => {
    renderApp("/");
    expect(await screen.findByText("Açık göreviniz yok.")).toBeInTheDocument();
  });
});

describe("bildirim zili", () => {
  it("okunmamış sayısını gösterir, listeyi açar ve tümünü okundu işaretler", async () => {
    vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(3);
    vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([makeNotification()]));
    vi.mocked(workflowApi.markNotificationsRead).mockResolvedValue(3);
    renderApp("/");

    const bell = await screen.findByRole("button", { name: "3 okunmamış bildirim" });
    await userEvent.click(bell);
    expect(await screen.findByText("Lot reddedildi: H-261015-001")).toBeInTheDocument();
    expect(screen.getByText("Uyarı")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Tümünü okundu işaretle" }));
    expect(workflowApi.markNotificationsRead).toHaveBeenCalledWith(undefined);
  });

  it("WebSocket'ten gelen bildirimle sayacı sayfa yenilemeden günceller", async () => {
    renderApp("/");
    await screen.findByRole("button", { name: "Bildirimler" });
    const socket = FakeWebSocket.latest();
    expect(socket.url).toMatch(/\/ws\/notifications\/$/);

    vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(1);
    vi.mocked(workflowApi.fetchTasks).mockResolvedValue(
      page([makeTask({ title: "Yeni görev geldi" })]),
    );
    act(() => socket.open());
    act(() =>
      socket.receive({
        type: "notification.created",
        id: 9,
        title: "Yeni görev: Say",
        body: "",
        level: "INFO",
      }),
    );
    act(() => socket.receive({ type: "task.changed", id: 9, status: "OPEN" }));

    expect(await screen.findByRole("button", { name: "1 okunmamış bildirim" })).toBeInTheDocument();
    expect(await screen.findByText("Yeni görev geldi")).toBeInTheDocument();
  });

  it("bağlantı yokken çevrimdışı işaretini gösterir", async () => {
    renderApp("/");
    await userEvent.click(await screen.findByRole("button", { name: "Bildirimler" }));
    expect(
      await screen.findByLabelText("Anlık bağlantı yok; bildirimler 30 sn'de bir yenileniyor."),
    ).toBeInTheDocument();
  });
});

describe("bildirimler sayfası", () => {
  it("okunmamış filtresiyle listeler", async () => {
    vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([makeNotification()]));
    renderApp("/bildirimler");

    expect(await screen.findByText("Lot reddedildi: H-261015-001")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Okunmamış"));
    await waitFor(() =>
      expect(workflowApi.fetchNotifications).toHaveBeenCalledWith(
        expect.objectContaining({ unread: true }),
      ),
    );
  });
});

describe("kayıt yorum paneli", () => {
  it("yorumları bahsetme vurgusuyla gösterir", async () => {
    vi.mocked(workflowApi.fetchComments).mockResolvedValue([makeComment()]);
    renderWithProviders(<RecordPanel contentType="inventory.lot" objectId={5} />);

    expect(await screen.findByText("@mehmet")).toBeInTheDocument();
    expect(screen.getByText("Ayşe Yılmaz")).toBeInTheDocument();
    expect(workflowApi.fetchComments).toHaveBeenCalledWith({
      contentType: "inventory.lot",
      objectId: 5,
    });
  });

  it("@ yazınca kişi önerir, seçileni ekler ve yorumu gönderir", async () => {
    vi.mocked(workflowApi.fetchComments).mockResolvedValue([]);
    vi.mocked(workflowApi.fetchMentionableUsers).mockResolvedValue([
      { id: 3, username: "mehmet", full_name: "Mehmet Kaya" },
    ]);
    vi.mocked(workflowApi.addComment).mockResolvedValue(makeComment());
    renderWithProviders(<RecordPanel contentType="inventory.lot" objectId={5} />);

    const input = await screen.findByRole("textbox");
    await userEvent.type(input, "Merhaba @meh");
    await userEvent.click(await screen.findByRole("option", { name: /@mehmet/ }));
    expect(input).toHaveValue("Merhaba @mehmet ");
    // Öneriler yalnızca bu kaydı görebilenlerden gelir.
    expect(workflowApi.fetchMentionableUsers).toHaveBeenCalledWith("meh", {
      contentType: "inventory.lot",
      objectId: 5,
    });

    await userEvent.type(input, "bakar mısın?");
    await userEvent.click(screen.getByRole("button", { name: "Gönder" }));
    expect(workflowApi.addComment).toHaveBeenCalledWith(
      { contentType: "inventory.lot", objectId: 5 },
      "Merhaba @mehmet bakar mısın?",
    );
    await waitFor(() => expect(input).toHaveValue(""));
  });

  it("kendi yorumunu düzenler", async () => {
    vi.mocked(workflowApi.fetchComments).mockResolvedValue([
      makeComment({ body: "eski", mentions: [] }),
    ]);
    vi.mocked(workflowApi.editComment).mockResolvedValue(makeComment({ body: "yeni" }));
    renderWithProviders(<RecordPanel contentType="inventory.lot" objectId={5} />);

    await userEvent.click(await screen.findByRole("button", { name: "Düzenle" }));
    const editor = screen.getAllByRole("textbox")[0];
    await userEvent.clear(editor);
    await userEvent.type(editor, "yeni");
    await userEvent.click(screen.getByRole("button", { name: "Kaydet" }));
    expect(workflowApi.editComment).toHaveBeenCalledWith(1, "yeni");
  });

  it("geçmiş sekmesinde denetim kayıtlarını gösterir", async () => {
    vi.mocked(workflowApi.fetchComments).mockResolvedValue([]);
    vi.mocked(workflowApi.fetchRecordHistory).mockResolvedValue([
      {
        id: 1,
        timestamp: new Date().toISOString(),
        actor: 2,
        actor_name: "Ayşe Yılmaz",
        action: "status_change",
        action_label: "Durum değişikliği",
        changes: { status: ["QUARANTINE", "RELEASED"] },
        note: "",
      },
    ]);
    renderWithProviders(<RecordPanel contentType="inventory.lot" objectId={5} />);

    await userEvent.click(await screen.findByRole("tab", { name: "Geçmiş" }));
    expect(await screen.findByText("Durum değişikliği")).toBeInTheDocument();
    expect(screen.getByText("status: QUARANTINE → RELEASED")).toBeInTheDocument();
  });
});
