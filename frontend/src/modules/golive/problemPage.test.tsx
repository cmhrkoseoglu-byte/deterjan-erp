import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as attachmentsApi from "../../api/attachments";
import * as authApi from "../../api/auth";
import * as goliveApi from "../../api/golive";
import type { ProblemReport } from "../../api/golive";
import * as workflowApi from "../../api/workflow";
import { page, userWith } from "../../test/fixtures";
import { renderApp } from "../../test/render";

vi.mock("../../api/auth");
vi.mock("../../api/attachments", async (importOriginal) => ({
  ...(await importOriginal<typeof attachmentsApi>()),
  listAttachments: vi.fn(),
}));
vi.mock("../../api/golive", async (importOriginal) => ({
  ...(await importOriginal<typeof goliveApi>()),
  getProblem: vi.fn(),
}));
vi.mock("../../api/workflow");

function report(pageUrl: string): ProblemReport {
  return {
    id: 3,
    number: "SB-2026-00003",
    description: "Ekran açılmıyor",
    page_url: pageUrl,
    page_title: "Stok",
    user_agent: "Deneme",
    screen: "1280x800",
    has_screenshot: false,
    reporter: "Demo Depo",
    created_at: "2026-11-04T09:00:00+03:00",
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(authApi.fetchCsrf).mockResolvedValue();
  vi.mocked(authApi.fetchMe).mockResolvedValue(userWith("admin"));
  vi.mocked(attachmentsApi.listAttachments).mockResolvedValue([]);
  vi.mocked(workflowApi.fetchTasks).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchNotifications).mockResolvedValue(page([]));
  vi.mocked(workflowApi.fetchUnreadCount).mockResolvedValue(0);
  vi.mocked(workflowApi.fetchComments).mockResolvedValue([]);
  vi.mocked(workflowApi.fetchRecordHistory).mockResolvedValue([]);
  vi.mocked(workflowApi.fetchMentionableUsers).mockResolvedValue([]);
});

// Bildirimdeki sayfa adresi admin ekranında bağlantıdır; başka siteye çözülen adres (eski kayıtlar
// dahil) bağlantı olmaz, düz yazı kalır.
describe("sorun bildirimi sayfası", () => {
  it("uygulama içi sayfa adresini bağlantı olarak gösterir", async () => {
    vi.mocked(goliveApi.getProblem).mockResolvedValue(report("/depo/stok?durum=serbest"));
    renderApp("/gecis/sorunlar/3");
    const link = await screen.findByRole("link", { name: "/depo/stok?durum=serbest" });
    expect(link).toHaveAttribute("href", "/depo/stok?durum=serbest");
  });

  it.each(["//kotu.example", "/..//kotu.example", "/%2e%2e//kotu.example"])(
    "başka siteye çözülen %j adresini bağlantı yapmaz",
    async (pageUrl) => {
      vi.mocked(goliveApi.getProblem).mockResolvedValue(report(pageUrl));
      renderApp("/gecis/sorunlar/3");
      expect(await screen.findByText(pageUrl, { exact: false })).toBeInTheDocument();
      expect(screen.queryByRole("link", { name: pageUrl })).not.toBeInTheDocument();
      expect(document.querySelector('a[href*="kotu.example"]')).toBeNull();
    },
  );
});
