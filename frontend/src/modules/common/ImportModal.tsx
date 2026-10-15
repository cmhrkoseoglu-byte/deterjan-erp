import {
  Alert,
  Anchor,
  Badge,
  Button,
  FileInput,
  Group,
  List,
  Modal,
  ScrollArea,
  Stack,
  Table,
  Text,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconDownload, IconFileSpreadsheet } from "@tabler/icons-react";
import { useMutation } from "@tanstack/react-query";
import axios from "axios";
import { useEffect, useState } from "react";
import { getErrorMessage } from "../../api/client";
import {
  importTemplateUrl,
  uploadImport,
  type ImportKind,
  type ImportReport,
} from "../../api/masterdata";
import { ct } from "./strings";

interface Props {
  kind?: ImportKind;
  title: string;
  opened: boolean;
  onClose: () => void;
  onImported: () => void;
  /** Ana veri dışı içe aktarmalar (ör. açılış stoku) kendi uç noktalarını verir. */
  upload?: (file: File, confirm: boolean) => Promise<ImportReport>;
  templateUrl?: string;
  intro?: string;
}

/** 400 `import_has_errors` yanıtındaki raporu çıkarır. */
function reportFromError(error: unknown): ImportReport | null {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data as { report?: ImportReport } | undefined;
    return data?.report ?? null;
  }
  return null;
}

/** Excel / CSV içe aktarma: dosya seç → önizle (satır hataları) → aktar. */
export function ImportModal({
  kind,
  title,
  opened,
  onClose,
  onImported,
  upload: uploadFn,
  templateUrl,
  intro,
}: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (opened) {
      setFile(null);
      setReport(null);
      setError("");
    }
  }, [opened]);

  const upload = useMutation({
    mutationFn: ({ confirm }: { confirm: boolean }) =>
      uploadFn ? uploadFn(file!, confirm) : uploadImport(kind!, file!, confirm),
    onSuccess: (result) => {
      setError("");
      setReport(result);
      if (result.imported) {
        notifications.show({
          color: "green",
          message: ct.importDone(result.to_create, result.to_update),
        });
        onImported();
        onClose();
      }
    },
    onError: (err) => {
      const failed = reportFromError(err);
      setReport(failed);
      setError(failed ? "" : getErrorMessage(err));
    },
  });

  const hasErrors = Boolean(report && (report.invalid > 0 || report.file_errors.length > 0));
  const canConfirm = Boolean(file && report && !hasErrors && report.total > 0);

  return (
    <Modal opened={opened} onClose={onClose} title={ct.importTitle(title)} size="xl">
      <Stack>
        <Text size="sm">{intro ?? ct.importIntro}</Text>
        <Anchor href={templateUrl ?? importTemplateUrl(kind!)} download size="sm">
          <Group gap={4}>
            <IconDownload size={16} />
            {ct.importTemplate}
          </Group>
        </Anchor>
        <FileInput
          label={ct.importFile}
          accept=".xlsx,.csv"
          leftSection={<IconFileSpreadsheet size={16} />}
          value={file}
          onChange={(value) => {
            setFile(value);
            setReport(null);
            setError("");
          }}
          clearable
        />
        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}
        {report && <ReportView report={report} hasErrors={hasErrors} />}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {ct.close}
          </Button>
          <Button
            variant="light"
            disabled={!file}
            loading={upload.isPending && !canConfirm}
            onClick={() => upload.mutate({ confirm: false })}
          >
            {ct.importPreview}
          </Button>
          <Button
            disabled={!canConfirm}
            loading={upload.isPending && canConfirm}
            onClick={() => upload.mutate({ confirm: true })}
          >
            {ct.importConfirm(report?.total ?? 0)}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function ReportView({ report, hasErrors }: { report: ImportReport; hasErrors: boolean }) {
  return (
    <Stack gap="xs">
      {report.file_errors.length > 0 ? (
        <Alert color="red" variant="light">
          <List size="sm">
            {report.file_errors.map((message) => (
              <List.Item key={message}>{message}</List.Item>
            ))}
          </List>
        </Alert>
      ) : (
        <Alert color={hasErrors ? "orange" : "green"} variant="light">
          {ct.importSummary(report.total, report.to_create, report.to_update, report.invalid)}
          {hasErrors && <Text size="sm">{ct.importHasErrors}</Text>}
        </Alert>
      )}
      {report.rows.length > 0 && (
        <ScrollArea.Autosize mah={320}>
          <Table striped verticalSpacing={4} fz="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{ct.importRow}</Table.Th>
                <Table.Th>{ct.importCode}</Table.Th>
                <Table.Th>{ct.importAction}</Table.Th>
                <Table.Th>{ct.importErrors}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {report.rows.map((row) => (
                <Table.Tr key={row.row}>
                  <Table.Td>{row.row}</Table.Td>
                  <Table.Td style={{ whiteSpace: "nowrap" }}>{row.code}</Table.Td>
                  <Table.Td miw={110}>
                    <Badge variant="light" color={row.action === "create" ? "blue" : "grape"}>
                      {row.action === "create" ? ct.importCreate : ct.importUpdate}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    {row.errors.length === 0 ? (
                      <Text size="sm" c="green">
                        {ct.importOk}
                      </Text>
                    ) : (
                      row.errors.map((e, index) => (
                        <Text key={index} size="sm" c="red">
                          {e.column ? `${e.column}: ` : ""}
                          {e.message}
                        </Text>
                      ))
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea.Autosize>
      )}
    </Stack>
  );
}
