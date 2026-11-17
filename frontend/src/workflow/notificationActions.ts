import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { markNotificationsRead, type AppNotification } from "../api/workflow";
import { useAuth } from "../auth/AuthContext";
import { workflowKeys } from "./queryKeys";
import { EVENT_ROUTES, openableRecordPath } from "./recordLinks";

/** Bildirimleri okundu işaretler (`ids` yoksa tümünü). */
export function useMarkRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (ids: number[] | undefined) => markNotificationsRead(ids),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: workflowKeys.notifications }),
  });
}

/**
 * Bildirime tıklanınca: okundu işaretle, ilgili kayda (kişi açamıyorsa ya da kayıt yoksa, olayın
 * sayfasına, ör. "Yetkileriniz güncellendi" → Yetkilerim; görev ise Görevlerim'e) git (plan §5.7, §6.5,
 * §8 madde 2).
 */
export function useOpenNotification(after?: () => void) {
  const markRead = useMarkRead();
  const navigate = useNavigate();
  const { user } = useAuth();
  return (notification: AppNotification) => {
    if (!notification.is_read) markRead.mutate([notification.id]);
    const path =
      openableRecordPath(user, notification.related) ??
      EVENT_ROUTES[notification.event_name] ??
      (notification.task ? "/" : null);
    after?.();
    if (path) navigate(path);
  };
}
