import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as opsApi from "../api/ops";
import { httpError } from "../test/fixtures";
import {
  reportClientError,
  resetClientErrorReporting,
  setClientErrorReporting,
} from "./clientErrors";

vi.mock("../api/ops");

describe("arayüz hata bildirimi", () => {
  beforeEach(() => {
    vi.mocked(opsApi.postClientError).mockReset().mockResolvedValue();
    resetClientErrorReporting();
  });
  afterEach(() => resetClientErrorReporting());

  it("oturum yokken göndermez", () => {
    reportClientError(new Error("patladı"));
    expect(opsApi.postClientError).not.toHaveBeenCalled();
  });

  it("mesaj, yığın ve adresi gönderir; aynı mesajı dakikada bir kez", () => {
    setClientErrorReporting(true);
    const now = Date.now();
    reportClientError(new Error("patladı"), now);
    reportClientError(new Error("patladı"), now + 30_000);
    reportClientError(new Error("başka"), now + 30_000);
    reportClientError(new Error("patladı"), now + 61_000);
    expect(opsApi.postClientError).toHaveBeenCalledTimes(3);
    expect(opsApi.postClientError).toHaveBeenNthCalledWith(1, {
      message: "patladı",
      stack: expect.any(String),
      url: window.location.pathname,
    });
  });

  it("yanıt dönen API hatalarını göndermez, gönderim hatası fırlatmaz", async () => {
    setClientErrorReporting(true);
    reportClientError(httpError(400, { code: "x" }));
    expect(opsApi.postClientError).not.toHaveBeenCalled();
    vi.mocked(opsApi.postClientError).mockRejectedValue(new Error("ağ yok"));
    expect(() => reportClientError("metin hata")).not.toThrow();
    await Promise.resolve();
  });
});
