/**
 * Ön yüz eşlik anlık görüntüsünden bilerek ayrılan kararlar (plan §5.5 "İzin listesi").
 *
 * Her kayıt bir farkı planın bir maddesine bağlar (§8'deki ilk gün değişiklikleri ya da planın
 * eklediği ekranlar). Liste 1. adımda bütün maddeleriyle yazıldı (plan §5.5). Kaydın `step` alanı
 * maddenin açıldığı adımdır (plan §10'daki madde → adım eşlemesi; ön yüzün 1, 2 ve 3. maddeleri 8.
 * adımda açılır); kayıt `CURRENT_STEP` o adıma gelince geçerli olur, yani her adım yalnız kendi
 * maddelerini açar. `until` verilirse kayıt o adımdan sonra geçersizdir. Kayıtlar hücre hücre
 * yazılır; yeni değeri plan sabitlemiyorsa verilmez. Buraya plan dışı bir kayıt eklemek ya da bir
 * kaydı genişletmek sahibin onayını ve DECISIONS kaydını ister. `allowlist.test.ts` her kaydın
 * planın bir maddesine ve dondurulmuş bir hücreye bağlı olduğunu bugünden denetler. Backend'deki
 * karşılığı: `backend/apps/core/tests/access_contract/allowlist.py`.
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
  /** Kaydın geçerli olduğu son adım; verilmezse sınırsız. */
  until?: number;
  /** Kayıt en az bir farkla eşleşmeli mi; verilmezse `true`. */
  required?: boolean;
}

/** Her (durum, persona) hücresi için ayrı bir kayıt: her hücre ayrı ayrı gereklidir. */
function cells(
  base: Omit<Allowed, "case" | "persona">,
  byCase: Readonly<Record<string, readonly string[]>>,
): Allowed[] {
  return Object.entries(byCase).flatMap(([name, personas]) =>
    personas.map((persona) => ({ ...base, case: name, persona })),
  );
}

export const ALLOWED: readonly Allowed[] = [
  // 8. adım — Rolsüz kullanıcı "İSG ve çevre" ile "Panolar ve raporlar" menülerini ve sayfalarını
  // (İndirmeler hariç) ve Görevlerim'deki "Arıza bildir" düğmesini görmez; üst bandı nötr olur.
  ...cells(
    { item: "§8 madde 1", section: "dashboardLinks", step: 8, old: true, new: false },
    { "approvals → /isg/olaylar": ["no_role"], "attention → /isg/olaylar": ["no_role"] },
  ),
  ...cells(
    { item: "§8 madde 1", section: "menu", step: 8, old: true, new: false },
    { hse: ["no_role"], reporting: ["no_role"] },
  ),
  ...cells(
    { item: "§8 madde 1", section: "pageDefaults", step: 8, old: "/isg/olaylar", new: "forbidden" },
    { "/isg": ["no_role"] },
  ),
  ...cells(
    { item: "§8 madde 1", section: "pageDefaults", step: 8, old: "/raporlar/panolar" },
    { "/raporlar": ["no_role"] },
  ),
  ...cells(
    {
      item: "§8 madde 1",
      section: "pageTabs",
      step: 8,
      old: ["/isg/olaylar", "/isg/tehlike", "/isg/ifadeler"],
      new: "forbidden",
    },
    { "/isg": ["no_role"] },
  ),
  ...cells({ item: "§8 madde 1", section: "pageTabs", step: 8 }, { "/raporlar": ["no_role"] }),
  ...cells(
    { item: "§8 madde 1", section: "recordLinks", step: 8, old: "open", new: "forbidden" },
    { "hse.incident": ["no_role"] },
  ),
  ...cells(
    { item: "§8 madde 1", section: "recordLinks", step: 8, old: "redirect /isg", new: "forbidden" },
    { "hse.safetydatasheet": ["no_role"], "hse.wasterecord": ["no_role"] },
  ),
  ...cells(
    { item: "§8 madde 1", section: "reportButtons", step: 8, old: ["breakdown"], new: [] },
    { "/gorevlerim": ["no_role"] },
  ),
  ...cells(
    { item: "§8 madde 1", section: "reportButtons", step: 8, old: ["incident"], new: "forbidden" },
    { "/isg": ["no_role"] },
  ),
  ...cells(
    { item: "§8 madde 1", section: "routes", step: 8, old: "open", new: "forbidden" },
    { "/isg/:tab?": ["no_role"], "/isg/olaylar/:incidentId": ["no_role"] },
  ),
  ...cells(
    { item: "§8 madde 1", section: "routes", step: 8, old: "open", required: false },
    { "/raporlar/:tab?": ["no_role"] },
  ),
  ...cells(
    { item: "§8 madde 1", section: "shell", step: 8, old: "admin" },
    { roleBar: ["no_role"] },
  ),

  // 8. adım — Yeni üretim ve dolum emri sayfaları yalnız emir açabilenlere, satın alma sipariş
  // ayrıntısı yalnız siparişleri görebilenlere açılır.
  ...cells(
    { item: "§8 madde 3", section: "newPages", step: 8, old: "open", new: "forbidden" },
    {
      "/uretim/emirler/yeni": ["inactive", "yonetim", "depo", "uretim", "depo+sevkiyat"],
      "/dolum/emirler/yeni": ["inactive", "yonetim", "depo", "dolum", "depo+sevkiyat"],
      "/satin-alma/siparisler/yeni": ["planlama", "uretim"],
    },
  ),
  ...cells(
    { item: "§8 madde 3", section: "recordLinks", step: 8, old: "open", new: "forbidden" },
    { "purchasing.purchaseorder": ["planlama", "uretim"] },
  ),
  ...cells(
    { item: "§8 madde 3", section: "routes", step: 8, old: "open", new: "forbidden" },
    { "/satin-alma/siparisler/:orderId": ["planlama", "uretim"] },
  ),

  // 9. adım — Sistem sayfasına Rol yetkileri sekmesi eklenir (plan §6.2).
  ...cells(
    {
      item: "yeni sayfa: Sistem > Rol yetkileri sekmesi (plan §6.2)",
      section: "pageTabs",
      step: 9,
    },
    { "/sistem": ["admin", "superuser"] },
  ),

  // 9. adım — Yeni ekran: Sistem > Kullanıcılar > Yetkiler (yalnız admin; plan §6.1).
  ...cells(
    {
      item: "§8 madde 13: Sistem > Kullanıcılar > Yetkiler (plan §6.1)",
      section: "routes",
      step: 9,
      old: MISSING,
      new: "login",
    },
    { "/sistem/kullanicilar/:*/yetkiler": ["anonymous"] },
  ),
  ...cells(
    {
      item: "§8 madde 13: Sistem > Kullanıcılar > Yetkiler (plan §6.1)",
      section: "routes",
      step: 9,
      old: MISSING,
      new: "open",
    },
    { "/sistem/kullanicilar/:*/yetkiler": ["admin", "superuser"] },
  ),
  ...cells(
    {
      item: "§8 madde 13: Sistem > Kullanıcılar > Yetkiler (plan §6.1)",
      section: "routes",
      step: 9,
      old: MISSING,
      new: "forbidden",
    },
    {
      "/sistem/kullanicilar/:*/yetkiler": [
        "inactive",
        "no_role",
        "yonetim",
        "planlama",
        "depo",
        "uretim",
        "laboratuvar",
        "dolum",
        "sevkiyat",
        "satin_alma",
        "depo+sevkiyat",
      ],
    },
  ),

  // 9. adım — Yeni ekran: Yetkilerim (giriş yapan herkes; plan §6.4).
  ...cells(
    {
      item: "§8 madde 14: Yetkilerim (plan §6.4)",
      section: "routes",
      step: 9,
      old: MISSING,
      new: "login",
    },
    { "/yetkilerim": ["anonymous"] },
  ),
  ...cells(
    {
      item: "§8 madde 14: Yetkilerim (plan §6.4)",
      section: "routes",
      step: 9,
      old: MISSING,
      new: "open",
    },
    {
      "/yetkilerim": [
        "inactive",
        "no_role",
        "yonetim",
        "planlama",
        "depo",
        "uretim",
        "laboratuvar",
        "dolum",
        "sevkiyat",
        "satin_alma",
        "admin",
        "superuser",
        "depo+sevkiyat",
      ],
    },
  ),
];

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
  return (entry.step ?? 1) <= step && (entry.until === undefined || step <= entry.until);
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

/** Plan §10: §8 maddesi → açıldığı adımlar (backend'deki `test_allowlist.ITEM_STEPS` ile aynı). */
export const ITEM_STEPS: Readonly<Record<number, readonly number[]>> = {
  1: [8],
  2: [8],
  3: [8],
  4: [2, 3, 4, 5, 6, 7, 8],
  5: [4],
  6: [7],
  7: [2, 5, 6],
  8: [5],
  9: [7, 8],
  10: [7],
  11: [7, 8],
  12: [6],
  13: [9],
  14: [9],
  15: [9],
};
/** Planın adıyla eklediği ekranlar → açıldıkları adımlar (kapalı liste; plan §6, §10). */
export const PLANNED_ITEMS: Readonly<Record<string, readonly number[]>> = {
  "yeni sayfa: Sistem > Rol yetkileri sekmesi (plan §6.2)": [9],
};

type FrozenSections = Readonly<
  Record<string, Readonly<Record<string, Readonly<Record<string, unknown>>>>>
>;

/**
 * Plana ya da dondurulmuş anlık görüntüye bağlanamayan kayıtlar. Sonraki adımların kayıtları da
 * bugünden denetlenir: yazım yanlışı ya da yanlış eski değer, maddenin adımına gelinmeden yakalanır.
 */
export function entryErrors(
  entries: readonly Allowed[],
  baseline: FrozenSections,
  currentStep: number = CURRENT_STEP,
  planned: Readonly<Record<string, readonly number[]>> = PLANNED_ITEMS,
): string[] {
  const errors: string[] = [];
  for (const entry of entries) {
    const label = `${entry.item}: ${entry.section} › ${entry.case} [${entry.persona ?? "*"}]`;
    const step = entry.step ?? 1;
    const found = /^§8 madde (\d+)\b/.exec(entry.item);
    if (found) {
      const number = Number(found[1]);
      const steps = ITEM_STEPS[number];
      if (!steps) errors.push(`${label}: §8'de böyle bir madde yok.`);
      else if (!steps.includes(step))
        errors.push(
          `${label}: madde ${number} [${steps.join(", ")}]. adımda açılır, kayıt ${step}. adımda.`,
        );
    } else if (Object.prototype.hasOwnProperty.call(planned, entry.item)) {
      const steps = planned[entry.item];
      if (!steps.includes(step))
        errors.push(
          `${label}: planın eklediği kayıt [${steps.join(", ")}]. adımda açılır, kayıt ${step}. adımda.`,
        );
    } else {
      errors.push(`${label}: planın bir maddesine bağlı değil.`);
    }
    if (entry.until !== undefined && entry.until < step)
      errors.push(`${label}: son adım (${entry.until}) ilk adımdan (${step}) önce.`);
    const cases = baseline[entry.section];
    if (!cases) {
      errors.push(`${label}: böyle bir bölüm yok.`);
      continue;
    }
    const cells: unknown[] = [];
    for (const [name, values] of Object.entries(cases)) {
      if (!matches(entry.case, name)) continue;
      for (const [persona, value] of Object.entries(values)) {
        if (matches(entry.persona ?? "*", persona)) cells.push(value);
      }
    }
    // Yalnız verilmeyen değer `ANY`dır; `null` gerçek bir değerdir (backend'deki `None` gibi).
    const old = entry.old === undefined ? ANY : entry.old;
    if (old === MISSING) {
      if (cells.length > 0)
        errors.push(
          `${label}: yeni durum diye yazılmış, anlık görüntüde ${cells.length} hücre var.`,
        );
    } else if (cells.length === 0) {
      errors.push(`${label}: anlık görüntüde eşleşen hücre yok.`);
    } else if (old !== ANY && !cells.some((value) => sameValue(value, old))) {
      errors.push(
        `${label}: eşleşen hücrelerin hiçbirinde eski değer ${JSON.stringify(old)} değil.`,
      );
    }
    if (old !== ANY && entry.new !== undefined && entry.new !== ANY && sameValue(old, entry.new))
      errors.push(`${label}: eski ve yeni değer aynı.`);
    if (isActive(entry, currentStep) && (entry.new === undefined || entry.new === ANY))
      errors.push(
        `${label}: adımı açıldı; yeni değer gözlenen değere sabitlenmeli (daraltmak onay istemez).`,
      );
  }
  return errors;
}
