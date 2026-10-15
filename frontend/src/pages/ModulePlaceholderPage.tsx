import { IconTools } from "@tabler/icons-react";
import { MessagePage } from "../components/MessagePage";
import { tr } from "../i18n/tr";

export function ModulePlaceholderPage({ title, phase }: { title: string; phase?: number }) {
  return (
    <MessagePage
      icon={<IconTools size={48} stroke={1.4} />}
      title={title}
      text={
        phase
          ? `${tr.placeholder.comingSoon} ${tr.placeholder.plannedPhase(phase)}`
          : tr.placeholder.comingSoon
      }
    />
  );
}
