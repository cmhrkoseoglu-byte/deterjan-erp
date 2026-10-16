#!/usr/bin/env bash
# .env.prod dosyasını .env.prod.example'dan üretir; gizli değerleri (Django anahtarı, PostgreSQL ve
# Redis şifreleri) rastgele doldurur. Var olan bir .env.prod'un üzerine YAZMAZ.
#
# Kullanım: scripts/init-env-prod.sh <sunucu adı> [ek ad ...]
#   Örnek:  scripts/init-env-prod.sh erp.firma.local 192.168.1.10
# İlk ad tarayıcıda kullanılacak adrestir (https://<ilk ad>).
set -euo pipefail

cd "$(dirname "$0")/.."
TARGET="${ENV_FILE:-.env.prod}"

if [ $# -lt 1 ]; then
    sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
fi
if [ -e "$TARGET" ]; then
    echo "HATA: $TARGET zaten var; üzerine yazılmadı. Yeniden üretmek için önce yedekleyip silin." >&2
    exit 1
fi
command -v openssl >/dev/null || {
    echo "HATA: openssl gerekli (sudo apt install openssl)" >&2
    exit 1
}

primary="$1"
names="$*"
hosts="$(printf '%s,' "$@")localhost"
origins="$(printf 'https://%s,' "$@")"
origins="${origins%,}"

secret_key="$(openssl rand -base64 96 | tr -dc 'A-Za-z0-9' | head -c 64)"
pg_password="$(openssl rand -hex 32)"
redis_password="$(openssl rand -hex 32)"

umask 077
sed \
    -e "s|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=$secret_key|" \
    -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$pg_password|" \
    -e "s|^REDIS_PASSWORD=.*|REDIS_PASSWORD=$redis_password|" \
    -e "s|^SERVER_NAME=.*|SERVER_NAME=\"$names\"|" \
    -e "s|^DJANGO_ALLOWED_HOSTS=.*|DJANGO_ALLOWED_HOSTS=$hosts|" \
    -e "s|^DJANGO_CSRF_TRUSTED_ORIGINS=.*|DJANGO_CSRF_TRUSTED_ORIGINS=$origins|" \
    .env.prod.example >"$TARGET"
chmod 600 "$TARGET"

echo "$TARGET oluşturuldu (yalnızca sahibi okuyabilir). Adres: https://$primary"
echo "Kontrol edin: firma bilgileri (COMPANY_*), INTERNAL_NETWORKS, BACKUP_* ve SENTRY_DSN."
