// Maliyet > Personel maliyeti ayarları: birimlerin maliyet aşaması. Ücretler Personel >
// Ücretler'de, işveren payının yerini alan bordro parametreleri Personel > Bordro'dadır.
import { Loader, Select, Stack, Text, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  listCostCenters,
  personnelCostKeys,
  setCostCenter,
  type CostCenter,
  type CostCenterStage,
} from "../../api/costing";
import { stageLabel } from "./personnelCostFormat";
import { ErrorAlert, ReportTable } from "./ReportTable";
import { kt } from "./strings";

// Select boş değer taşımaz: genel gider arayüzde "GENERAL", API'de boş.
const GENERAL = "GENERAL";
const STAGE_OPTIONS = (["", "PRODUCTION", "FILLING"] as CostCenterStage[]).map((stage) => ({
  value: stage || GENERAL,
  label: stageLabel(stage),
}));

/** Birimin maliyet aşaması: eşleştirme değişince rapor ve birimler yeniden okunur. */
export function CostCentersSection() {
  const queryClient = useQueryClient();
  const centers = useQuery({ queryKey: personnelCostKeys.costCenters, queryFn: listCostCenters });
  const save = useMutation({
    mutationFn: (center: CostCenter) => setCostCenter(center),
    onSuccess: () => {
      notifications.show({ color: "green", message: kt.costCenterSaved });
      for (const queryKey of [personnelCostKeys.all, personnelCostKeys.costCenters])
        void queryClient.invalidateQueries({ queryKey });
    },
  });
  return (
    <Stack gap="xs">
      <Title order={4}>{kt.costCenters}</Title>
      <Text size="sm" c="dimmed" maw={860}>
        {kt.costCentersHint}
      </Text>
      {centers.isError && <ErrorAlert error={centers.error} />}
      {save.isError && <ErrorAlert error={save.error} />}
      {centers.isLoading ? (
        <Loader size="sm" />
      ) : (
        <ReportTable
          rows={centers.data ?? []}
          rowKey={(center) => center.department}
          minWidth={420}
          cells={[
            { label: kt.department, render: (center) => center.department },
            {
              label: kt.stage,
              render: (center) => (
                <Select
                  aria-label={`${kt.stage}: ${center.department}`}
                  data={STAGE_OPTIONS}
                  value={center.stage || GENERAL}
                  allowDeselect={false}
                  disabled={save.isPending}
                  w={220}
                  onChange={(value) => {
                    if (!value || value === (center.stage || GENERAL)) return;
                    const stage = (value === GENERAL ? "" : value) as CostCenterStage;
                    save.mutate({ department: center.department, stage });
                  }}
                />
              ),
            },
          ]}
        />
      )}
    </Stack>
  );
}
