import { Alert, Select } from "@mantine/core";
import { useEffect } from "react";
import { remember, scaleBlocked, useScales } from "./scales";
import { pt } from "./strings";

/** Tartım terazisi seçimi (Faz 4): kalibrasyonu yaklaşan terazi sarı uyarı verir, süresi geçen ya
 * da duruştaki terazi seçilemez (backend de reddeder). Tanımlı terazi yoksa hiçbir şey göstermez. */
export function ScaleSelect({
  value,
  onChange,
}: {
  value: number | null;
  onChange: (id: number | null) => void;
}) {
  const scales = useScales();
  const rows = scales.data ?? [];
  const selected = rows.find((row) => row.equipment === value) ?? null;

  useEffect(() => {
    // Hatırlanan terazi artık yoksa ya da kullanılamıyorsa seçimi temizle.
    if (value !== null && scales.data && (!selected || scaleBlocked(selected))) onChange(null);
  }, [value, selected, scales.data, onChange]);

  if (rows.length === 0) return null;
  return (
    <>
      <Select
        size="lg"
        label={pt.scale}
        placeholder={pt.scalePlaceholder}
        withAsterisk
        data={rows.map((row) => ({
          value: String(row.equipment),
          label: scaleBlocked(row)
            ? `${row.equipment_code} - ${row.equipment_name} (${
                row.is_down ? pt.scaleDown : pt.calibrationOverdueShort
              })`
            : `${row.equipment_code} - ${row.equipment_name}`,
          disabled: scaleBlocked(row),
        }))}
        value={value === null ? null : String(value)}
        onChange={(next) => {
          const id = next ? Number(next) : null;
          remember(id);
          onChange(id);
        }}
        data-testid="scale-select"
      />
      {selected?.status === "DUE_SOON" && (
        <Alert color="yellow" variant="light" data-testid="calibration-warning">
          {pt.calibrationDueSoon(selected.equipment_code, selected.days_left ?? 0)}
        </Alert>
      )}
      {rows.some(scaleBlocked) && !selected && (
        <Alert color="red" variant="light">
          {pt.calibrationBlockedHint}
        </Alert>
      )}
    </>
  );
}
