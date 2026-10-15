import { Checkbox, NumberInput, Select, Textarea, TextInput } from "@mantine/core";
import type { UseFormReturnType } from "@mantine/form";
import type { FieldDef, FormValues } from "./forms";
import { useOptions } from "./useOptions";

interface Props {
  field: FieldDef;
  form: UseFormReturnType<FormValues>;
  disabled?: boolean;
}

/** Alan tanımına göre uygun Mantine girişini çizer. */
export function FieldInput({ field, form, disabled }: Props) {
  const common = {
    label: field.label,
    description: field.description,
    withAsterisk: field.required,
    disabled,
  };
  const options = useOptions(field.type === "relation" ? field.relation : undefined);

  switch (field.type) {
    case "checkbox":
      return (
        <Checkbox
          mt="md"
          label={field.label}
          description={field.description}
          disabled={disabled}
          {...form.getInputProps(field.name, { type: "checkbox" })}
        />
      );
    case "textarea":
      return <Textarea autosize minRows={2} {...common} {...form.getInputProps(field.name)} />;
    case "integer":
      return (
        <NumberInput
          {...common}
          allowDecimal={false}
          allowNegative={false}
          {...form.getInputProps(field.name)}
          onChange={(value) => form.setFieldValue(field.name, String(value ?? ""))}
        />
      );
    case "select":
      return (
        <Select
          {...common}
          data={field.options ?? []}
          allowDeselect={!field.required}
          {...form.getInputProps(field.name)}
          onChange={(value) => form.setFieldValue(field.name, value ?? "")}
        />
      );
    case "relation":
      return (
        <Select
          {...common}
          searchable
          clearable={!field.required}
          nothingFoundMessage="Bulunamadı"
          data={options.data ?? []}
          {...form.getInputProps(field.name)}
          onChange={(value) => form.setFieldValue(field.name, value ?? "")}
        />
      );
    case "decimal":
      // Türkçe klavyede virgülle yazılabilsin diye metin girişi; gönderirken noktaya çevrilir.
      return <TextInput inputMode="decimal" {...common} {...form.getInputProps(field.name)} />;
    default:
      return (
        <TextInput
          type={field.type === "email" ? "email" : "text"}
          {...common}
          {...form.getInputProps(field.name)}
        />
      );
  }
}
