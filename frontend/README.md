# Frontend

Vite + React + TypeScript, Mantine 7, React Router, TanStack Query, axios.

## Komutlar

```bash
npm install
npm run dev           # geliştirme sunucusu (docker compose içinde nginx arkasında: http://localhost/)
npm test              # Vitest
npm run lint          # ESLint
npm run format:check  # Prettier
npm run typecheck     # tsc
npm run build         # üretim derlemesi (dist/)
```

## Yapı

```
src/
  api/          axios istemcisi (session + CSRF), auth çağrıları, tipler
  auth/         AuthProvider, RequireAuth, RequireRole, rol yardımcıları
  layout/       AppShell (sol menü + üst bar), menü yapılandırması (menu.ts)
  pages/        LoginPage, HomePage, yer tutucu/hata sayfaları
  components/   ortak bileşenler
  i18n/         Türkçe metinler (tr.ts) ve sayı/tarih biçimleri (format.ts)
```

- Kullanıcıya görünen tüm metinler `src/i18n/tr.ts` içindedir.
- Menü ve modül rotaları `src/layout/menu.ts`'den üretilir; her öğe hangi rollere açık olduğunu taşır.
  Menüyü gizlemek yetki değildir, asıl kontrol backend'dedir (CLAUDE.md §4.12).
- Sayı ve tarihler için `formatNumber`, `formatMoney`, `formatDate`, `formatDateTime` kullanın
  (`1.234,56`, `15.10.2026`, saat dilimi Europe/Istanbul).
