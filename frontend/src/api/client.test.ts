import { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from "axios";
import { afterEach, describe, expect, it } from "vitest";
import { api, getErrorMessage } from "./client";

function reject(config: InternalAxiosRequestConfig, status: number, data: unknown) {
  return Promise.reject(
    new AxiosError("hata", String(status), config, null, {
      status,
      statusText: "",
      headers: {},
      config,
      data,
    }),
  );
}

const defaultAdapter = api.defaults.adapter;

describe("api istemcisi", () => {
  afterEach(() => {
    api.defaults.adapter = defaultAdapter;
  });

  it("403 csrf_failed alınca CSRF çerezini yenileyip isteği bir kez tekrarlar", async () => {
    const calls: string[] = [];
    let attempts = 0;
    api.defaults.adapter = async (config) => {
      calls.push(`${config.method} ${config.url}`);
      if (config.url === "/auth/csrf/")
        return { data: "", status: 204, statusText: "", headers: {}, config };
      attempts += 1;
      if (attempts === 1) return reject(config, 403, { code: "csrf_failed", detail: "CSRF" });
      return { data: { ok: true }, status: 200, statusText: "", headers: {}, config };
    };
    const response = await api.post("/ornek/", {});
    expect(response.data).toEqual({ ok: true });
    expect(calls).toEqual(["post /ornek/", "get /auth/csrf/", "post /ornek/"]);
  });

  it("ikinci csrf_failed hatasında tekrar denemez", async () => {
    let posts = 0;
    api.defaults.adapter = async (config) => {
      if (config.url === "/auth/csrf/")
        return { data: "", status: 204, statusText: "", headers: {}, config };
      posts += 1;
      return reject(config, 403, {
        code: "csrf_failed",
        detail: "CSRF doğrulaması başarısız.",
      });
    };
    const request = api.post("/ornek/", {});
    await expect(request).rejects.toBeInstanceOf(AxiosError);
    expect(posts).toBe(2);
  });

  it("backend hata mesajını (detail) döner", () => {
    const config = { headers: new AxiosHeaders() };
    const error = new AxiosError("hata", "429", config, null, {
      status: 429,
      statusText: "",
      headers: {},
      config,
      data: { code: "throttled", detail: "Çok fazla deneme." },
    });
    expect(getErrorMessage(error)).toBe("Çok fazla deneme.");
  });
});
