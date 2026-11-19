#!/usr/bin/env bash
# Docker Compose duman testi: servisler ayaktayken nginx üzerinden temel uçları dener.
# Kullanım: docker compose up -d && scripts/smoke_test.sh [taban adres]
# Önkoşul: migrate, seed_roles ve create_demo_users çalıştırılmış olmalı (README'ye bakın).
# Kişiye özel yetki adımı demo admin'le girer: geliştirme ayarında admin'e 2FA zorunlu değildir.
set -euo pipefail

BASE_URL="${1:-http://localhost}"
DEMO_PASSWORD="${DEMO_USER_PASSWORD:-Demo.12345}"
JAR="$(mktemp)"
ADMIN_JAR="$(mktemp)"
OUT="$(mktemp)"
trap 'rm -f "$JAR" "$ADMIN_JAR" "$OUT"' EXIT

fail() { echo "HATA: $*" >&2; exit 1; }
csrf_of() { awk '$6 == "csrftoken" { print $7 }' "$1"; }

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

# Müşteri ve tedarikçi portalı (docs/plan/musteri-siparis-takibi.md §4): girişsiz istek 401,
# çalışan hesabı portal uç noktalarını açamaz (403); hesapları yalnız admin yönetir.
echo "- portal: girişsiz 401, çalışan (depo) 403"
code="$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/api/v1/portal/me/")"
[ "$code" = "401" ] || fail "girişsiz /api/v1/portal/me/ beklenen 401, gelen $code"
for path in portal/me/ portal/customer/orders/ portal/supplier/orders/ portal/accounts/; do
  code="$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" "$BASE_URL/api/v1/$path")"
  [ "$code" = "403" ] || fail "depo /api/v1/$path beklenen 403, gelen $code"
done

# Kişiye özel yetki (plan §10, 9. adım): admin Yetkiler ekranının API'siyle depodan
# "Malzeme hazırlama: Değiştirir"i kaldırır; depo'nun açık oturumu hemen etkilenir. Veritabanı
# boş olduğundan yetki olmayan bir emirle denenir: izin denetimi nesneden önce çalışır (yetkisiz
# 403, yetkili 404). Sonunda rol varsayılanına dönülür (betik yeniden çalıştırılabilir).
echo "- kişiye özel yetki: admin depodan 'Malzeme hazırlama: Değiştirir'i kaldırır"
depo_id="$(echo "$me" | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)"
[ -n "$depo_id" ] || fail "me yanıtında kullanıcı numarası yok"
echo "$me" | grep -q '"production.prep":"rvc"' || fail "depo'nun hazırlık yetkisi beklenen gibi değil"

curl -fsS -c "$ADMIN_JAR" -b "$ADMIN_JAR" -o /dev/null "$BASE_URL/api/v1/auth/csrf/"
curl -fsS -c "$ADMIN_JAR" -b "$ADMIN_JAR" -o /dev/null \
  -H "Content-Type: application/json" -H "X-CSRFToken: $(csrf_of "$ADMIN_JAR")" \
  -d "{\"username\": \"admin\", \"password\": \"$DEMO_PASSWORD\"}" \
  "$BASE_URL/api/v1/auth/login/" || fail "admin girişi başarısız (2FA kapalı geliştirme ayarı gerekir)"

save_access() {   # $1: overrides JSON dizisi, $2: gerekçe
  local version code
  version="$(curl -fsS -b "$ADMIN_JAR" "$BASE_URL/api/v1/users/$depo_id/access/" \
    | grep -o '"version":"[0-9a-f]*"' | head -1)"
  [ -n "$version" ] || fail "yetki matrisinde sürüm belirteci yok"
  code="$(curl -s -o "$OUT" -w '%{http_code}' -b "$ADMIN_JAR" -X PUT \
    -H "Content-Type: application/json" -H "X-CSRFToken: $(csrf_of "$ADMIN_JAR")" \
    -d "{$version, \"overrides\": $1, \"note\": \"$2\"}" \
    "$BASE_URL/api/v1/users/$depo_id/access/")"
  [ "$code" = "200" ] || fail "yetki kaydı beklenen 200, gelen $code: $(cat "$OUT")"
  grep -q '"saved":true' "$OUT" || fail "yetki kaydedilmedi: $(cat "$OUT")"
}
save_access '[{"key": "production.prep", "level": "change", "effect": "revoke"}]' \
  "Duman testi: hazırlık yetkisi kaldırıldı"

code="$(curl -s -o "$OUT" -w '%{http_code}' -b "$JAR" -X POST -H "X-CSRFToken: $(csrf_of "$JAR")" \
  "$BASE_URL/api/v1/production/orders/0/start-prep/")"
[ "$code" = "403" ] && grep -q '"production.prep"' "$OUT" \
  || fail "hazırlık başlatma beklenen 403 (production.prep), gelen $code: $(cat "$OUT")"
code="$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" "$BASE_URL/api/v1/production/orders/")"
[ "$code" = "200" ] || fail "emir okuması açık kalmalı, gelen $code"
curl -fsS -b "$JAR" "$BASE_URL/api/v1/auth/me/" | grep -q '"production.prep":"rv"' \
  || fail "me yanıtında kaldırılan yetki görünüyor"
curl -fsS -b "$JAR" "$BASE_URL/api/v1/auth/me/access/" | grep -q '"revoked":\[{"key":"production.prep"' \
  || fail "Yetkilerim kaldırılan yetkiyi göstermiyor"
curl -fsS -b "$ADMIN_JAR" "$BASE_URL/api/v1/users/$depo_id/access/history/" \
  | grep -q 'hazırlık yetkisi kaldırıldı' || fail "geçmişte gerekçe yok"

echo "- kişiye özel yetki: rol varsayılanına dönüş"
save_access '[]' "Duman testi: rol varsayılanına döndü"
curl -fsS -b "$JAR" "$BASE_URL/api/v1/auth/me/" | grep -q '"production.prep":"rvc"' \
  || fail "yetki rol varsayılanına dönmedi"
code="$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" -X POST -H "X-CSRFToken: $(csrf_of "$JAR")" \
  "$BASE_URL/api/v1/production/orders/0/start-prep/")"
[ "$code" = "404" ] || fail "yetki dönünce beklenen 404, gelen $code"
curl -fsS -c "$ADMIN_JAR" -b "$ADMIN_JAR" -o /dev/null -X POST \
  -H "X-CSRFToken: $(csrf_of "$ADMIN_JAR")" "$BASE_URL/api/v1/auth/logout/" \
  || fail "admin çıkışı başarısız"

csrf="$(awk '$6 == "csrftoken" { print $7 }' "$JAR")"
curl -fsS -c "$JAR" -b "$JAR" -o /dev/null -X POST -H "X-CSRFToken: $csrf" \
  "$BASE_URL/api/v1/auth/logout/" || fail "çıkış başarısız"
code="$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" "$BASE_URL/api/v1/auth/me/")"
[ "$code" = "401" ] || fail "çıkıştan sonra me beklenen 401, gelen $code"

echo "Duman testi geçti."
