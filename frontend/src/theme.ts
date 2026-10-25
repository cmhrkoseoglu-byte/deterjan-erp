import { Badge, createTheme, Paper, type MantineColorsTuple } from "@mantine/core";

// DentMesher tasarım dili (Desktop\DENTMESHER, static/css/main.css ve admin.css): vurgu mavisi
// #3b7eff, kayrak gri yazı ve çizgiler, Inter yazı tipi, 10/16 px köşeler; gece temasında sıcak
// kahve zemin. Yazı tipleri uygulamayla paketlenir (main.tsx); canlıdaki CSP dış kaynağa izin vermez.

/** Vurgu mavisi: 6 = DentMesher --blue (#3b7eff), 7 = --blue-dark (#2563eb). */
const blue: MantineColorsTuple = [
  "#eef4ff",
  "#dbe6ff",
  "#b6ceff",
  "#8db3ff",
  "#6a9bff",
  "#528bff",
  "#3b7eff",
  "#2563eb",
  "#1d4fd1",
  "#173fa6",
];

/**
 * Kayrak gri. Mantine'in sıra anlamları korunur: 3 kutu çizgisi (#e2e8f0), 4 alan çizgisi
 * (#cbd5e1), 5 yer tutucu (#94a3b8), 6 soluk yazı (#64748b).
 */
const gray: MantineColorsTuple = [
  "#f8fafc",
  "#f1f5f9",
  "#e9eef5",
  "#e2e8f0",
  "#cbd5e1",
  "#94a3b8",
  "#64748b",
  "#475569",
  "#334155",
  "#1e293b",
];

/**
 * Gece paleti: DentMesher'ın gece zemini (sıcak kahve). Mantine gece temasında 0 yazı, 2 soluk
 * yazı, 3 yer tutucu, 4 çizgi, 5 üzerine gelme, 6 alan, 7 sayfa ve açılır pencere zeminidir.
 */
const dark: MantineColorsTuple = [
  "#f4ede6",
  "#d8cfc6",
  "#a39a92",
  "#7a7068",
  "#3b3029",
  "#2f241c",
  "#251a12",
  "#1c120b",
  "#150d07",
  "#0f0904",
];

const SANS = "'Inter Variable', Inter, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";

// Tablet kullanımı: varsayılan bileşen boyutları büyük, dokunma alanları en az 44 px.
export const theme = createTheme({
  primaryColor: "blue",
  primaryShade: { light: 6, dark: 6 },
  colors: { blue, gray, dark },
  black: "#0f172a",
  defaultRadius: "md",
  radius: { xs: "0.25rem", sm: "0.375rem", md: "0.625rem", lg: "1rem", xl: "1.5rem" },
  fontFamily: SANS,
  headings: { fontFamily: SANS, fontWeight: "700" },
  components: {
    Button: { defaultProps: { size: "md" } },
    TextInput: { defaultProps: { size: "md" } },
    PasswordInput: { defaultProps: { size: "md" } },
    Select: { defaultProps: { size: "md" } },
    // Kutular DentMesher kartları gibi 16 px köşeli; özel köşe verilmişse o kalır.
    Paper: Paper.extend({
      vars: (_theme, props) => ({
        root: {
          "--paper-radius":
            props.radius === undefined || props.radius === "md"
              ? "var(--mantine-radius-lg)"
              : undefined,
        },
      }),
    }),
    // Durum etiketleri tablo sütununda ya da satırda yer daraldığında "ONAY BEKLİ…" gibi
    // kesilmesin; yanındaki metin daralır ya da kaydırılır (Mantine Badge varsayılanı, içerik
    // gizli taştığı için en dar genişliğe kadar küçülmektir). DentMesher rozetleri gibi hap
    // biçimli ve büyük harfe çevrilmeden yazılır.
    Badge: Badge.extend({
      defaultProps: { radius: "xl" },
      styles: {
        root: {
          flexShrink: 0,
          minWidth: "max-content",
          textTransform: "none",
          letterSpacing: "0.01em",
        },
      },
    }),
  },
});
