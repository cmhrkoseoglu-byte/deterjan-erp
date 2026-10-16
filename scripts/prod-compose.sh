#!/usr/bin/env bash
# Üretim compose komutlarının kısayolu. Örnekler:
#   scripts/prod-compose.sh up -d --build      # kur / güncelle (migrate otomatik çalışır)
#   scripts/prod-compose.sh ps                 # servis durumları
#   scripts/prod-compose.sh logs -f backend    # günlükler
#   scripts/prod-compose.sh exec backend python manage.py createsuperuser
#
# Şuna eşittir: docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.prod ...
# ENV_FILE ile başka bir ortam dosyası, COMPOSE_EXTRA_FILES ile (boşlukla ayrılmış) ek compose
# dosyaları verilebilir.
set -euo pipefail

cd "$(dirname "$0")/.."
ENV_FILE="${ENV_FILE:-.env.prod}"
# Konteynerlerin env_file yolu da bu değişkenden okunur (docker-compose.prod.yml).
export ENV_FILE

if [ ! -f "$ENV_FILE" ]; then
    echo "HATA: $ENV_FILE bulunamadı. Önce: scripts/init-env-prod.sh <sunucu adı> (docs/KURULUM.md)" >&2
    exit 1
fi

# Sürüm bilgisi .env.prod'da verilmemişse git'ten alınır (yedek manifestine ve hata kayıtlarına girer).
if [ -z "${APP_VERSION:-}" ] && ! grep -qE '^APP_VERSION=.+' "$ENV_FILE"; then
    APP_VERSION="$(git describe --tags --always --dirty 2>/dev/null || true)"
    export APP_VERSION
fi

files=(-f docker-compose.yml -f docker-compose.prod.yml)
for extra in ${COMPOSE_EXTRA_FILES:-}; do
    files+=(-f "$extra")
done

exec docker compose "${files[@]}" --env-file "$ENV_FILE" "$@"
