// Tablet ekranlarında ortak barkod okutma alanı (Adım 2.3).
//
// Okuyucu (klavye gibi çalışır) kodu yazıp Enter gönderir; kod sunucuda çözülür
// (LOT:/LOC:/MAT: önekleri, GS1-128, Faz 1'de basılmış düz lot numaraları) ve ilgili geri çağrı
// çalışır. `expectedMaterial` verilirse başka malzemenin lotu okutulduğunda sesli ve kırmızı uyarı.
//
//   <ScanInput expect="lot" expectedMaterial={{ id, code }} onLot={(lot) => ...} />
import { Alert, Group, Loader, Text, TextInput, type TextInputProps } from "@mantine/core";
import { IconAlertTriangle, IconBarcode, IconCheck } from "@tabler/icons-react";
import { forwardRef, useImperativeHandle, useRef, useState } from "react";
import { getErrorMessage } from "../../api/client";
import { scanCode, type ScanLot, type ScanResult } from "../../api/scan";
import { tr } from "../../i18n/tr";
import { errorFeedback, successFeedback } from "./feedback";

const t = tr.scan;

type Expect = "lot" | "location" | "any";
type ExpectedMaterial = { id: number; code: string };

export interface ScanInputHandle {
  focus: () => void;
  /** Hata gösterir (ör. sunucu okutulan lotu reddetti) ve alanı yeniden okutmaya hazırlar. */
  showError: (message: string) => void;
  clear: () => void;
}

export interface ScanInputProps {
  expect?: Expect;
  /** Beklenen malzeme ya da malzemeler (ör. ambalaj reçetesindeki kalemler). */
  expectedMaterial?: ExpectedMaterial | ExpectedMaterial[] | null;
  onLot?: (lot: ScanLot, result: ScanResult) => void;
  onLocation?: (location: NonNullable<ScanResult["location"]>, result: ScanResult) => void;
  onResult?: (result: ScanResult) => void;
  label?: string;
  placeholder?: string;
  size?: TextInputProps["size"];
  autoFocus?: boolean;
  disabled?: boolean;
}

function describe(result: ScanResult): string {
  if (result.location) return `${result.location.code} - ${result.location.name}`;
  if (result.lots.length === 1) {
    const lot = result.lots[0];
    return `${lot.lot_no} · ${lot.material_code} - ${lot.material_name}`;
  }
  if (result.material) return `${result.material.code} - ${result.material.name}`;
  return result.code;
}

export const ScanInput = forwardRef<ScanInputHandle, ScanInputProps>(function ScanInput(
  {
    expect = "any",
    expectedMaterial,
    onLot,
    onLocation,
    onResult,
    label = t.label,
    placeholder = t.placeholder,
    size = "lg",
    autoFocus,
    disabled,
  },
  ref,
) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [warning, setWarning] = useState(false);
  const [done, setDone] = useState("");

  function fail(message: string, wrongMaterial = false) {
    setError(message);
    setWarning(wrongMaterial);
    setDone("");
    errorFeedback();
    inputRef.current?.select();
  }

  useImperativeHandle(ref, () => ({
    focus: () => inputRef.current?.focus(),
    showError: (message: string) => {
      fail(message);
      inputRef.current?.focus();
    },
    clear: () => {
      setValue("");
      setError("");
      setDone("");
    },
  }));

  function accept(result: ScanResult, message: string) {
    setError("");
    setWarning(false);
    setDone(message);
    setValue("");
    successFeedback();
    onResult?.(result);
  }

  async function submit() {
    const code = value.trim();
    if (!code || busy) return;
    setBusy(true);
    let result: ScanResult;
    try {
      result = await scanCode(code);
    } catch (err) {
      setBusy(false);
      fail(getErrorMessage(err));
      return;
    } finally {
      setBusy(false);
    }

    if (expect === "location") {
      if (!result.location) return fail(t.notLocation);
      accept(result, describe(result));
      onLocation?.(result.location, result);
      return;
    }
    if (expect === "lot") {
      if (result.lots.length === 0) return fail(t.notLot);
      let lots = result.lots;
      const expected = expectedMaterial
        ? Array.isArray(expectedMaterial)
          ? expectedMaterial
          : [expectedMaterial]
        : [];
      if (expected.length) {
        const ids = new Set(expected.map((m) => m.id));
        lots = lots.filter((lot) => ids.has(lot.material));
        if (lots.length === 0) {
          const found = result.lots.map((lot) => lot.material_code).join(", ");
          const wanted = expected.map((m) => m.code).join(", ");
          return fail(t.wrongMaterial(wanted, found), true);
        }
      }
      if (lots.length > 1) return fail(t.multipleLots);
      accept(result, describe({ ...result, lots }));
      onLot?.(lots[0], result);
      return;
    }
    accept(result, describe(result));
    if (result.location) onLocation?.(result.location, result);
    if (result.lots.length === 1) onLot?.(result.lots[0], result);
  }

  return (
    <div>
      <TextInput
        ref={inputRef}
        size={size}
        label={label}
        placeholder={placeholder}
        autoFocus={autoFocus}
        disabled={disabled}
        autoComplete="off"
        leftSection={<IconBarcode size={20} />}
        rightSection={busy ? <Loader size="xs" /> : null}
        value={value}
        error={error ? true : undefined}
        onChange={(event) => {
          setValue(event.currentTarget.value);
          if (error) setError("");
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            void submit();
          }
        }}
        data-testid="scan-input"
      />
      {error && (
        <Alert
          mt="xs"
          color="red"
          variant={warning ? "filled" : "light"}
          icon={<IconAlertTriangle size={20} />}
          role="alert"
          data-testid="scan-error"
        >
          {error}
        </Alert>
      )}
      {!error && done && (
        <Group gap={4} mt={4}>
          <IconCheck size={16} color="var(--mantine-color-green-7)" />
          <Text size="sm" c="green.8" data-testid="scan-ok">
            {done}
          </Text>
        </Group>
      )}
    </div>
  );
});
