import { Alert, Button, Group, Modal, SimpleGrid, Stack } from "@mantine/core";
import { useForm } from "@mantine/form";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery } from "@tanstack/react-query";
import axios from "axios";
import { useEffect, useRef, useState } from "react";
import { getErrorCode } from "../../api/client";
import { suggestCode } from "../../api/coding";
import type { ApiError } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { isAdmin } from "../../auth/roles";
import { FieldInput } from "./FieldInput";
import { applyApiErrors, toFormValues, toPayload, type FieldDef, type FormValues } from "./forms";
import { ct } from "./strings";

interface Props<T> {
  opened: boolean;
  title: string;
  fields: readonly FieldDef[];
  record: T | null;
  defaults?: FormValues;
  readOnly?: boolean;
  /**
   * Kodlama sistematiğindeki kod türü (ör. "masterdata.material"): yeni kayıtta önerilen kod
   * gelir, düzenlemede kodu yalnızca admin değiştirir, eski kodlar görünür.
   */
  codeType?: string;
  /** Kodun öneki kaydın bu alanından gelir (ekipman türü). */
  codeTypeField?: string;
  onClose: () => void;
  onSubmit: (payload: Record<string, unknown>) => Promise<T>;
  onSaved: (record: T) => void;
}

const CODE = "code";
/** Kodun alınmış olduğunu bildiren iş kuralı hataları: kod az önce başka kayda verildi, başka
 * kaydın eski kodu ya da eşzamanlı aynı kod. */
const CODE_TAKEN = ["code_taken", "code_reserved", "duplicate"];

/** Kayıt, kod alınmış olduğu için mi reddedildi? (Kod alanındaki benzersizlik hatası da sayılır.) */
function isCodeTaken(error: unknown): boolean {
  const code = getErrorCode(error);
  if (CODE_TAKEN.includes(code)) return true;
  if (code !== "validation_error" || !axios.isAxiosError(error)) return false;
  const errors = (error.response?.data as ApiError | undefined)?.errors;
  return Boolean(errors && CODE in errors);
}

/** Ana veri kaydı formu (yeni / düzenle). Doğrulama backend'dedir; hatalar alanlara yazılır. */
export function RecordFormModal<T extends object>({
  opened,
  title,
  fields,
  record,
  defaults,
  readOnly,
  codeType,
  codeTypeField,
  onClose,
  onSubmit,
  onSaved,
}: Props<T>) {
  const { user } = useAuth();
  const form = useForm<FormValues>({ initialValues: toFormValues(fields, null, defaults) });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  // Özel alanın (ör. GTIN) koyduğu not: alan önerisini silince yalnızca bu not kalkar.
  const fieldNotice = useRef("");
  const suggested = useRef("");
  const hasCode = Boolean(codeType) && fields.some((field) => field.name === CODE);
  // Kayıt açıldıktan sonra kodu yalnızca admin değiştirir (sunucu da denetler).
  const codeLocked = hasCode && Boolean(record) && !isAdmin(user);
  const typeValue = codeTypeField ? String(form.values[codeTypeField] ?? "") : "";
  const recordValues = record as Record<string, unknown> | null;

  /** Kayıt alanı kilitliyor mu (ör. lotu olan malzemenin GTIN'i)? Yeni kayıtta kilit yoktur. */
  function isLocked(field: FieldDef): boolean {
    return Boolean(recordValues && field.lockedBy && recordValues[field.lockedBy]);
  }

  const suggestion = useQuery({
    queryKey: ["coding", "suggest", codeType, typeValue],
    queryFn: () => suggestCode(codeType!, typeValue || undefined),
    enabled: opened && hasCode && !record && !readOnly,
    staleTime: 0,
    retry: false,
  });

  useEffect(() => {
    if (opened) {
      form.setValues(toFormValues(fields, record as Record<string, unknown> | null, defaults));
      form.resetDirty();
      form.clearErrors();
      setError("");
      setNotice("");
      suggested.current = "";
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- yalnızca açılışta doldurulur
  }, [opened, record]);

  /** Alandaki güncel kod. `form.values` çizimdeki değerdir; pencere yeniden açılınca yukarıdaki
   * sıfırlama aynı turda yapıldığı için güncel değer `getValues()` ile okunur. */
  function currentCode(): string {
    return String(form.getValues()[CODE] ?? "");
  }

  // Önerilen kod, kullanıcı alana kendi kodunu yazmadıysa alana gelir; tür değişince yenilenir.
  const suggestedCode = suggestion.data?.code ?? "";
  useEffect(() => {
    if (!opened || record || !suggestedCode) return;
    const current = currentCode();
    if (current === "" || current === suggested.current) {
      form.setFieldValue(CODE, suggestedCode);
      suggested.current = suggestedCode;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- yalnızca öneri değişince
  }, [suggestedCode, opened, record]);

  /**
   * Önerilen kod kaydedilirken alınmışsa (başka kayda verildi ya da başka kaydın eski kodu)
   * öneri yenilenir ve sıradaki kod alana yazılır; true döner. Kullanıcı kendi kodunu yazdıysa
   * ya da yeni öneri yoksa dokunulmaz.
   */
  async function replaceTakenSuggestion(err: unknown): Promise<boolean> {
    const taken = suggested.current;
    if (record || !taken || currentCode() !== taken || !isCodeTaken(err)) return false;
    const fresh = (await suggestion.refetch()).data?.code ?? "";
    // Yenilenen öneriyi yukarıdaki etki de alana yazabilir; ikisi aynı değeri yazar.
    if (!fresh || fresh === taken || ![taken, fresh].includes(currentCode())) return false;
    form.setFieldValue(CODE, fresh); // kod alanındaki hata da silinir
    suggested.current = fresh;
    setNotice(ct.codeRefreshed(taken, fresh));
    return true;
  }

  const mutation = useMutation({
    mutationFn: (values: FormValues) => {
      const payload = toPayload(fields, values);
      if (record) {
        for (const field of fields) {
          if (field.lockedOnEdit || isLocked(field)) delete payload[field.name];
        }
        if (codeLocked) delete payload[CODE];
      }
      return onSubmit(payload);
    },
    onSuccess: (saved) => {
      notifications.show({ color: "green", message: ct.saved });
      onSaved(saved);
    },
    onError: async (err) => {
      const message = applyApiErrors(form, err);
      if (await replaceTakenSuggestion(err)) {
        // Kod hatası yeni öneriyle giderildi; varsa öteki alan dışı mesajlar kalır.
        setError(getErrorCode(err) === "validation_error" ? message : "");
        return;
      }
      setError(message);
    },
  });

  /** Özel alan (ör. GTIN) alınmış önerisini yeniledi: sunucunun hatası yerine sarı not çıkar. */
  function suggestionReplaced(text: string) {
    setError("");
    fieldNotice.current = text;
    setNotice(text);
  }

  /** Özel alan yazdığı öneriyi sildi: o alanın notu kalkar, başka not ya da hata kalır. */
  function suggestionCleared() {
    const own = fieldNotice.current;
    fieldNotice.current = "";
    if (own) setNotice((current) => (current === own ? "" : current));
  }

  /** Alan açıklaması: kilitli alanda kilidin nedeni, kod alanında öneri, kilit ve eski kodlar. */
  function describe(field: FieldDef): FieldDef {
    if (!isLocked(field) || !field.lockedHelp || readOnly) return describeCode(field);
    return describeCode({ ...field, description: field.lockedHelp });
  }

  function describeCode(field: FieldDef): FieldDef {
    if (!hasCode || field.name !== CODE) return field;
    const notes: string[] = [];
    if (field.description) notes.push(field.description);
    if (!record && suggestion.data?.active && suggestion.data.format) {
      notes.push(ct.codeSuggested(suggestion.data.format));
    }
    if (codeLocked && !readOnly) notes.push(ct.codeLocked);
    const former = (record as { former_codes?: string[] } | null)?.former_codes ?? [];
    if (former.length) notes.push(ct.formerCodes(former.join(", ")));
    return { ...field, description: notes.join(" ") || undefined };
  }

  return (
    <Modal opened={opened} onClose={onClose} title={title} size="lg">
      <form
        onSubmit={form.onSubmit((values) => {
          setNotice("");
          mutation.mutate(values);
        })}
      >
        <Stack>
          {error && (
            <Alert color="red" variant="light">
              {error}
            </Alert>
          )}
          {notice && (
            <Alert color="yellow" variant="light">
              {notice}
            </Alert>
          )}
          {readOnly && (
            <Alert color="gray" variant="light">
              {ct.readOnly}
            </Alert>
          )}
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            {fields.map((field) => {
              const style = field.wide || field.type === "textarea" ? { gridColumn: "1 / -1" } : {};
              const disabled = Boolean(
                readOnly ||
                (record && field.lockedOnEdit) ||
                (field.name === CODE && codeLocked) ||
                isLocked(field),
              );
              if (field.component) {
                // Özel alan görünmüyorsa (null) ızgarada boş hücre kalmasın diye sarmalanmaz.
                const Custom = field.component;
                return (
                  <Custom
                    key={field.name}
                    field={describe(field)}
                    form={form}
                    record={recordValues}
                    disabled={disabled}
                    style={style}
                    saveError={mutation.error}
                    onSuggestionReplaced={suggestionReplaced}
                    onSuggestionCleared={suggestionCleared}
                  />
                );
              }
              return (
                <div key={field.name} style={style}>
                  <FieldInput field={describe(field)} form={form} disabled={disabled} />
                </div>
              );
            })}
          </SimpleGrid>
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {readOnly ? ct.close : ct.cancel}
            </Button>
            {!readOnly && (
              <Button type="submit" loading={mutation.isPending}>
                {ct.save}
              </Button>
            )}
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
