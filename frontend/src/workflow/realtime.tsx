// Anlık bildirim bağlantısı: /ws/notifications/ (aynı origin, oturum çereziyle).
// Sunucu yeni bildirim ve görev değişikliğini gönderir; ilgili sorgular tazelenir. Kişinin yetkisi
// değişince (`access.changed`, plan §8 madde 11) `me` ve görevler yeniden alınır: menü, sekme ve
// düğmeler sayfa yenilenmeden güncellenir, açık sayfa artık izinli değilse "Yetkiniz yok" çıkar.
// Bağlantı yokken bildirim sayısı ve görev listesi 30 sn'de bir yoklanır (yedek).
import { notifications } from "@mantine/notifications";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { ME_QUERY_KEY } from "../auth/AuthProvider";
import { workflowKeys } from "./queryKeys";
import { RealtimeContext } from "./realtimeContext";

const MAX_RECONNECT_DELAY_MS = 30_000;

interface ServerMessage {
  type: string;
  id?: number;
  title?: string;
  body?: string;
  level?: "INFO" | "WARNING" | "CRITICAL";
}

function socketUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/notifications/`;
}

const LEVEL_COLORS = { INFO: "blue", WARNING: "orange", CRITICAL: "red" } as const;

export function RealtimeProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (typeof WebSocket === "undefined") return;
    let socket: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let attempts = 0;
    let stopped = false;
    let wasConnected = false;

    const handleMessage = (event: MessageEvent) => {
      let message: ServerMessage;
      try {
        message = JSON.parse(String(event.data)) as ServerMessage;
      } catch {
        return;
      }
      if (message.type === "notification.created") {
        void queryClient.invalidateQueries({ queryKey: workflowKeys.notifications });
        if (message.title) {
          notifications.show({
            title: message.title,
            message: message.body || "",
            color: LEVEL_COLORS[message.level ?? "INFO"],
            autoClose: 6000,
          });
        }
      } else if (message.type === "notification.read") {
        void queryClient.invalidateQueries({ queryKey: workflowKeys.notifications });
      } else if (message.type === "task.changed") {
        void queryClient.invalidateQueries({ queryKey: workflowKeys.tasks });
      } else if (message.type === "access.changed") {
        // Her şey: fiyat/maliyet gibi kaldırılan alanlar açık sayfada eski haliyle kalmasın.
        void queryClient.invalidateQueries();
      }
    };

    const connect = () => {
      socket = new WebSocket(socketUrl());
      socket.onopen = () => {
        attempts = 0;
        setConnected(true);
        // Bağlantı kopukken kaçırılanlar için bir kez tazele (yetki değişikliği dahil).
        void queryClient.invalidateQueries({ queryKey: workflowKeys.all });
        if (wasConnected) void queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY });
        wasConnected = true;
      };
      socket.onmessage = handleMessage;
      socket.onclose = () => {
        setConnected(false);
        if (stopped) return;
        attempts += 1;
        const delay = Math.min(1000 * 2 ** attempts, MAX_RECONNECT_DELAY_MS);
        retryTimer = setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      stopped = true;
      clearTimeout(retryTimer);
      socket?.close();
    };
  }, [queryClient]);

  return <RealtimeContext.Provider value={connected}>{children}</RealtimeContext.Provider>;
}
