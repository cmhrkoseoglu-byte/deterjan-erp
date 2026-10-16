import {
  ActionIcon,
  Alert,
  Button,
  Checkbox,
  Group,
  Image,
  Modal,
  Stack,
  Text,
  Textarea,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconMessageReport } from "@tabler/icons-react";
import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import { reportProblem } from "../../api/golive";
import { tr } from "../../i18n/tr";

const t = tr.problemReport;

/** Sayfanın ekran görüntüsü (JPEG). Tarayıcı izin vermezse ya da hata olursa null. */
async function captureScreen(): Promise<Blob | null> {
  try {
    const { default: html2canvas } = await import("html2canvas-pro");
    const canvas = await html2canvas(document.body, {
      scale: Math.min(1, window.devicePixelRatio || 1),
      logging: false,
      useCORS: true,
    });
    return await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.75));
  } catch {
    return null;
  }
}

/** Üst çubuktaki "Sorun bildir": ekran görüntüsü + açıklama → admin rolüne görev. */
export function ProblemReportButton() {
  const location = useLocation();
  const [opened, setOpened] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [screenshot, setScreenshot] = useState<Blob | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [attach, setAttach] = useState(true);
  const [description, setDescription] = useState("");

  useEffect(() => {
    if (!screenshot || typeof URL.createObjectURL !== "function") return;
    const url = URL.createObjectURL(screenshot);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [screenshot]);

  async function open() {
    // Görüntü modal açılmadan alınır; böylece pencere değil, sorunun olduğu ekran görünür.
    setCapturing(true);
    const blob = await captureScreen();
    setCapturing(false);
    setScreenshot(blob);
    setPreview(null);
    setAttach(Boolean(blob));
    setDescription("");
    setOpened(true);
  }

  const send = useMutation({
    mutationFn: () =>
      reportProblem({
        description,
        page_url: `${location.pathname}${location.search}`,
        page_title: document.title,
        user_agent: navigator.userAgent,
        screen: `${window.innerWidth}x${window.innerHeight}`,
        screenshot: attach ? screenshot : null,
      }),
    onSuccess: (report) => {
      notifications.show({ color: "green", message: t.sent(report.number) });
      setOpened(false);
    },
  });

  return (
    <>
      <Tooltip label={t.button}>
        <ActionIcon
          variant="subtle"
          size="xl"
          aria-label={t.button}
          onClick={() => void open()}
          loading={capturing}
        >
          <IconMessageReport size={24} />
        </ActionIcon>
      </Tooltip>
      <Modal opened={opened} onClose={() => setOpened(false)} title={t.title} size="lg">
        <Stack>
          <Text size="sm">{t.intro}</Text>
          <Textarea
            label={t.description}
            placeholder={t.placeholder}
            value={description}
            onChange={(event) => setDescription(event.currentTarget.value)}
            autosize
            minRows={4}
            required
            data-autofocus
          />
          {screenshot ? (
            <Stack gap="xs">
              <Checkbox
                label={t.attach}
                checked={attach}
                onChange={(event) => setAttach(event.currentTarget.checked)}
              />
              {attach && preview && (
                <Image src={preview} alt={t.screenshot} mah={220} fit="contain" radius="sm" />
              )}
            </Stack>
          ) : (
            <Text size="sm" c="dimmed">
              {t.noScreenshot}
            </Text>
          )}
          {send.isError && (
            <Alert color="red" variant="light">
              {getErrorMessage(send.error)}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setOpened(false)}>
              {t.cancel}
            </Button>
            <Button
              onClick={() => send.mutate()}
              loading={send.isPending}
              disabled={!description.trim()}
            >
              {t.send}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
}
