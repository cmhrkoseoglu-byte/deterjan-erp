import { Alert, Button, Group, Modal, SimpleGrid, Stack } from "@mantine/core";
import { useForm } from "@mantine/form";
import { notifications } from "@mantine/notifications";
import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";
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
  onClose: () => void;
  onSubmit: (payload: Record<string, unknown>) => Promise<T>;
  onSaved: (record: T) => void;
}

/** Ana veri kaydı formu (yeni / düzenle). Doğrulama backend'dedir; hatalar alanlara yazılır. */
export function RecordFormModal<T extends object>({
  opened,
  title,
  fields,
  record,
  defaults,
  readOnly,
  onClose,
  onSubmit,
  onSaved,
}: Props<T>) {
  const form = useForm<FormValues>({ initialValues: toFormValues(fields, null, defaults) });
  const [error, setError] = useState("");

  useEffect(() => {
    if (opened) {
      form.setValues(toFormValues(fields, record as Record<string, unknown> | null, defaults));
      form.resetDirty();
      form.clearErrors();
      setError("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- yalnızca açılışta doldurulur
  }, [opened, record]);

  const mutation = useMutation({
    mutationFn: (values: FormValues) => {
      const payload = toPayload(fields, values);
      if (record) for (const field of fields) if (field.lockedOnEdit) delete payload[field.name];
      return onSubmit(payload);
    },
    onSuccess: (saved) => {
      notifications.show({ color: "green", message: ct.saved });
      onSaved(saved);
    },
    onError: (err) => setError(applyApiErrors(form, err)),
  });

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
                  field={field}
                  form={form}
                  disabled={readOnly || (Boolean(record) && field.lockedOnEdit)}
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
