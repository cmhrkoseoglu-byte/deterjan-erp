import { SegmentedControl, Stack } from "@mantine/core";
import { useSearchParams } from "react-router-dom";
import { PortalAccountsPanel } from "./PortalAccountsPanel";
import { UsersPanel } from "./UsersPanel";

/**
 * Sistem > Kullanıcılar: çalışan kullanıcılar ya da müşteri ve tedarikçi portal hesapları
 * (docs/plan/musteri-siparis-takibi.md §4.2). Seçim adreste (`?tur=portal`).
 */
export function UsersTab() {
  const [params, setParams] = useSearchParams();
  const portal = params.get("tur") === "portal";
  return (
    <Stack>
      <SegmentedControl
        value={portal ? "portal" : "staff"}
        onChange={(value) =>
          setParams(value === "portal" ? { tur: "portal" } : {}, { replace: true })
        }
        data={[
          { value: "staff", label: "Çalışanlar" },
          { value: "portal", label: "Portal hesapları" },
        ]}
        w="fit-content"
      />
      {portal ? <PortalAccountsPanel /> : <UsersPanel />}
    </Stack>
  );
}
