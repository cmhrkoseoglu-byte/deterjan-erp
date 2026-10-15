import { createContext, useContext } from "react";

export const POLL_INTERVAL_MS = 30_000;

/** WebSocket bağlı mı? `RealtimeProvider` (realtime.tsx) değeri sağlar. */
export const RealtimeContext = createContext(false);

/** WebSocket bağlı mı? Bağlı değilse sorgular yoklama aralığı kullanır. */
export function useRealtimeConnected(): boolean {
  return useContext(RealtimeContext);
}

/** Bağlantı yokken kullanılacak `refetchInterval` değeri (30 sn), bağlıyken kapalı. */
export function usePollInterval(): number | false {
  return useRealtimeConnected() ? false : POLL_INTERVAL_MS;
}
