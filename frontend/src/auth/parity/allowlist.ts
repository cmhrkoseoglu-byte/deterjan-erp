/**
 * Ön yüz eşlik anlık görüntüsünden bilerek ayrılan kararlar (plan §5.5 "İzin listesi").
 *
 * Her kayıt bir farkı planın bir maddesine bağlar (§8'deki ilk gün değişiklikleri). Kaydın `step`
 * alanı maddenin açıldığı adımdır (plan §10'daki madde → adım eşlemesi; ön yüzün 1, 2 ve 3.
 * maddeleri 8. adımda açılır); kayıt `CURRENT_STEP` o adıma gelince geçerli olur, yani her adım
 * yalnız kendi maddelerini açar. Buraya plan dışı bir kayıt eklemek sahibin onayını ve DECISIONS
 * kaydını ister. Backend'deki karşılığı: `backend/apps/core/tests/access_contract/allowlist.py`.
 *
 * - Desenlerde yalnız `*` (herhangi bir metin) ve `?` (tek karakter) jokerdir; köşeli parantez
 *   dahil öteki karakterler olduğu gibi eşleşir.
 * - `required` (varsayılan `true`) kayıt, karşılaştırmada en az bir farkla eşleşmelidir. Onaylı bir
 *   değişiklik sonradan geri alınırsa (değer dondurulmuş eski değere dönerse) test bunu yakalar.
 */

/** Durum anlık görüntüde (ya da bugünkü kodda) yok. */
export const MISSING = "<yok>";
/** Eski ya da yeni değer ne olursa olsun. */
export const ANY = "<her>";

/** Uygulanan adım (plan §10). Her adım bu sayıyı artırır ve kendi kayıtlarını ekler. */
export const CURRENT_STEP = 1;

export interface Allowed {
  /** Planın maddesi, ör. "§8 madde 1". */
  item: string;
  /** Anlık görüntünün bölümü, ör. "menu", "routes". */
  section: string;
  /** Durum deseni: `*` herhangi bir metin, `?` tek karakter (ör. "/isg/*"). */
  case: string;
  /** Persona deseni; verilmezse bütün personalar. */
  persona?: string;
  /** Beklenen eski değer; verilmezse `ANY`. */
  old?: unknown;
  /** Beklenen yeni değer; verilmezse `ANY`. */
  new?: unknown;
  /** Maddenin açıldığı adım (plan §10); verilmezse 1. */
  step?: number;
  /** Kayıt en az bir farkla eşleşmeli mi; verilmezse `true`. */
  required?: boolean;
}

export const ALLOWED: readonly Allowed[] = [];

function globToRegExp(pattern: string): RegExp {
  const body = pattern
    .split("")
    .map((char) => {
      if (char === "*") return ".*";
      if (char === "?") return ".";
      return char.replace(/[.+^${}()|[\]\\]/g, "\\$&");
    })
    .join("");
  return new RegExp(`^${body}$`, "s");
}

/** Desen eşleşmesi: yalnız `*` ve `?` jokerdir (backend'deki `allowlist.matches` ile aynı). */
export function matches(pattern: string, value: string): boolean {
  return globToRegExp(pattern).test(value);
}

/** İki JSON değerinin eşitliği (nesnelerde anahtar sırası önemsiz). */
export function sameValue(a: unknown, b: unknown): boolean {
  return canonical(a) === canonical(b);
}

export function canonical(value: unknown): string {
  return JSON.stringify(value, (_key, item: unknown) =>
    item && typeof item === "object" && !Array.isArray(item)
      ? Object.fromEntries(Object.entries(item).sort(([x], [y]) => (x < y ? -1 : x > y ? 1 : 0)))
      : item,
  );
}

function valueMatches(expected: unknown, actual: unknown): boolean {
  return expected === undefined || expected === ANY || sameValue(expected, actual);
}

/** Kayıt bu adımda geçerli mi? */
export function isActive(entry: Allowed, step: number = CURRENT_STEP): boolean {
  return (entry.step ?? 1) <= step;
}

/** Farka izin veren kayıt (yoksa `undefined`). */
export function permitted(
  section: string,
  caseName: string,
  persona: string,
  oldValue: unknown,
  newValue: unknown,
  allowed: readonly Allowed[] = ALLOWED,
  step: number = CURRENT_STEP,
): Allowed | undefined {
  return allowed.find(
    (entry) =>
      isActive(entry, step) &&
      entry.section === section &&
      matches(entry.case, caseName) &&
      matches(entry.persona ?? "*", persona) &&
      valueMatches(entry.old, oldValue) &&
      valueMatches(entry.new, newValue),
  );
}

/** Bölümün geçerli ve eşleşmesi gereken kayıtları. */
export function requiredFor(
  section: string,
  allowed: readonly Allowed[] = ALLOWED,
  step: number = CURRENT_STEP,
): Allowed[] {
  return allowed.filter(
    (entry) => entry.section === section && isActive(entry, step) && (entry.required ?? true),
  );
}
