import { api } from "./client";

export interface SiteInfo {
  /** Eğitim ortamı: demo veri; her ekranda uyarı şeridi gösterilir. */
  training_mode: boolean;
}

/** Ortam bilgisi; giriş gerektirmez. */
export async function fetchSiteInfo(): Promise<SiteInfo> {
  const { data } = await api.get<SiteInfo>("/site/");
  return data;
}
