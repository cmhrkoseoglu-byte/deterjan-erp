// Cari ülke kodu: ISO 3166-1 alpha-2 listesinden seçilir (liste sunucudan, adlar Türkçe).
import { Select } from "@mantine/core";
import { useStandardOptions, withValue } from "../../components/standards/useStandardOptions";
import type { FieldComponentProps } from "../common/forms";

export function CountryField({ field, form, disabled, style }: FieldComponentProps) {
  const { countries } = useStandardOptions();
  const value = String(form.values[field.name] ?? "") || null;
  const { error } = form.getInputProps(field.name);
  return (
    <Select
      style={style}
      label={field.label}
      description={field.description}
      withAsterisk={field.required}
      disabled={disabled}
      searchable
      allowDeselect={false}
      data={withValue(countries, value)}
      value={value}
      error={error}
      onChange={(next) => form.setFieldValue(field.name, next ?? "")}
      nothingFoundMessage="Ülke bulunamadı"
    />
  );
}
