import { createTheme } from "@mantine/core";

// Tablet kullanımı: varsayılan bileşen boyutları büyük, dokunma alanları en az 44 px.
export const theme = createTheme({
  primaryColor: "blue",
  defaultRadius: "md",
  fontFamily:
    "system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans', sans-serif",
  components: {
    Button: { defaultProps: { size: "md" } },
    TextInput: { defaultProps: { size: "md" } },
    PasswordInput: { defaultProps: { size: "md" } },
    Select: { defaultProps: { size: "md" } },
  },
});
