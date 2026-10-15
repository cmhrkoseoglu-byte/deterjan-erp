import { Center, Loader } from "@mantine/core";
import { tr } from "../i18n/tr";

export function LoadingScreen() {
  return (
    <Center h="100vh" aria-label={tr.common.loading}>
      <Loader size="lg" />
    </Center>
  );
}
