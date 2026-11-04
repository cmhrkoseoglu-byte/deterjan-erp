import { Alert, Button, Group, Modal, SimpleGrid, Stack } from "@mantine/core";
import { useForm } from "@mantine/form";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { suggestCode } from "../../api/coding";
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
  const suggested = useRef("");
  const hasCode = Boolean(codeType) && fields.some((field) => field.name === CODE);
  // Kayıt açıldıktan sonra kodu yalnızca admin değiştirir (sunucu da denetler).
  const codeLocked = hasCode && Boolean(record) && !isAdmin(user);
  const typeValue = codeTypeField ? String(form.values[codeTypeField] ?? "") : "";

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
      suggested.current = "";
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- yalnızca açılışta doldurulur
  }, [opened, record]);

  // Önerilen kod, kullanıcı alana kendi kodunu yazmadıysa alana gelir; tür değişince yenilenir.
  const suggestedCode = suggestion.data?.code ?? "";
  useEffect(() => {
    if (!opened || record || !suggestedCode) return;
    const current = String(form.values[CODE] ?? "");
    if (current === "" || current === suggested.current) {
      form.setFieldValue(CODE, suggestedCode);
      suggested.current = suggestedCode;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- yalnızca öneri değişince
  }, [suggestedCode, opened, record]);

  const mutation = useMutation({
    mutationFn: (values: FormValues) => {
      const payload = toPayload(fields, values);
      if (record) {
        for (const field of fields) if (field.lockedOnEdit) delete payload[field.name];
        if (codeLocked) delete payload[CODE];
      }
      return onSubmit(payload);
    },
    onSuccess: (saved) => {
      notifications.show({ color: "green", message: ct.saved });
      onSaved(saved);
    },
    onError: (err) => setError(applyApiErrors(form, err)),
  });

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
      <form onSubmit={form.onSubmit((values) => mutation.mutate(values))}>
        <Stack>
          {error && (
            <Alert color="red" variant="light">
              {error}
            </Alert>
          )}
          {readOnly && (
            <Alert color="gray" variant="light">
              {ct.readOnly}
            </Alert>
          )}
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            {fields.map((field) => (
              <div
                key={field.name}
                style={field.wide || field.type === "textarea" ? { gridColumn: "1 / -1" } : {}}
              >
                <FieldInput
                  field={describeCode(field)}
                  form={form}
                  disabled={
                    readOnly ||
                    (Boolean(record) && field.lockedOnEdit) ||
                    (field.name === CODE && codeLocked)
                  }
                />
              </div>
            ))}
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
