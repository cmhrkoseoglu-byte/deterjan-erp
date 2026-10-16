import { Button, Stack } from "@mantine/core";
import { IconBug } from "@tabler/icons-react";
import { useEffect } from "react";
import { isRouteErrorResponse, useRouteError } from "react-router-dom";
import { MessagePage } from "../components/MessagePage";
import { reportClientError } from "../errors/clientErrors";
import { tr } from "../i18n/tr";
import { NotFoundPage } from "./NotFoundPage";

/** Yönlendiricinin hata sınırı: beklenmeyen ekran hatasını bildirir ve Türkçe mesaj gösterir. */
export function RouteErrorPage() {
  const error = useRouteError();
  const notFound = isRouteErrorResponse(error) && error.status === 404;
  useEffect(() => {
    if (!notFound) reportClientError(error);
  }, [error, notFound]);
  if (notFound) return <NotFoundPage />;
  return (
    <Stack>
      <MessagePage
        icon={<IconBug size={48} stroke={1.4} />}
        title={tr.errors.crashTitle}
        text={tr.errors.crashText}
      />
      <Button variant="subtle" onClick={() => window.location.reload()} mx="auto">
        {tr.errors.reload}
      </Button>
    </Stack>
  );
}
