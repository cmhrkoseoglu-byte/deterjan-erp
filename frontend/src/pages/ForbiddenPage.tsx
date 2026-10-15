import { IconLock } from "@tabler/icons-react";
import { MessagePage } from "../components/MessagePage";
import { tr } from "../i18n/tr";

export function ForbiddenPage() {
  return (
    <MessagePage
      icon={<IconLock size={48} stroke={1.4} />}
      title={tr.errors.forbiddenTitle}
      text={tr.errors.forbiddenText}
    />
  );
}
