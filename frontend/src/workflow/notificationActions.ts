import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { markNotificationsRead, type AppNotification } from "../api/workflow";
import { workflowKeys } from "./queryKeys";
import { recordPath } from "./recordLinks";

/** Bildirimleri okundu işaretler (`ids` yoksa tümünü). */
export function useMarkRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (ids: number[] | undefined) => markNotificationsRead(ids),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: workflowKeys.notifications }),
  });
}

/** Bildirime tıklanınca: okundu işaretle, ilgili kayda (yoksa görev ise Görevlerim'e) git. */
export function useOpenNotification(after?: () => void) {
  const markRead = useMarkRead();
  const navigate = useNavigate();
  return (notification: AppNotification) => {
    if (!notification.is_read) markRead.mutate([notification.id]);
    const path = recordPath(notification.related) ?? (notification.task ? "/" : null);
    after?.();
    if (path) navigate(path);
  };
}
