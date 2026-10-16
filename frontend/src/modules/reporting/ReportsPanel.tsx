import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  NumberInput,
  Pagination,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconFileSpreadsheet, IconFileTypePdf } from "@tabler/icons-react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { getErrorMessage } from "../../api/client";
import { listRecords } from "../../api/masterdata";
import {
  exportReport,
  getReport,
  listReports,
  type ColumnKind,
  type FileFormat,
  type FilterKey,
  type ReportInfo,
  type ReportParams,
} from "../../api/reporting";
import { useOptions, type Option } from "../common/useOptions";
import { Stat } from "./Dashboards";
import { defaultParams, formatValue } from "./format";
import { CHOICES, rt } from "./strings";

const PAGE_SIZE = 50;
const RIGHT: ColumnKind[] = ["number", "money", "percent", "duration"];

const RELATIONS = {
  material: "materials",
  warehouse: "warehouses",
  location: "locations",
  customer: "customers",
} as const;

function useEquipmentOptions(enabled: boolean) {
  return useQuery({
    queryKey: ["options", "equipment"],
    enabled,
    staleTime: 60_000,
    queryFn: async (): Promise<Option[]> => {
      const data = await listRecords<{ id: number; code: string; name: string }>("equipment", {
        is_active: true,
        page_size: 500,
      });
      return data.results.map((row) => ({
        value: String(row.id),
        label: `${row.code} - ${row.name}`,
      }));
    },
  });
}

function RelationFilter({
  name,
  value,
  onChange,
}: {
  name: keyof typeof RELATIONS;
  value: string | undefined;
  onChange: (value: string | undefined) => void;
}) {
  const options = useOptions({ endpoint: RELATIONS[name] });
  return (
    <Select
      label={rt.filter_[name]}
      placeholder={rt.all}
      data={options.data ?? []}
      value={value ?? null}
      onChange={(v) => onChange(v ?? undefined)}
      searchable
      clearable
      w={240}
    />
  );
}

function EquipmentFilter({
  value,
  onChange,
}: {
  value: string | undefined;
  onChange: (value: string | undefined) => void;
}) {
  const options = useEquipmentOptions(true);
  return (
    <Select
      label={rt.filter_.equipment}
      placeholder={rt.all}
      data={options.data ?? []}
      value={value ?? null}
      onChange={(v) => onChange(v ?? undefined)}
      searchable
      clearable
      w={200}
    />
  );
}

function FilterField({
  name,
  value,
  onChange,
}: {
  name: FilterKey;
  value: string | undefined;
  onChange: (value: string | undefined) => void;
}) {
  if (name === "date_from" || name === "date_to")
    return (
      <TextInput
        label={rt.filter_[name]}
        type="date"
        value={value ?? ""}
        onChange={(event) => onChange(event.currentTarget.value || undefined)}
      />
    );
  if (name in RELATIONS)
    return (
      <RelationFilter name={name as keyof typeof RELATIONS} value={value} onChange={onChange} />
    );
  if (name === "equipment") return <EquipmentFilter value={value} onChange={onChange} />;
  if (CHOICES[name])
    return (
      <Select
        label={rt.filter_[name]}
        placeholder={rt.all}
        data={CHOICES[name]}
        value={value ?? null}
        onChange={(v) => onChange(v ?? undefined)}
        clearable
        w={180}
      />
    );
  if (name === "expiring_days")
    return (
      <NumberInput
        label={rt.filter_[name]}
        value={value ?? ""}
        min={0}
        onChange={(v) => onChange(v === "" ? undefined : String(v))}
        w={180}
      />
    );
  return (
    <TextInput
      label={rt.filter_[name]}
      value={value ?? ""}
      onChange={(event) => onChange(event.currentTarget.value || undefined)}
      w={160}
    />
  );
}

/** Raporlar: rapor seç, filtrele, ekranda gör; Excel ya da PDF al. */
export function ReportsPanel() {
  const list = useQuery({ queryKey: ["reporting", "reports"], queryFn: listReports });
  const [code, setCode] = useState<string | null>(null);
  if (list.isLoading) return <Loader />;
  if (list.isError)
    return (
      <Alert color="red" variant="light">
        {getErrorMessage(list.error)}
      </Alert>
    );
  const reports = list.data ?? [];
  if (reports.length === 0) return <Text c="dimmed">{rt.noReport}</Text>;
  const report = reports.find((r) => r.code === code) ?? reports[0];
  return (
    <Stack>
      <Select
        label={rt.report}
        data={reports.map((r) => ({ value: r.code, label: r.title }))}
        value={report.code}
        allowDeselect={false}
        onChange={(value) => setCode(value)}
        w={300}
      />
      <Text size="sm" c="dimmed">
        {report.description}
      </Text>
      <ReportView key={report.code} report={report} />
    </Stack>
  );
}

function ReportView({ report }: { report: ReportInfo }) {
  const [params, setParams] = useState<ReportParams>(() => defaultParams(report));
  const [page, setPage] = useState(1);
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["reporting", "report", report.code, params, page],
    queryFn: () => getReport(report.code, { ...params, page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });
  const download = useMutation({
    mutationFn: (fileFormat: FileFormat) => exportReport(report.code, fileFormat, params),
    onSuccess: (result) => {
      if (result.kind === "job") {
        notifications.show({ color: "blue", message: rt.jobStarted });
        queryClient.invalidateQueries({ queryKey: ["reporting", "jobs"] });
      } else {
        notifications.show({ color: "green", message: rt.downloaded(result.fileName) });
      }
    },
    onError: (error) => notifications.show({ color: "red", message: getErrorMessage(error) }),
  });
  const data = query.data;
  const pages = Math.max(1, Math.ceil((data?.count ?? 0) / PAGE_SIZE));
  const set = (name: FilterKey) => (value: string | undefined) => {
    setParams((current) => ({ ...current, [name]: value }));
    setPage(1);
  };
  return (
    <Stack>
      <Group align="flex-end" wrap="wrap">
        {report.filters.map((name) => (
          <FilterField key={name} name={name} value={params[name]} onChange={set(name)} />
        ))}
      </Group>
      <Group>
        <Button
          leftSection={<IconFileSpreadsheet size={16} />}
          variant="light"
          loading={download.isPending && download.variables === "xlsx"}
          onClick={() => download.mutate("xlsx")}
        >
          {rt.excel}
        </Button>
        <Button
          leftSection={<IconFileTypePdf size={16} />}
          variant="light"
          loading={download.isPending && download.variables === "pdf"}
          onClick={() => download.mutate("pdf")}
        >
          {rt.pdf}
        </Button>
        {data && <Badge variant="outline">{rt.rows(data.count)}</Badge>}
        {data && data.count > data.sync_limit && (
          <Text size="sm" c="dimmed">
            {rt.backgroundHint(data.sync_limit)}
          </Text>
        )}
      </Group>
      {query.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(query.error)}
        </Alert>
      )}
      {data && data.summary.length > 0 && (
        <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }}>
          {data.summary.map((item) => (
            <Stat
              key={item.key}
              label={item.label}
              value={formatValue(item.value, item.kind) || "—"}
            />
          ))}
        </SimpleGrid>
      )}
      {query.isLoading && <Loader />}
      {data && (
        <Table.ScrollContainer minWidth={900}>
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                {data.columns.map((c) => (
                  <Table.Th key={c.key} ta={RIGHT.includes(c.kind) ? "right" : undefined}>
                    {c.label}
                  </Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data.results.map((row, index) => (
                <Table.Tr key={index}>
                  {data.columns.map((c) => (
                    <Table.Td key={c.key} ta={RIGHT.includes(c.kind) ? "right" : undefined}>
                      {formatValue(row[c.key] ?? null, c.kind)}
                    </Table.Td>
                  ))}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      {data && data.count === 0 && (
        <Text size="sm" c="dimmed">
          {rt.none}
        </Text>
      )}
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
    </Stack>
  );
}
