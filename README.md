# Deterjan ERP

Deterjan fabrikası için hammadde kabulünden sevkiyata kadar üretim takip sistemi.
Proje kuralları için [CLAUDE.md](CLAUDE.md), faz planları için [docs/plan/](docs/plan/),
ilerleme için [docs/PROGRESS.md](docs/PROGRESS.md).

## Gereksinimler

- Docker ve Docker Compose (v2)

## Kurulum ve çalıştırma

```bash
cp .env.example .env          # gerekirse şifreleri değiştirin
docker compose up -d          # db, redis, backend, worker, beat, frontend, nginx
```

- Uygulama: http://localhost/
- Sağlık kontrolü: http://localhost/api/v1/health/ → `{"status": "ok", "db": "ok", "redis": "ok"}`
- Django admin: http://localhost/admin/

## Testler ve kod kalitesi

```bash
docker compose exec backend pytest
docker compose exec backend ruff check .
docker compose exec backend ruff format --check .
```

> Bu bölüm Adım 0.6'da (kalite araçları ve CI) tamamlanacak.
