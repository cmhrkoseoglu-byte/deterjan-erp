#!/usr/bin/env bash
# Docker Compose duman testi: servisler ayaktayken nginx üzerinden temel uçları dener.
# Kullanım: docker compose up -d && scripts/smoke_test.sh [taban adres]
# Önkoşul: migrate, seed_roles ve create_demo_users çalıştırılmış olmalı (README'ye bakın).
set -euo pipefail

BASE_URL="${1:-http://localhost}"
DEMO_PASSWORD="${DEMO_USER_PASSWORD:-Demo.12345}"
JAR="$(mktemp)"
trap 'rm -f "$JAR"' EXIT

fail() { echo "HATA: $*" >&2; exit 1; }

# Servisler (özellikle frontend'in npm install'ı) hazır olana kadar bekle.
wait_for() {
  local url="$1" tries=60
  until curl -fsS -o /dev/null "$url"; do
    tries=$((tries - 1))
    [ "$tries" -gt 0 ] || fail "$url yanıt vermedi"
    sleep 5
  done
}

wait_for "$BASE_URL/api/v1/health/"
wait_for "$BASE_URL/"

echo "- sağlık kontrolü"
curl -fsS "$BASE_URL/api/v1/health/" | grep -q '"status":"ok"' || fail "health ok değil"

echo "- SPA (giriş ekranı) açılıyor"
curl -fsS "$BASE_URL/" | grep -q 'id="root"' || fail "SPA index.html gelmedi"

echo "- /api/docs/ ve /api/schema/"
curl -fsS -o /dev/null "$BASE_URL/api/docs/" || fail "/api/docs/ açılmadı"
curl -fsS -o /dev/null "$BASE_URL/api/schema/" || fail "/api/schema/ açılmadı"

echo "- demo kullanıcıyla giriş (depo): csrf -> login -> me -> logout"
curl -fsS -c "$JAR" -b "$JAR" -o /dev/null "$BASE_URL/api/v1/auth/csrf/"
csrf="$(awk '$6 == "csrftoken" { print $7 }' "$JAR")"
[ -n "$csrf" ] || fail "csrftoken çerezi gelmedi"

curl -fsS -c "$JAR" -b "$JAR" -o /dev/null \
  -H "Content-Type: application/json" -H "X-CSRFToken: $csrf" \
  -d "{\"username\": \"depo\", \"password\": \"$DEMO_PASSWORD\"}" \
  "$BASE_URL/api/v1/auth/login/" || fail "depo girişi başarısız"

me="$(curl -fsS -b "$JAR" "$BASE_URL/api/v1/auth/me/")"
echo "$me" | grep -q '"depo"' || fail "me yanıtında depo rolü yok: $me"

echo "- rol koruması: depo kullanıcısı /api/v1/users/ için 403 alıyor"
code="$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" "$BASE_URL/api/v1/users/")"
[ "$code" = "403" ] || fail "/api/v1/users/ beklenen 403, gelen $code"

csrf="$(awk '$6 == "csrftoken" { print $7 }' "$JAR")"
curl -fsS -c "$JAR" -b "$JAR" -o /dev/null -X POST -H "X-CSRFToken: $csrf" \
  "$BASE_URL/api/v1/auth/logout/" || fail "çıkış başarısız"
code="$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" "$BASE_URL/api/v1/auth/me/")"
[ "$code" = "401" ] || fail "çıkıştan sonra me beklenen 401, gelen $code"

echo "Duman testi geçti."
