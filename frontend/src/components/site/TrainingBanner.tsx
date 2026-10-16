import { Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { fetchSiteInfo } from "../../api/site";
import { tr } from "../../i18n/tr";

/**
 * Eğitim ortamında her ekranın altında sabit duran turuncu şerit. Kullanıcı eğitim sunucusunu
 * canlı sistemle karıştırıp gerçek kayıt girmesin diye; tıklamaları engellemez.
 */
export function TrainingBanner() {
  const { data } = useQuery({
    queryKey: ["site-info"],
    queryFn: fetchSiteInfo,
    staleTime: Infinity,
    retry: false,
  });
  if (!data?.training_mode) return null;
  return (
    <Text
      role="status"
      size="sm"
      fw={700}
      ta="center"
      c="white"
      bg="orange.7"
      py={4}
      style={{
        position: "fixed",
        left: 0,
        right: 0,
        bottom: 0,
        zIndex: 1000,
        pointerEvents: "none",
      }}
    >
      {tr.site.trainingBanner}
    </Text>
  );
}
