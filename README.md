# Deterjan ERP

Deterjan fabrikası için hammadde kabulünden sevkiyata kadar üretim takip sistemi.
Proje kuralları için [CLAUDE.md](CLAUDE.md), faz planları için [docs/plan/](docs/plan/),
ilerleme için [docs/PROGRESS.md](docs/PROGRESS.md).

## Gereksinimler

- Docker ve Docker Compose (v2)
- Docker dışında geliştirme için (isteğe bağlı): Python 3.12, Node.js 22, PostgreSQL 16, Redis 7

## Kurulum ve çalıştırma

```bash
cp .env.example .env          # gerekirse şifreleri değiştirin
docker compose up -d          # db, redis, backend, worker, beat, frontend, nginx

# İlk kurulumda (ve yeni migration geldiğinde)
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py seed_roles
docker compose exec backend python manage.py create_demo_users   # yalnızca geliştirme
```

- Uygulama (giriş ekranı): http://localhost/
- API dokümantasyonu: http://localhost/api/docs/ (şema: `/api/schema/`)
- Sağlık kontrolü: http://localhost/api/v1/health/ → `{"status": "ok", "db": "ok", "redis": "ok"}`
- Django admin: http://localhost/admin/

Demo kullanıcı adları rol kodlarıdır (`admin`, `yonetim`, `planlama`, `depo`, `uretim`,
`laboratuvar`, `dolum`, `sevkiyat`, `satin_alma`); şifre `.env` içindeki `DEMO_USER_PASSWORD`.

## Üretim kurulumu

Fabrika sunucusuna (ya da bulut sunucusuna) HTTPS, yedekleme ve izleme ile kurulum:
[docs/KURULUM.md](docs/KURULUM.md). Kısaca:

```bash
scripts/gen-selfsigned-cert.sh erp.firma.local     # ya da firma/Let's Encrypt sertifikası
scripts/init-env-prod.sh erp.firma.local           # .env.prod (rastgele gizli değerlerle)
scripts/prod-compose.sh up -d --build --wait       # migrate otomatik çalışır
scripts/backup.sh --test                           # elle yedek + geri yükleme testi
```

## Testler ve kod kalitesi

Backend (konteyner içinde):

```bash
docker compose exec backend pytest                  # testler (PostgreSQL üzerinde)
docker compose exec backend ruff check .            # lint
docker compose exec backend ruff format --check .   # biçim (düzeltmek için: ruff format .)
docker compose exec backend mypy                    # tip denetimi
```

Frontend:

```bash
cd frontend
npm ci
npm test                 # Vitest
npm run lint             # ESLint
npm run format:check     # Prettier (düzeltmek için: npm run format)
npm run typecheck        # tsc
npm run build            # üretim derlemesi
```

Uçtan uca duman testi (servisler ayaktayken; giriş, rol koruması ve `/api/docs/` dahil):

```bash
scripts/smoke_test.sh
```

### pre-commit kancaları

Her commit'ten önce ruff (lint + biçim), Prettier, ESLint ve genel dosya kontrollerini çalıştırır.

```bash
pip install pre-commit        # ya da backend dev bağımlılıklarıyla gelir
pre-commit install            # bir kez
pre-commit run --all-files    # elle, tüm dosyalarda
```

Frontend kancaları için `frontend/node_modules` kurulu olmalı (`cd frontend && npm ci`).

### Sürekli entegrasyon

`.github/workflows/ci.yml` her pull request'te ve `main`'e her push'ta beş iş çalıştırır:

- **Backend:** PostgreSQL 16 ve Redis servis konteynerleriyle `ruff check`, `ruff format --check`,
  `mypy`, eksik migration kontrolü, `pytest`.
- **Frontend:** `lint`, `format:check`, `typecheck`, `test`, `build`.
- **Duman testi:** `docker compose up`, migration ve demo kullanıcılar, ardından `scripts/smoke_test.sh`.
- **Üretim kurulumu duman testi:** iç CA sertifikası, rastgele `.env.prod`, üretim imajları,
  `scripts/prod_smoke_test.sh` (HTTPS, güvenlik başlıkları, giriş, yedek ve geri yükleme testi).
- **Güvenlik taramaları:** gitleaks (tüm git geçmişi), `pip-audit` (backend bağımlılıkları),
  `npm audit --omit=dev --audit-level=high` (frontend).

`mypy` tüm `apps/` klasörünü denetler; `services.py`, `selectors.py` ve `state.py` dosyalarında tip
ipucu eksik fonksiyon hata sayılır.
