import { IconMapOff } from "@tabler/icons-react";
import { MessagePage } from "../components/MessagePage";
import { tr } from "../i18n/tr";

export function NotFoundPage() {
  return (
    <MessagePage
      icon={<IconMapOff size={48} stroke={1.4} />}
      title={tr.errors.notFoundTitle}
      text={tr.errors.notFoundText}
    />
  );
}
