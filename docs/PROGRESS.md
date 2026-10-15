# İlerleme

## Faz 0 — Altyapı ve çekirdek

| Adım | Durum | Not |
|---|---|---|
| 0.1 Depo yapısı | Tamamlandı (2026-10-15) | Klasör yapısı, ayarlar (django-environ), `.gitignore`, `.env.example` |
| 0.2 Docker Compose | Tamamlandı (2026-10-15) | 7 servis, nginx tek origin, `GET /api/v1/health/` + testler |
| 0.3 `core` uygulaması | Tamamlandı (2026-10-15) | User/roller, BaseModel/MasterDataModel/DocumentModel, AuditLog, belge numarası, olaylar, durum makinesi, `seed_roles`, `create_demo_users` |
| 0.4 API temeli | Tamamlandı (2026-10-15) | DRF ayarları, auth uç noktaları, `users`, `audit-log`, `/api/schema/`, `/api/docs/` |
| 0.5 Frontend iskeleti | Bekliyor | `frontend/` şu an geçici yer tutucu (düz Vite sayfası) |
| 0.6 Kalite araçları ve CI | Bekliyor | ruff/mypy/pytest ayarları `backend/pyproject.toml` içinde hazır |

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
