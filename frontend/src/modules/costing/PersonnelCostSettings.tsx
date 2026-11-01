// Maliyet > Personel maliyeti ayarları: birimlerin maliyet aşaması ve işveren payı. Ücretler
// Personel > Ücretler'dedir (2026-11-01'de taşındı).
import { Button, Group, Loader, Select, Stack, Text, TextInput, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  getPersonnelCostSettings,
  listCostCenters,
  personnelCostKeys,
  setCostCenter,
  updatePersonnelCostSettings,
  type CostCenter,
  type CostCenterStage,
} from "../../api/costing";
import { normalizeDecimal, trimDecimal } from "../common/forms";
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

/** İşveren payı (%): değişince bütün ayların raporu yeni oranla okunur. */
export function EmployerRateSection() {
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: personnelCostKeys.settings,
    queryFn: getPersonnelCostSettings,
  });
  const [draft, setDraft] = useState<string | null>(null);
  const saved = settings.data ? trimDecimal(settings.data.employer_rate).replace(".", ",") : "";
  const value = draft ?? saved;
  const save = useMutation({
    mutationFn: () => updatePersonnelCostSettings(normalizeDecimal(value)),
    onSuccess: (data) => {
      notifications.show({ color: "green", message: kt.employerRateSaved });
      queryClient.setQueryData(personnelCostKeys.settings, data);
      setDraft(null);
      void queryClient.invalidateQueries({ queryKey: personnelCostKeys.all });
    },
  });
  return (
    <Stack gap="xs">
      <Title order={4}>{kt.employerRate}</Title>
      <Text size="sm" c="dimmed" maw={860}>
        {kt.employerRateHint}
      </Text>
      {settings.isError && <ErrorAlert error={settings.error} />}
      <Group align="flex-end">
        <TextInput
          label={kt.employerRateLabel}
          inputMode="decimal"
          w={160}
          value={value}
          disabled={!settings.data}
          onChange={(event) => setDraft(event.currentTarget.value)}
        />
        <Button
          onClick={() => save.mutate()}
          loading={save.isPending}
          disabled={draft === null || !draft.trim() || draft === saved}
        >
          {kt.save}
        </Button>
      </Group>
      {save.isError && <ErrorAlert error={save.error} />}
    </Stack>
  );
}
