import { MantineProvider } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { AuthProvider } from "./auth/AuthProvider";
import { TrainingBanner } from "./components/site/TrainingBanner";
import { routes } from "./routes";
import { theme } from "./theme";

const router = createBrowserRouter(routes);

export function App() {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
      }),
  );
  return (
    // Gündüz varsayılan (DentMesher gibi); gece kullanıcının seçimidir ve tarayıcıda saklanır.
    <MantineProvider theme={theme} defaultColorScheme="light">
      <Notifications />
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <RouterProvider router={router} />
          <TrainingBanner />
        </AuthProvider>
      </QueryClientProvider>
    </MantineProvider>
  );
}
