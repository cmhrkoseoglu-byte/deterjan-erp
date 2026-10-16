// Arayüzdeki beklenmeyen hatalar sunucu günlüğüne gönderilir (POST /ops/client-errors/).
// Gönderim "ateşle ve unut"tur: yalnızca oturum açıkken, aynı mesaj dakikada bir kez, hiçbir
// durumda hata fırlatmaz.
import axios from "axios";
import { postClientError } from "../api/ops";

const DEDUPE_MS = 60_000;
const MAX_MESSAGE = 1000;
const MAX_STACK = 8000;

let enabled = false;
let installed = false;
const recent = new Map<string, number>();

/** AuthProvider oturum durumuna göre açar/kapatır. */
export function setClientErrorReporting(value: boolean) {
  enabled = value;
}

function describe(error: unknown): { message: string; stack: string } {
  if (error instanceof Error) {
    return { message: error.message || error.name, stack: error.stack ?? "" };
  }
  if (typeof error === "string") return { message: error, stack: "" };
  try {
    return { message: JSON.stringify(error) ?? String(error), stack: "" };
  } catch {
    return { message: String(error), stack: "" };
  }
}

/** Hatayı bildirir; oturum yoksa ya da aynı mesaj son bir dakikada gönderildiyse bir şey yapmaz. */
export function reportClientError(error: unknown, now: number = Date.now()): void {
  try {
    if (!enabled) return;
    // Yanıt dönen API hataları sunucuda zaten bilinir (ve ekranda gösterilir).
    if (axios.isAxiosError(error) && error.response) return;
    const { message, stack } = describe(error);
    if (!message) return;
    const last = recent.get(message);
    if (last !== undefined && now - last < DEDUPE_MS) return;
    recent.set(message, now);
    for (const [key, at] of recent) if (now - at >= DEDUPE_MS) recent.delete(key);
    postClientError({
      message: message.slice(0, MAX_MESSAGE),
      stack: stack.slice(0, MAX_STACK),
      url: window.location.pathname,
    }).catch(() => undefined);
  } catch {
    // Hata bildirimi asla yeni bir hata üretmez.
  }
}

/** window 'error' ve 'unhandledrejection' dinleyicilerini bir kez bağlar. */
export function installClientErrorHandlers() {
  if (installed || typeof window === "undefined") return;
  installed = true;
  window.addEventListener("error", (event: ErrorEvent) => {
    reportClientError(event.error ?? event.message);
  });
  window.addEventListener("unhandledrejection", (event: PromiseRejectionEvent) => {
    reportClientError(event.reason);
  });
}

/** Yalnızca testler için. */
export function resetClientErrorReporting() {
  enabled = false;
  recent.clear();
}
