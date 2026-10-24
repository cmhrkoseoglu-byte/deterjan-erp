// Kullanıcı adı kuralı: sunucudaki `core.services.USERNAME_RE` ile aynı.
export const USERNAME_RE = /^[a-z0-9][a-z0-9._-]{1,149}$/;

const TURKISH: Record<string, string> = {
  ç: "c",
  ğ: "g",
  ı: "i",
  ö: "o",
  ş: "s",
  ü: "u",
  Ç: "c",
  Ğ: "g",
  İ: "i",
  Ö: "o",
  Ş: "s",
  Ü: "u",
};

/** Yazılan kullanıcı adındaki büyük harfleri küçültür (Türkçe büyük harfler kurala uymaz). */
export function normalizeUsernameInput(value: string): string {
  return value.replace(/[A-Z]/g, (ch) => ch.toLowerCase());
}

/** Ad soyaddan kurala uyan bir kullanıcı adı önerir: "Ahmet Yılmaz" → "ahmet.yilmaz". */
export function suggestUsername(fullName: string): string {
  return fullName
    .trim()
    .replace(/[çğıöşüÇĞİÖŞÜ]/g, (ch) => TURKISH[ch] ?? ch)
    .toLowerCase()
    .replace(/\s+/g, ".")
    .replace(/[^a-z0-9._-]/g, "")
    .replace(/\.{2,}/g, ".")
    .replace(/^[._-]+/, "")
    .slice(0, 150);
}
