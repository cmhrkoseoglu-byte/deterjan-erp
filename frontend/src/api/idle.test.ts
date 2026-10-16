import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, isOtpSetupRequired, isSessionExpired } from "./client";
import {
  IDLE_HEADER,
  idleSeconds,
  markActivity,
  resetIdleTracking,
  startIdleTracking,
} from "./idle";
import { httpError } from "../test/fixtures";

const defaultAdapter = api.defaults.adapter;

describe("hareketsizlik izleyici", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-16T09:00:00Z"));
    resetIdleTracking();
  });

  afterEach(() => {
    vi.useRealTimers();
    api.defaults.adapter = defaultAdapter;
  });

  it("son kullanıcı etkinliğinden bu yana geçen saniyeyi verir", () => {
    vi.advanceTimersByTime(42_500);
    expect(idleSeconds()).toBe(42);
    markActivity();
    expect(idleSeconds()).toBe(0);
  });

  it("kullanıcı etkinliği (tuş, dokunma) sayacı sıfırlar", () => {
    startIdleTracking();
    vi.advanceTimersByTime(90_000);
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "a" }));
    expect(idleSeconds()).toBe(0);
    vi.advanceTimersByTime(5_000);
    window.dispatchEvent(new Event("pointerdown"));
    expect(idleSeconds()).toBe(0);
  });

  it("başka sekmedeki etkinlik (localStorage) de sayılır", () => {
    vi.advanceTimersByTime(600_000);
    window.localStorage.setItem("erp:lastActivity", String(Date.now() - 3_000));
    expect(idleSeconds()).toBe(3);
  });

  it("her API isteğine X-ERP-Idle-Seconds başlığını ekler", async () => {
    const seen: string[] = [];
    api.defaults.adapter = async (config) => {
      seen.push(String(config.headers.get(IDLE_HEADER)));
      return { data: {}, status: 200, statusText: "", headers: {}, config };
    };
    vi.advanceTimersByTime(125_000);
    await api.get("/workflow/notifications/unread-count/");
    markActivity();
    await api.post("/ornek/", {});
    expect(IDLE_HEADER).toBe("X-ERP-Idle-Seconds");
    expect(seen).toEqual(["125", "0"]);
  });

  it("oturum hata kodlarını ayırt eder", () => {
    expect(isSessionExpired(httpError(401, { code: "session_expired" }))).toBe(true);
    expect(isSessionExpired(httpError(401, { code: "not_authenticated" }))).toBe(false);
    expect(isOtpSetupRequired(httpError(403, { code: "otp_setup_required" }))).toBe(true);
    expect(isOtpSetupRequired(httpError(403, { code: "permission_denied" }))).toBe(false);
  });
});
