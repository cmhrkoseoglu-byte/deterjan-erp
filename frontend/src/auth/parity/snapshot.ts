import { ALLOWED, MISSING, permitted, sameValue, type Allowed } from "./allowlist";
import { PERSONAS } from "./personas";

/**
 * Eşlik anlık görüntüsü dosyası (`baseline.json`): kaydetme, karşılaştırma ve okunur fark çıktısı.
 *
 * Dosya bölümlerden oluşur; her bölüm iki düzeyli bir eşlemedir: `{durum: {persona: değer}}`.
 * `_` ile başlayan anahtarlar açıklamadır. `ACCESS_PARITY_UPDATE=1` ile çalışan test dosyayı
 * bugünkü sonuçla yeniden yazar; bu yalnız 1. adımda ya da sahibin onayı ve DECISIONS kaydıyla
 * yapılır (plan §5.5). Backend'deki karşılığı:
 * `backend/apps/core/tests/access_contract/snapshot.py`.
 */

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type Cases = Record<string, Record<string, Json>>;
export type Baseline = Record<string, Cases>;

export const UPDATE_ENV = "ACCESS_PARITY_UPDATE";
const FILE_NAME = "baseline.json";
const NOTE =
  "Ön yüz eşlik anlık görüntüsü (plan §5.5, 4. parça): {bölüm: {durum: {persona: değer}}}. " +
  "Elle düzenlenmez; ACCESS_PARITY_UPDATE=1 ile yeniden yazmak sahibin onayını ister.";

export function updating(): boolean {
  return import.meta.env[UPDATE_ENV] === "1";
}

interface NodeFiles {
  existsSync(path: string): boolean;
  readFileSync(path: string, encoding: "utf8"): string;
  writeFileSync(path: string, data: string, encoding: "utf8"): void;
  /** Bu klasördeki `baseline.json`'un yolu. */
  file: string;
}

/** Node'un dosya işlevleri. Modül adı değişkenle verilir: ön yüzün tiplerinde Node yok. */
async function node(): Promise<NodeFiles> {
  const load = (name: string) => import(/* @vite-ignore */ name);
  const [fs, path, url] = await Promise.all([load("node:fs"), load("node:path"), load("node:url")]);
  const here = path.dirname(url.fileURLToPath(import.meta.url)) as string;
  return {
    existsSync: fs.existsSync,
    readFileSync: fs.readFileSync,
    writeFileSync: fs.writeFileSync,
    file: path.join(here, FILE_NAME) as string,
  };
}

export async function loadBaseline(): Promise<Baseline | null> {
  const fs = await node();
  if (!fs.existsSync(fs.file)) return null;
  const data = JSON.parse(fs.readFileSync(fs.file, "utf8")) as Record<string, unknown>;
  return Object.fromEntries(
    Object.entries(data).filter(([key]) => !key.startsWith("_")),
  ) as Baseline;
}

function sortedCases(cases: Cases): Cases {
  return Object.fromEntries(
    Object.keys(cases)
      .sort()
      .map((name) => [name, orderedPersonas(cases[name])]),
  );
}

function orderedPersonas(values: Record<string, Json>): Record<string, Json> {
  return Object.fromEntries(
    Object.keys(values)
      .sort((a, b) => personaIndex(a) - personaIndex(b))
      .map((persona) => [persona, values[persona]]),
  );
}

function personaIndex(persona: string): number {
  const index = PERSONAS.indexOf(persona);
  return index < 0 ? PERSONAS.length : index;
}

/**
 * Üretilen bölümleri prettier biçiminde yazar. `previous` verilirse (testin bir kısmı çalıştıysa)
 * dosyadaki öteki bölümler korunur.
 */
export async function saveBaseline(sections: Baseline, previous: Baseline | null): Promise<void> {
  const merged: Baseline = { ...(previous ?? {}), ...sections };
  const data: Record<string, unknown> = { _note: NOTE, _personas: PERSONAS };
  for (const section of Object.keys(merged).sort()) data[section] = sortedCases(merged[section]);
  const fs = await node();
  const prettier = await import("prettier");
  const options = (await prettier.resolveConfig(fs.file)) ?? {};
  // Girintili yazılır: prettier açık yazılmış nesneleri açık bırakır (persona başına bir satır).
  const text = await prettier.format(JSON.stringify(data, null, 2), { ...options, parser: "json" });
  fs.writeFileSync(fs.file, text, "utf8");
}

function short(value: unknown): string {
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return text.length <= 200 ? text : `${text.slice(0, 197)}...`;
}

/** (izinsiz farklar, izin listesindeki farklar) — okunur satırlar olarak. */
export function differences(
  section: string,
  expected: Cases,
  actual: Cases,
  allowed: readonly Allowed[] = ALLOWED,
): { unexpected: string[]; permitted: string[] } {
  const unexpected: string[] = [];
  const allowedLines: string[] = [];
  const names = [...new Set([...Object.keys(expected), ...Object.keys(actual)])].sort();
  for (const name of names) {
    const oldValues = expected[name];
    const newValues = actual[name];
    const personas = [
      ...new Set([...Object.keys(oldValues ?? {}), ...Object.keys(newValues ?? {})]),
    ];
    personas.sort((a, b) => personaIndex(a) - personaIndex(b));
    for (const persona of personas) {
      const oldValue = oldValues && persona in oldValues ? oldValues[persona] : MISSING;
      const newValue = newValues && persona in newValues ? newValues[persona] : MISSING;
      if (sameValue(oldValue, newValue)) continue;
      const line = `${section} › ${name} [${persona}]: ${short(oldValue)} → ${short(newValue)}`;
      const rule = permitted(section, name, persona, oldValue, newValue, allowed);
      if (rule) allowedLines.push(`${line} (${rule.item})`);
      else unexpected.push(line);
    }
  }
  return { unexpected, permitted: allowedLines };
}

/** Bölümü dondurulmuş anlık görüntüyle karşılaştırır; izinsiz farkta okunur bir hata fırlatır. */
export function compareSection(baseline: Baseline | null, section: string, actual: Cases): void {
  if (!baseline) {
    throw new Error(`Anlık görüntü yok: ${FILE_NAME}. 1. adımda ${UPDATE_ENV}=1 ile üretilir.`);
  }
  const { unexpected } = differences(section, baseline[section] ?? {}, actual);
  if (unexpected.length === 0) return;
  const shown = unexpected.slice(0, 80).join("\n");
  const more = unexpected.length > 80 ? `\n... ve ${unexpected.length - 80} fark daha` : "";
  throw new Error(
    `Ön yüz yetki eşliği bozuldu (${section}): ${unexpected.length} izinsiz fark.\n` +
      `${shown}${more}\n` +
      "Fark bilerek yapıldıysa allowlist.ts'de planın bir maddesine bağlanmalıdır.",
  );
}
