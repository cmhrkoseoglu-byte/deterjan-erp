import type { UseFormReturnType } from "@mantine/form";
import axios from "axios";
import type { ComponentType, CSSProperties } from "react";
import { getErrorMessage } from "../../api/client";
import type { ApiError } from "../../api/types";

export type FieldType =
  "text" | "textarea" | "email" | "decimal" | "integer" | "checkbox" | "select" | "relation";

/** Seçenek kaynağı: ana veri uç noktası + isteğe bağlı filtre. */
export interface RelationSource {
  endpoint:
    | "units"
    | "categories"
    | "materials"
    | "warehouses"
    | "locations"
    | "suppliers"
    | "customers"
    | "printers";
  params?: Record<string, string>;
}

export interface FieldDef {
  name: string;
  label: string;
  type: FieldType;
  required?: boolean;
  description?: string;
  options?: { value: string; label: string }[];
  relation?: RelationSource;
  /** Düzenlemede değiştirilemez (ör. dönüşümün malzemesi). */
  lockedOnEdit?: boolean;
  /**
   * Kaydın bu alanı true ise alan kilitlidir (ör. lotu olan malzemenin GTIN'i: `gtin_locked`):
   * düzenlemede kapalı gelir, açıklama yerine `lockedHelp` yazar ve gönderilmez.
   */
  lockedBy?: string;
  lockedHelp?: string;
  /** Formda tam satır kaplar. */
  wide?: boolean;
  /** Alanın yerine çizilen bileşen (ör. öneri düğmeli GTIN alanı). */
  component?: ComponentType<FieldComponentProps>;
}

export type FormValues = Record<string, string | boolean>;

/** Özel alan bileşeninin aldıkları (bkz. `FieldDef.component`). */
export interface FieldComponentProps {
  /** Açıklaması (kilit notu dahil) işlenmiş alan tanımı. */
  field: FieldDef;
  form: UseFormReturnType<FormValues>;
  /** Düzenlenen kayıt; yeni kayıtta null. */
  record: Record<string, unknown> | null;
  disabled: boolean;
  /** Izgaradaki hücrenin stili (geniş alan); bileşen kök öğesine verir. */
  style?: CSSProperties;
  /** Son kayıt denemesinin hatası (yeni denemede sıfırlanır): alan alınmış önerisini yeniler. */
  saveError: unknown;
  /** Alan, kayıtta alınmış çıkan önerisini yenisiyle değiştirdi: formun hatası yerine not çıkar. */
  onSuggestionReplaced: (notice: string) => void;
  /** Alan, yazdığı öneriyi sildi (ör. tür mamulden çıktı): `onSuggestionReplaced` notu kalkar. */
  onSuggestionCleared: () => void;
}

/** API kaydını form değerlerine çevirir (Mantine girişleri metin bekler). */
export function toFormValues(
  fields: readonly FieldDef[],
  record: Record<string, unknown> | null,
  defaults: FormValues = {},
): FormValues {
  const values: FormValues = {};
  for (const field of fields) {
    const raw = record ? record[field.name] : defaults[field.name];
    if (field.type === "checkbox") {
      values[field.name] = typeof raw === "boolean" ? raw : Boolean(defaults[field.name] ?? false);
    } else if (raw === null || raw === undefined) {
      values[field.name] = "";
    } else if (field.type === "decimal") {
      values[field.name] = trimDecimal(String(raw));
    } else {
      values[field.name] = String(raw);
    }
  }
  return values;
}

/** "12.5000" → "12.5" (formda gereksiz sıfırlar gösterilmez). */
export function trimDecimal(value: string): string {
  if (!value.includes(".")) return value;
  return value.replace(/0+$/, "").replace(/\.$/, "");
}

/** "1.234,5" ya da "1,05" girişini API'nin beklediği "1234.5" biçimine çevirir. */
export function normalizeDecimal(value: string): string {
  const text = value.trim().replace(/\s/g, "");
  if (text.includes(",") && text.includes(".")) return text.replace(/\./g, "").replace(",", ".");
  return text.replace(",", ".");
}

/** Form değerlerinden API gövdesi: boş isteğe bağlı alanlar null olur. */
export function toPayload(
  fields: readonly FieldDef[],
  values: FormValues,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  for (const field of fields) {
    const value = values[field.name];
    if (field.type === "checkbox") {
      payload[field.name] = Boolean(value);
      continue;
    }
    const text = typeof value === "string" ? value.trim() : "";
    if (field.type === "decimal") payload[field.name] = text ? normalizeDecimal(text) : null;
    else if (field.type === "integer") payload[field.name] = text ? Number(text) : null;
    else if (field.type === "relation") payload[field.name] = text ? Number(text) : null;
    else payload[field.name] = text;
  }
  return payload;
}

/**
 * API hatasını forma uygular: alan hataları ilgili alanın altına yazılır. Alana bağlanamayan
 * mesaj (iş kuralı hatası, genel hata) döner; ekranda uyarı olarak gösterilir.
 */
export function applyApiErrors(form: UseFormReturnType<FormValues>, error: unknown): string {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data as ApiError | undefined;
    if (data?.code === "validation_error" && data.errors) {
      const known: Record<string, string> = {};
      const other: string[] = [];
      for (const [name, messages] of Object.entries(data.errors)) {
        const text = Array.isArray(messages) ? messages.join(" ") : String(messages);
        if (name in form.values) known[name] = text;
        else other.push(text);
      }
      form.setErrors(known);
      return other.join(" ") || (Object.keys(known).length ? "" : getErrorMessage(error));
    }
  }
  return getErrorMessage(error);
}
