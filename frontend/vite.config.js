// GEÇİCİ: Adım 0.5'te React + TypeScript + Mantine kurulumuyla değiştirilecek.
import { defineConfig } from "vite";

export default defineConfig({
  server: {
    host: true,
    port: 5173,
    allowedHosts: true,
    // nginx arkasında (port 80) HMR bağlantısı
    hmr: { clientPort: 80 },
  },
});
