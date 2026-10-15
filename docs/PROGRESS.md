# İlerleme

## Faz 0 — Altyapı ve çekirdek

| Adım | Durum | Not |
|---|---|---|
| 0.1 Depo yapısı | Tamamlandı (2026-10-15) | Klasör yapısı, ayarlar (django-environ), `.gitignore`, `.env.example` |
| 0.2 Docker Compose | Tamamlandı (2026-10-15) | 7 servis, nginx tek origin, `GET /api/v1/health/` + testler |
| 0.3 `core` uygulaması | Tamamlandı (2026-10-15) | User/roller, BaseModel/MasterDataModel/DocumentModel, AuditLog, belge numarası, olaylar, durum makinesi, `seed_roles`, `create_demo_users` |
| 0.4 API temeli | Tamamlandı (2026-10-15) | DRF ayarları, auth uç noktaları, `users`, `audit-log`, `/api/schema/`, `/api/docs/` |
| 0.5 Frontend iskeleti | Tamamlandı (2026-10-15) | React + TS + Mantine iskeleti, giriş, role göre menü, Türkçe biçimler; gerçek backend ile uçtan uca denendi |
| 0.6 Kalite araçları ve CI | Tamamlandı (2026-10-15) | pre-commit, servis katmanında zorunlu tip ipucu, GitHub Actions (backend, frontend, Docker Compose duman testi), README ve CLAUDE.md §9 |

### Adım 0.2 doğrulaması

- `docker compose up -d` ile 7 servis ayağa kalktı; backend, db, redis sağlık kontrolleri yeşil.
- `http://localhost/api/v1/health/` → 200 `{"status":"ok","db":"ok","redis":"ok"}`; Redis durdurulunca 503.
- `http://localhost/` frontend yer tutucusu, `/admin/` ve admin statik dosyaları nginx üzerinden açılıyor.
- `pytest` 4 test geçti; `ruff check`, `ruff format --check`, `mypy` temiz.

### Adım 0.3 ve 0.4 doğrulaması

- `pytest` 142 test geçti (konteynerde `docker compose exec backend pytest` dahil); `ruff check`,
  `ruff format --check`, `mypy` temiz; OpenAPI şeması uyarısız üretiliyor.
- Kabul kriterleri: 20 eşzamanlı `next_document_number` çağrısı tekrarsız
  (`test_document_number_concurrent_calls_are_unique`); test modeliyle oluşturma/güncelleme eski/yeni
  değerlerle günlükte (`test_save_with_audit_*`); geri alınan transaction'da handler çağrılmıyor
  (`test_handler_not_called_when_transaction_rolls_back`); yasak geçişte `BusinessRuleError`
  (`test_forbidden_transition_raises_business_rule_error`); yetkisiz rol 403
  (`test_users_list_forbidden_for_other_roles` ve diğerleri).
- `docker compose up` sonrası nginx üzerinden: `migrate`, `seed_roles`, `create_demo_users`;
  demo kullanıcıyla `csrf → login → me → logout` akışı, `/api/docs/` 200, giriş sınırı (sahte
  `X-Forwarded-For` ile de) 10 denemeden sonra 429.
- Bağımsız bir kod incelemesi yapıldı (5 açıdan, her bulgu ikinci bir gözle doğrulandı); doğrulanan
  bulgular düzeltildi ve her biri için test eklendi.

### Kurulumdan sonra (geliştirme)

```bash
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py seed_roles
docker compose exec backend python manage.py create_demo_users   # şifre: .env DEMO_USER_PASSWORD
```

Demo kullanıcı adları rol kodlarıdır: `admin`, `yonetim`, `planlama`, `depo`, `uretim`,
`laboratuvar`, `dolum`, `sevkiyat`, `satin_alma`. `admin` yönetim paneline de girer.

- **Adım 0.3'ten önce `migrate` çalıştırmayın.** Özel `User` modeli (`AUTH_USER_MODEL = "core.User"`)
  ilk migration'dan önce tanımlanmalı. Yanlışlıkla çalıştırıldıysa: `docker compose down -v`.

### Adım 0.5 doğrulaması

- `npm test` 25 test geçti (biçimler, role göre menü, giriş/çıkış/yönlendirme, 401'de oturum düşürme,
  açılışta CSRF, `csrf_failed` sonrası yenileyip tekrar deneme, 403 ve 404 sayfaları). Tipler DECISIONS.md'deki auth sözleşmesine göre yazıldı.
- `npm run lint`, `npm run format:check`, `npm run typecheck`, `npm run build` temiz.
- 390, 768 ve 1280 px genişlikte ekran görüntüsüyle kontrol edildi (sahte API ile); 768 px ve üstünde
  menü sabit, altında hamburger menü.
- Gerçek backend ile uçtan uca denendi (Adım 0.3–0.4 dalı + bu frontend, `docker compose up`, demo
  kullanıcılar): `/depo` → giriş ekranına yönlendirme, hatalı şifrede backend mesajı, `depo` girişinde menü
  yalnızca Görevlerim + Depo ve stok, `/kalite` → "Yetkiniz yok", çıkış sonrası `me` 401, `admin` tüm menüyü
  görüyor, sayfa yenilenince oturum korunuyor.

### Adım 0.6 doğrulaması

- `pre-commit run --all-files` temiz (ruff lint + biçim, Prettier, ESLint, YAML/TOML/JSON, büyük dosya,
  gizli anahtar kontrolleri). ruff sürümü `backend/pyproject.toml` ve `.pre-commit-config.yaml`'da 0.17.0'a sabit.
- `mypy`: `services.py`, `selectors.py`, `state.py` için tip ipucu zorunlu; tip ipucusuz bir fonksiyon
  eklenince hata verdiği denendi.
- `scripts/smoke_test.sh` yerelde `docker compose up` üzerinde geçti; yanlış şifreyle çalıştırılınca
  "depo girişi başarısız" diye düşüyor.
- Tarayıcıyla (Playwright) giriş: `depo` menüsü Görevlerim + Depo ve stok, `admin` tüm menü.

## Faz 0 kabul kriterleri

| Kriter | Durum | Kanıt |
|---|---|---|
| `docker compose up` sonrası `/` giriş ekranı, `/api/docs/` çalışıyor | ✓ | CI duman testi (`scripts/smoke_test.sh`) |
| Demo kullanıcılarla giriş; menü role göre değişiyor | ✓ | Duman testi (giriş + `me` rolleri), frontend testleri (`menu.test.ts`), tarayıcı denemesi |
| `next_document_number` 20 eşzamanlı çağrıda tekrarsız | ✓ | `test_document_number_concurrent_calls_are_unique` |
| Oluşturma/güncelleme `AuditLog`'a eski/yeni değerlerle | ✓ | `test_save_with_audit_*` |
| `core.events`: geri alınanda handler yok, commit'te var | ✓ | `test_handler_not_called_when_transaction_rolls_back`, `test_handler_called_after_commit` |
| `StateMachine` yasak geçişte `BusinessRuleError` | ✓ | `test_forbidden_transition_raises_business_rule_error` |
| Yetkisiz rol 403 | ✓ | `test_users_list_forbidden_for_other_roles` vb., duman testinde `depo` → `/api/v1/users/` 403 |
| CI yeşil; `ruff check`, `ruff format --check`, `mypy` temiz | ✓ | GitHub Actions `CI` iş akışı |
| `docs/PROGRESS.md` güncel | ✓ | Bu dosya |
