// Kullanıcı etkinliği izleyici (Faz 5 oturum güvenliği).
//
// Sunucu oturumu, son KULLANICI etkinliğinden bu yana `idle_timeout_seconds` geçince kapatır. SPA
// her API isteğinde `X-ERP-Idle-Seconds` başlığıyla kullanıcının kaç saniyedir ekrana dokunmadığını
// bildirir; böylece arka planda kendiliğinden yenilenen ekranlar (bildirim zili, panolar) oturumu
// açık tutmaz. Aynı tarayıcıdaki sekmeler son etkinlik zamanını `localStorage` üzerinden paylaşır:
// bir sekmede çalışan kullanıcının oturumu, arka plandaki diğer sekme yüzünden kapanmaz.

export const IDLE_HEADER = "X-ERP-Idle-Seconds";
const STORAGE_KEY = "erp:lastActivity";
const ACTIVITY_EVENTS = ["pointerdown", "keydown", "touchstart", "wheel"] as const;
/** Etkinlik dinleyicisi en çok bu sıklıkla zamanı günceller (ms). */
const THROTTLE_MS = 1000;

let lastActivity = Date.now();
let lastRecorded = 0;
let tracking = false;

function readShared(): number {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const value = raw ? Number(raw) : NaN;
    return Number.isFinite(value) ? value : 0;
  } catch {
    return 0;
  }
}

function writeShared(value: number) {
  try {
    window.localStorage.setItem(STORAGE_KEY, String(value));
  } catch {
    // Gizli pencere ya da kapalı depolama: yalnızca bu sekmenin zamanı kullanılır.
  }
}

/** Kullanıcı etkinliğini kaydeder (giriş, dokunma, tuş). */
export function markActivity(now: number = Date.now()) {
  lastActivity = now;
  if (now - lastRecorded >= THROTTLE_MS) {
    lastRecorded = now;
    writeShared(now);
  }
}

function onActivity() {
  const now = Date.now();
  if (now - lastActivity < THROTTLE_MS) return;
  markActivity(now);
}

/** Etkinlik dinleyicilerini bir kez bağlar (tekrar çağrılırsa bir şey yapmaz). */
export function startIdleTracking() {
  if (tracking || typeof window === "undefined") return;
  tracking = true;
  for (const name of ACTIVITY_EVENTS) {
    window.addEventListener(name, onActivity, { passive: true, capture: true });
  }
}

/** Son kullanıcı etkinliğinden (bu ya da başka sekme) bu yana geçen tam saniye. */
export function idleSeconds(now: number = Date.now()): number {
  const last = Math.max(lastActivity, readShared());
  return Math.max(0, Math.floor((now - last) / 1000));
}

/** Yalnızca testler için: izleyiciyi başlangıç durumuna döndürür. */
export function resetIdleTracking(now: number = Date.now()) {
  lastActivity = now;
  lastRecorded = 0;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // yok say
  }
}
