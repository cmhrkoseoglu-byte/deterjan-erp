// Ana veri formlarındaki GS1 GTIN alanları: mamulde "GTIN öner", KOLI dönüşümünde koli GTIN'i.
// Kilit (lotu olan mamulün GTIN'i ve koli GTIN'i) formun `lockedBy` kuralıyla gelir: alan
// kapalıdır. Koli içi miktar değişince koli GTIN'inin kilidi kalkar (`unlockedWhen`): yeni koli
// GTIN'i girilir, eskisi eski miktarıyla arşivlenir.
import { Button, List, Text, TextInput } from "@mantine/core";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { getErrorCode, getErrorMessage } from "../../api/client";
import {
  CASE_UNIT,
  gtinSuggestionKey,
  listRecords,
  suggestCaseGtin,
  suggestGtin,
  type Material,
  type RetiredGtin,
  type Unit,
} from "../../api/masterdata";
import { formatDate, formatNumber } from "../../i18n/format";
import { tr } from "../../i18n/tr";
import type { FieldComponentProps } from "../common/forms";

const g = {
  suggest: "GTIN öner",
  suggestCase: "Koli GTIN'i öner",
  refreshed: (taken: string, next: string) =>
    `${taken} başka bir malzemede ya da koli dönüşümünde kayıtlı. Yerine sıradaki önerilen GTIN ${next} yazıldı; kontrol edip yeniden kaydedin.`,
  packChanged: (old: string) =>
    `Koli içi miktar değişince yeni koli GTIN'i gerekir (GS1). Eski GTIN ${old} eski miktarıyla arşivlenir; depodaki eski koliler okutulmaya devam eder.`,
  retired: "Eski koli GTIN'leri:",
  retiredRow: (gtin: string, units: string, changedOn: string) =>
    `${gtin} · ${units} · ${changedOn} değişti`,
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

// Bulunma eki yılın okunuşundaki son sözcüğe uyar: birler hanesi (bir, iki, üç … dokuz), o sıfırsa
// onlar hanesi (on, yirmi … doksan); yüz ve bin "de" alır.
const ONES_SUFFIX = ["", "de", "de", "te", "te", "te", "da", "de", "de", "da"];
const TENS_SUFFIX = ["", "da", "de", "da", "ta", "de", "ta", "te", "de", "da"];

/** Tarih, bulunma ekiyle (İstanbul saatiyle): "05.11.2026'da", "12.03.2027'de", "01.12.2025'te". */
function onDate(value: string): string {
  const date = formatDate(value);
  if (!date) return "";
  const year = Number(date.slice(-4));
  const suffix = ONES_SUFFIX[year % 10] || TENS_SUFFIX[Math.floor(year / 10) % 10] || "de";
  return `${date}'${suffix}`;
}

/**
 * Eski koli GTIN'leri (en yeniden eskiye): GTIN, o GTIN'deki koli içi miktar ve değiştiği gün.
 * Salt okunur; arşivdeki GTIN bir daha hiçbir ürüne ya da koliye verilmez.
 */
function RetiredGtinList({ rows, baseUnit }: { rows: RetiredGtin[]; baseUnit: string }) {
  const titleId = useId();
  return (
    <div>
      <Text id={titleId} size="xs" c="dimmed" mt={6}>
        {g.retired}
      </Text>
      <List aria-labelledby={titleId} size="xs" c="dimmed" listStyleType="none" spacing={2}>
        {rows.map((row) => (
          <List.Item key={row.gtin}>
            {g.retiredRow(
              row.gtin,
              tr.scan.caseUnits(formatNumber(row.factor_to_base), baseUnit),
              onDate(row.retired_at),
            )}
          </List.Item>
        ))}
      </List>
    </div>
  );
}

/**
 * Koli GTIN'i: yalnızca birimi KOLI olan dönüşümde görünür (koli dışı birime geçilince yazılan
 * değer silinir). Mamul seçiliyse ve alan boşsa "Koli GTIN'i öner" mamulün GTIN'inden türetilen
 * ilk boş GTIN-14'ü yazar; türetilemezse nedeni gösterilir. Hammadde, ambalaj ve yarı mamulde
 * öneri yoktur: GTIN tedarikçinindir, koli GTIN'i tedarikçinin koli etiketinden girilir. Önerilen
 * GTIN o malzemenin GTIN'inden türetilir: malzeme ya da birim değişince alanda duruyorsa silinir
 * (kullanıcının yazdığı GTIN kalır).
 *
 * Lotu olan mamulde alan kilitlidir; koli içi miktar değişince (`unlocked`) alan açılır, boşalır ve
 * zorunlu olur: yeni koli GTIN'i girilir ya da önerilir, eskisi eski miktarıyla arşivlenir.
 * Kayıttaki miktara dönülünce alan kayıttaki GTIN'le yeniden kilitlenir. Düzenlemede eski koli
 * GTIN'leri alanın altında listelenir.
 */
export function CaseGtinField(props: FieldComponentProps) {
  const { field, form, record, disabled, unlocked, style } = props;
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
  // Öneri yalnız mamulde: düzenlemede tür kayıttan, yeni kayıtta seçilen malzemenin türü listeden
  // okunur (birim kodu gibi; seçim değişince yeni istek yapılmaz).
  const materials = useQuery({
    queryKey: ["options", "materials", "types"],
    queryFn: async () =>
      (await listRecords<Material>("materials", { is_active: true, page_size: 500 })).results,
    enabled: !record,
    staleTime: 60_000,
  });
  const materialType = record
    ? String(record.material_type ?? "")
    : materials.data?.find((row) => String(row.id) === material)?.material_type;
  const finished = materialType === "FINISHED";
  const [reason, setReason] = useState("");
  // "Koli GTIN'i öner"in alana yazdığı GTIN ve türetildiği seçim (malzeme, birim).
  const applied = useRef<(CaseChoice & { gtin: string }) | null>(null);
  // Kilidin son durumu: alan yalnızca kilit açılıp kapanınca boşalır ya da kayıttaki GTIN'e döner.
  const wasUnlocked = useRef(unlocked);
  const savedGtin = String(record?.gtin ?? "");

  /** Alandaki güncel GTIN (`form.values` çizimdeki değerdir; güncel değer okunur). */
  function current(): string {
    return String(form.getValues()[field.name] ?? "").trim();
  }

  useEffect(() => {
    // Koli içi miktar değişti: kayıttaki GTIN alandan kalkar, yeni koli GTIN'i istenir. Kayıttaki
    // miktara dönüldü: alan kayıttaki GTIN'le yeniden kilitlenir. Önceki öneri ve nedeni unutulur
    // (bu arada gelen öneri yanıtı dolu alana yazılmaz).
    if (wasUnlocked.current === unlocked) return;
    wasUnlocked.current = unlocked;
    applied.current = null;
    setReason("");
    form.setFieldValue(field.name, unlocked ? "" : savedGtin);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- yalnızca kilit açılıp kapanınca
  }, [unlocked]);

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
  const canSuggest = !disabled && finished && Boolean(material) && empty;
  // Koli içi miktar değişti: yeni koli GTIN'i zorunlu, açıklama eski GTIN'in ne olacağını söyler.
  const input = unlocked
    ? { ...field, required: true, description: g.packChanged(savedGtin) }
    : field;
  const retired = (record?.retired_gtins as RetiredGtin[] | undefined) ?? [];
  return (
    <div style={style}>
      <GtinInput {...props} field={input} />
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
      {retired.length > 0 && (
        <RetiredGtinList rows={retired} baseUnit={String(record?.base_unit_code ?? "")} />
      )}
    </div>
  );
}
