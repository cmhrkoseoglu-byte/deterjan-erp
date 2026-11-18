import { Button, Group, Modal, Text } from "@mantine/core";
import { useEffect, type ReactNode } from "react";
import { useBlocker } from "react-router-dom";

export interface UnsavedPromptText {
  title: string;
  text: string;
  stay: string;
  leave: string;
}

const DEFAULT_TEXT: UnsavedPromptText = {
  title: "Kaydedilmemiş değişiklikler",
  text: "Yaptığınız değişiklikler kaydedilmedi. Sayfadan çıkılsın mı?",
  stay: "Sayfada kal",
  leave: "Değişiklikleri at ve çık",
};

/**
 * Kaydedilmemiş değişiklik varken sayfadan çıkarken sorar (uygulama içi geçiş ve sekmeyi kapatma /
 * yenileme). Yalnız adresin yolu değişince sorulur; aynı sayfadaki sekme (`?sekme=`) değişimi
 * sormaz. Döndürdüğü pencere sayfada çizilmelidir.
 */
export function useUnsavedChangesPrompt(
  dirty: boolean,
  text: UnsavedPromptText = DEFAULT_TEXT,
): ReactNode {
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      dirty && currentLocation.pathname !== nextLocation.pathname,
  );

  useEffect(() => {
    if (!dirty) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  return (
    <Modal
      opened={blocker.state === "blocked"}
      onClose={() => blocker.reset?.()}
      title={text.title}
      centered
    >
      <Text size="sm">{text.text}</Text>
      <Group justify="flex-end" mt="md">
        <Button variant="default" onClick={() => blocker.reset?.()}>
          {text.stay}
        </Button>
        <Button color="red" onClick={() => blocker.proceed?.()}>
          {text.leave}
        </Button>
      </Group>
    </Modal>
  );
}
