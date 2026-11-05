// Ana veri formlarındaki GS1 GTIN alanları: mamulde "GTIN öner", KOLI dönüşümünde koli GTIN'i.
// Kilit (lotu olan malzemenin GTIN'i) formun `lockedBy` kuralıyla gelir: alan kapalıdır.
import { Button, Text, TextInput } from "@mantine/core";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { getErrorCode, getErrorMessage } from "../../api/client";
import {
  CASE_UNIT,
  gtinSuggestionKey,
  listRecords,
  suggestCaseGtin,
  suggestGtin,
  type Unit,
} from "../../api/masterdata";
import type { FieldComponentProps } from "../common/forms";

const g = {
  suggest: "GTIN öner",
  suggestCase: "Koli GTIN'i öner",
  refreshed: (taken: string, next: string) =>
    `${taken} başka bir malzemede ya da koli dönüşümünde kayıtlı. Yerine sıradaki önerilen GTIN ${next} yazıldı; kontrol edip yeniden kaydedin.`,
};

/** Kayıt, GTIN başka bir malzemede ya da koli dönüşümünde kayıtlı olduğu için reddedildi. */
const GTIN_TAKEN = "gtin_taken";

function GtinInput({ field, form, disabled }: FieldComponentProps) {
  return (
    <TextInput
      label={field.label}
      description={field.description}
      withAsterisk={field.required}
      disabled={disabled}
      inputMode="numeric"
      {...form.getInputProps(field.name)}
    />
  );
}

function fieldText(props: FieldComponentProps, name: string): string {
  return String(props.form.values[name] ?? "").trim();
}

/**
 * Malzeme GTIN'i: mamulde, öneri açıksa ve alan boşken "GTIN öner" sıradaki boş GTIN'i yazar.
 * Önerilen GTIN kaydedilirken başka kayda verilmişse (`gtin_taken`) sıradaki öneri alana yazılır.
 * Öneri yalnızca mamul için: tür mamulden çıkınca önerilen GTIN alanda duruyorsa silinir
 * (kullanıcının yazdığı GTIN kalır).
 */
export function MaterialGtinField(props: FieldComponentProps) {
  const { field, form, disabled, style, saveError, onSuggestionReplaced, onSuggestionCleared } =
    props;
  const finished = fieldText(props, "material_type") === "FINISHED";
  // Öneri yalnızca mamulde ve GTIN boşken istenir (malzeme yazma rolleri; görüntüleyende kapalı).
  const wanted = finished && !disabled && !fieldText(props, field.name);
  const suggestion = useQuery({
    queryKey: gtinSuggestionKey,
    queryFn: suggestGtin,
    enabled: wanted,
    staleTime: 0,
    retry: false,
  });
  // Yalnızca taze öneri sunulur: önbellekteki eski öneri (ör. az önce kaydedilen GTIN) yenilenirken
  // ya da yenilenemediyse düğme çıkmaz.
  const fresh = suggestion.isSuccess && !suggestion.isFetching;
  const data = wanted && fresh && suggestion.data.active ? suggestion.data : null;
  // Alana "GTIN öner" ile yazılan GTIN; kullanıcının kendi yazdığı GTIN değiştirilmez.
  const applied = useRef("");

  /** Alandaki güncel GTIN (`form.values` çizimdeki değerdir; hata sonrası güncel değer okunur). */
  function current(): string {
    return String(form.getValues()[field.name] ?? "").trim();
  }

  useEffect(() => {
    const taken = applied.current;
    if (!taken || getErrorCode(saveError) !== GTIN_TAKEN || current() !== taken) return;
    let live = true;
    void suggestion.refetch().then((result) => {
      const next = result.isSuccess && result.data.active ? (result.data.gtin ?? "") : "";
      // Bu arada pencere kapandıysa, yeniden kaydedildiyse ya da alan değiştiyse dokunulmaz.
      if (!live || !next || next === taken || current() !== taken) return;
      form.setFieldValue(field.name, next);
      applied.current = next;
      onSuggestionReplaced(g.refreshed(taken, next));
    });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- yalnızca kayıt hatası değişince
  }, [saveError]);
  useEffect(() => {
    // Tür mamulden çıktı: önerilen GTIN alanda duruyorsa silinir ve öneri unutulur (kayıtta
    // alınmışsa da yenilenmez). Kullanıcının yazdığı GTIN kalır.
    const suggested = applied.current;
    if (finished || !suggested) return;
    applied.current = "";
    if (current() !== suggested) return;
    form.setFieldValue(field.name, "");
    // Alınmış önerinin yenilendiğini söyleyen not artık alandaki GTIN'i anlatmaz.
    onSuggestionCleared();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- yalnızca tür değişince
  }, [finished]);

  return (
    <div style={style}>
      <GtinInput {...props} />
      {data?.gtin && (
        <Button
          size="compact-sm"
          variant="light"
          mt={6}
          onClick={() => {
            applied.current = data.gtin ?? "";
            form.setFieldValue(field.name, applied.current);
          }}
        >
          {g.suggest}
        </Button>
      )}
      {data && !data.gtin && data.reason && (
        <Text size="xs" c="var(--status-warning)" mt={4}>
          {data.reason}
        </Text>
      )}
    </div>
  );
}

/** "Koli GTIN'i öner" isteğindeki seçim (form değerleri: malzeme ve birim kimliği). */
interface CaseChoice {
  material: string;
  unit: string;
}

/**
 * Koli GTIN'i: yalnızca birimi KOLI olan dönüşümde görünür (koli dışı birime geçilince yazılan
 * değer silinir). Malzeme seçiliyse ve alan boşsa "Koli GTIN'i öner" malzemenin GTIN'inden
 * türetilen ilk boş GTIN-14'ü yazar; türetilemezse nedeni gösterilir. Önerilen GTIN o malzemenin
 * GTIN'inden türetilir: malzeme ya da birim değişince alanda duruyorsa silinir (kullanıcının
 * yazdığı GTIN kalır).
 */
export function CaseGtinField(props: FieldComponentProps) {
  const { field, form, record, disabled, style } = props;
  const unit = fieldText(props, "unit");
  const material = fieldText(props, "material");
  // Düzenlemede birim değişmez (kayıttaki kod); yeni kayıtta seçilen birimin kodu listeden okunur.
  const units = useQuery({
    queryKey: ["options", "units", "codes"],
    queryFn: async () =>
      (await listRecords<Unit>("units", { is_active: true, page_size: 500 })).results,
    enabled: !record,
    staleTime: 60_000,
  });
  const unitCode = record
    ? String(record.unit_code ?? "")
    : units.data?.find((row) => String(row.id) === unit)?.code;
  const isCase = unitCode === CASE_UNIT;
  const [reason, setReason] = useState("");
  // "Koli GTIN'i öner"in alana yazdığı GTIN ve türetildiği seçim (malzeme, birim).
  const applied = useRef<(CaseChoice & { gtin: string }) | null>(null);

  /** Alandaki güncel GTIN (`form.values` çizimdeki değerdir; güncel değer okunur). */
  function current(): string {
    return String(form.getValues()[field.name] ?? "").trim();
  }

  useEffect(() => {
    if (unitCode !== undefined && !isCase && fieldText(props, field.name)) {
      form.setFieldValue(field.name, "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- yalnızca birim değişince
  }, [unitCode]);
  useEffect(() => {
    setReason("");
    // Başka malzemeye (ya da birime) geçildi: önceki malzemeden türetilen öneri alanda duruyorsa
    // silinir, düğme yeni seçim için yeniden çıkar. Kullanıcının yazdığı GTIN kalır.
    const suggested = applied.current;
    if (!suggested || (suggested.material === material && suggested.unit === unit)) return;
    applied.current = null;
    if (current() === suggested.gtin) form.setFieldValue(field.name, "");
    // eslint-disable-next-line react-hooks/exhaustive-deps -- yalnızca malzeme/birim değişince
  }, [material, unit]);

  /** İstekteki malzeme ve birim hâlâ seçili mi? (`form.values` çizimdeki değerdir; güncel değer
   * okunur.) */
  function stillChosen(choice: CaseChoice): boolean {
    const values = form.getValues();
    return (
      String(values.material ?? "").trim() === choice.material &&
      String(values.unit ?? "").trim() === choice.unit
    );
  }

  // Bu arada malzeme ya da birim değiştiyse (ör. koli dışı birime geçildi, alan gizlendi) eski
  // seçimin yanıtı da hatası da yazılmaz; alana bu arada GTIN yazıldıysa yanıt onu değiştirmez.
  const suggest = useMutation({
    mutationFn: (choice: CaseChoice) => suggestCaseGtin(Number(choice.material)),
    onSuccess: (data, choice) => {
      if (!stillChosen(choice) || current()) return;
      if (data.gtin) {
        form.setFieldValue(field.name, data.gtin);
        applied.current = { ...choice, gtin: data.gtin };
      }
      setReason(data.gtin ? "" : data.reason);
    },
    onError: (err, choice) => {
      if (stillChosen(choice)) setReason(getErrorMessage(err));
    },
  });

  if (!isCase) return null;
  const empty = !fieldText(props, field.name);
  const canSuggest = !disabled && Boolean(material) && empty;
  return (
    <div style={style}>
      <GtinInput {...props} />
      {canSuggest && (
        <Button
          size="compact-sm"
          variant="light"
          mt={6}
          loading={suggest.isPending}
          onClick={() => suggest.mutate({ material, unit })}
        >
          {g.suggestCase}
        </Button>
      )}
      {reason && empty && (
        <Text size="xs" c="var(--status-warning)" mt={4}>
          {reason}
        </Text>
      )}
    </div>
  );
}
