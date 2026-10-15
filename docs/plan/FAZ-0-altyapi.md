# Faz 0 — Altyapı ve çekirdek

**Amaç:** Üzerine tüm modüllerin kurulacağı iskeleti hazırlamak. Bu fazın sonunda kullanıcı giriş
yapabilir, roller tanımlıdır, her kayıt denetim günlüğüne yazılır ve projede test/lint/CI çalışır.
Bu fazda iş modülü (malzeme, stok vb.) yazılmaz.

Önce `CLAUDE.md`'yi oku. Adımları sırayla uygula; her adım sonunda testler yeşil olmalı ve commit atılmalı.

---

## Adım 0.1 — Depo yapısı

```
deterjan-erp/
  CLAUDE.md
  README.md
  .env.example
  docker-compose.yml
  docker-compose.prod.yml        # (iskelet; Faz 5'te tamamlanacak)
  nginx/default.conf
  backend/
    pyproject.toml               # bağımlılıklar + ruff + pytest + mypy ayarları
    manage.py
    config/
      settings/base.py, dev.py, test.py, prod.py
      urls.py, asgi.py, wsgi.py, celery.py
    apps/
      core/
  frontend/
  docs/
    PROGRESS.md
    DECISIONS.md
    plan/
```

- `git init`, `.gitignore` (Python, Node, `.env`, medya).
- Ayarlar `django-environ` ile `.env`'den okunur.

## Adım 0.2 — Docker Compose

Servisler: `db` (postgres:16, kalıcı volume), `redis` (redis:7), `backend` (Django, geliştirmede
`runserver` / Channels için `daphne` veya `uvicorn`), `worker` (celery), `beat` (celery beat),
`frontend` (Vite dev server), `nginx` (tek origin: `/api`, `/admin`, `/ws` → backend; `/` → frontend).

- `docker compose up` ile tek komutta ayağa kalkmalı.
- `GET /api/v1/health/` → `{"status": "ok", "db": "ok", "redis": "ok"}`.

## Adım 0.3 — `core` uygulaması

### Modeller

**`User`** (`AbstractUser`'dan türet — proje başında, sonradan değiştirmek zordur)
- `full_name` (CharField), `phone` (opsiyonel), `is_active`
- Roller: Django `Group` ilişkisi. `user.has_role("depo")` yardımcı metodu.

**`BaseModel`** (abstract)
- `created_at`, `updated_at` (auto)
- `created_by`, `updated_by` (FK User, `PROTECT`, null=True — sistem işlemleri için)
- Tüm iş modelleri bundan türer.

**`MasterDataModel(BaseModel)`** (abstract): `is_active` (default True). Ana veriler için.

**`DocumentModel(BaseModel)`** (abstract): `number` (unique, CharField), `status` (CharField),
`cancelled_at`, `cancelled_by`, `cancel_reason`. Durumlu belgeler için.

**`AuditLog`**
- `timestamp`, `actor` (FK User, null), `action` (`create` | `update` | `status_change` | `cancel` | `login` | `custom`)
- `content_type` + `object_id` (GenericFK), `object_repr`
- `changes` (JSONField: `{"alan": [eski, yeni]}`), `ip_address`, `note`
- Değiştirilemez: admin'de salt okunur, API'de yalnızca okuma.

**`DocumentSequence`**
- `prefix` (ör. `UE`), `year`, `last_number`; `unique_together(prefix, year)`

### Servisler / yardımcılar

- `core.services.next_document_number(prefix: str) -> str` → `UE-2026-00001`. `select_for_update`.
  Eşzamanlı çağrıda çakışma olmadığını test et.
- `core.audit.log_change(actor, instance, action, changes=None, note="")`.
- `core.audit.diff(instance_before, instance_after) -> dict` — değişen alanları çıkarır.
- Servis katmanında kullanılmak üzere: `core.services.save_with_audit(instance, actor)` — oluşturma/güncellemede
  `created_by/updated_by` doldurur ve denetim kaydı yazar.
- `core.events`:
  - `publish(event_name: str, payload: dict, actor: User | None)` — `transaction.on_commit` ile handler'ları çağırır.
  - `subscribe(event_name: str)(handler)` dekoratörü; `"production_order.*"` gibi joker destekli.
  - Olay adları sabitleri `core/event_names.py` içinde (ör. `PRODUCTION_ORDER_APPROVED = "production_order.approved"`).
  - Handler hatası ana işlemi bozmaz; loglanır.
- `core.state.StateMachine` yardımcı sınıfı: `transitions = {"DRAFT": ["APPROVED", "CANCELLED"], ...}`;
  `assert_can_transition(from, to)`; geçersiz geçişte `BusinessRuleError("invalid_transition", ...)`.
- `core.exceptions.BusinessRuleError` + DRF exception handler (400, `{"code", "detail"}`).
- `core.permissions.HasRole("depo", "planlama")` DRF izin sınıfı.

### Yönetim komutları
- `seed_roles` — CLAUDE.md'deki 9 rolü oluşturur (idempotent).
- `create_demo_users` — her rol için bir test kullanıcısı (yalnızca dev ortamında çalışır).

## Adım 0.4 — API temeli

- DRF ayarları: session auth, `IsAuthenticated` varsayılan, sayfalama 50, `django-filter`, drf-spectacular.
- Uç noktalar:
  - `POST /api/v1/auth/login/`, `POST /api/v1/auth/logout/`, `GET /api/v1/auth/me/` (kullanıcı + roller)
  - `GET /api/v1/auth/csrf/` (SPA için CSRF çerezi)
  - `GET /api/v1/users/` (admin), `GET /api/v1/audit-log/?content_type=&object_id=` (admin, yonetim)
  - `GET /api/v1/health/`
- Login/logout denetim günlüğüne yazılır.

## Adım 0.5 — Frontend iskeleti

- Vite + React + TypeScript, Mantine, React Router, TanStack Query, `axios` (CSRF başlığı otomatik).
- Klasör yapısı:
  ```
  frontend/src/
    api/          # axios istemcisi, tipler (OpenAPI'den üretilebilir: openapi-typescript)
    auth/         # AuthProvider, RequireAuth, RequireRole
    layout/       # AppShell: sol menü (role göre), üst bar (kullanıcı, bildirim zili yeri)
    pages/        # LoginPage, HomePage ("Görevlerim" yer tutucu), NotFound
    components/   # ortak bileşenler
    i18n/         # Türkçe metinler tek dosyada
  ```
- Giriş ekranı → ana sayfa. Menü, kullanıcının rollerine göre şekillenir.
- Tablet uyumlu (en az 768 px genişlikte rahat kullanım, büyük dokunma alanları).
- Tarih/sayı biçimi Türkçe (`1.234,56`, `15.10.2026`).

## Adım 0.6 — Kalite araçları ve CI

- `ruff` (lint+format), `mypy` (en azından `apps/*/services.py`), `pytest` + `pytest-django` + `factory_boy`.
- `pre-commit` kancaları.
- GitHub Actions (ya da kullanılan CI): backend testleri PostgreSQL servis konteyneriyle, ruff, frontend
  lint + build.
- `README.md`: kurulum, çalıştırma, test komutları. `CLAUDE.md` §9'u gerçek komutlarla güncelle.

---

## Kabul kriterleri

- [ ] `docker compose up` sonrası `http://localhost/` giriş ekranı açılıyor, `/api/docs/` çalışıyor.
- [ ] Demo kullanıcılarla giriş yapılabiliyor; menü role göre değişiyor.
- [ ] `next_document_number` eşzamanlı 20 çağrıda tekrarsız numara üretiyor (test).
- [ ] Bir test modeli üzerinden: oluşturma ve güncelleme `AuditLog`'a eski/yeni değerlerle düşüyor (test).
- [ ] `core.events`: geri alınan transaction'da handler çağrılmıyor, commit edilende çağrılıyor (test).
- [ ] `StateMachine` yasak geçişte `BusinessRuleError` fırlatıyor (test).
- [ ] Yetkisiz kullanıcı rol korumalı uç noktada 403 alıyor (test).
- [ ] CI yeşil; `ruff check`, `ruff format --check`, `mypy` temiz.
- [ ] `docs/PROGRESS.md` güncel.
