#!/usr/bin/env bash
# Üretim kurulumu duman testi: servisler ayaktayken nginx üzerinden HTTPS ile dener, ardından bir
# yedek ve bir geri yükleme testi çalıştırır.
#
# Kullanım:
#   SMOKE_USER=smoke SMOKE_PASSWORD=... scripts/prod_smoke_test.sh [https://taban-adres]
# Önkoşullar:
#   - scripts/prod-compose.sh up -d --wait (migrate ve seed_roles otomatik çalışır)
#   - test kullanıcısı (create_demo_users üretimde çalışmaz), örneğin:
#       scripts/prod-compose.sh exec -T backend python manage.py shell -c "from apps.core.models \
#         import User; from django.contrib.auth.models import Group; u, _ = User.objects.get_or_create( \
#         username='smoke'); u.set_password('...'); u.save(); u.groups.add(Group.objects.get(name='depo'))"
# Ortam değişkenleri:
#   SMOKE_CA      : sunucu sertifikasını imzalayan CA (varsayılan nginx/internal-ca/ca.crt)
#   SKIP_BACKUP=1 : yedek / geri yükleme testi adımlarını atla
set -euo pipefail

cd "$(dirname "$0")/.."
BASE_URL="${1:-https://localhost}"
BASE_URL="${BASE_URL%/}"
HOST="${BASE_URL#https://}"
HOST="${HOST%%/*}"
HOST_NO_PORT="${HOST%%:*}"
HTTP_URL="http://$HOST_NO_PORT${HTTP_PORT:+:$HTTP_PORT}"
CA="${SMOKE_CA:-nginx/internal-ca/ca.crt}"
SMOKE_USER="${SMOKE_USER:-smoke}"
SMOKE_PASSWORD="${SMOKE_PASSWORD:?SMOKE_PASSWORD verin (test kullanıcısının şifresi)}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
JAR="$WORK/cookies"

fail() {
    echo "HATA: $*" >&2
    exit 1
}
ok() { echo "  ok: $*"; }
c() { curl -sS --cacert "$CA" "$@"; }
compose() { scripts/prod-compose.sh "$@"; }
command -v jq >/dev/null || fail "jq gerekli"
[ -s "$CA" ] || fail "CA sertifikası bulunamadı: $CA"

EXPECTED_CSP="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' wss://$HOST; worker-src 'self'; manifest-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"

# $1: başlık dosyası, $2: başlık adı -> değer (küçük/büyük harf duyarsız, son \r atılır)
header() {
    awk -v name="$(echo "$2" | tr '[:upper:]' '[:lower:]')" -F': ' '
        { key = tolower($1) }
        key == name { sub(/\r$/, ""); sub(/^[^:]*: /, ""); print; exit }' "$1"
}

check_security_headers() {
    local file="$1" what="$2" value
    for pair in \
        "Strict-Transport-Security|max-age=31536000" \
        "X-Content-Type-Options|nosniff" \
        "X-Frame-Options|DENY" \
        "Referrer-Policy|same-origin" \
        "Permissions-Policy|camera=(self), microphone=(), geolocation=(), payment=()" \
        "Cross-Origin-Opener-Policy|same-origin"; do
        value="$(header "$file" "${pair%%|*}")"
        [ "$value" = "${pair#*|}" ] || fail "$what: ${pair%%|*} beklenen '${pair#*|}', gelen '$value'"
    done
    value="$(header "$file" Content-Security-Policy)"
    [ "$value" = "$EXPECTED_CSP" ] || fail "$what: CSP farklı: '$value'"
    # Başlıklar tek kaynaktan (nginx) gelmeli, çift olmamalı.
    [ "$(grep -ci '^x-frame-options:' "$file")" = "1" ] || fail "$what: X-Frame-Options birden fazla"
    ok "$what: güvenlik başlıkları ve CSP tam"
}

echo "- servis bekleniyor: $BASE_URL"
tries=60
until c -fo /dev/null "$BASE_URL/api/v1/health/" 2>/dev/null; do
    tries=$((tries - 1))
    [ "$tries" -gt 0 ] || fail "$BASE_URL/api/v1/health/ yanıt vermedi"
    sleep 2
done

echo "- sağlık ve TLS"
c -f "$BASE_URL/api/v1/health/" | jq -e '.status == "ok" and .db == "ok" and .redis == "ok"' >/dev/null \
    || fail "health ok değil"
ok "health: ok (db, redis)"
for proto in tlsv1 tlsv1.1; do
    if curl -sS --cacert "$CA" --$proto --tls-max "${proto#tlsv}" -o /dev/null "$BASE_URL/" 2>/dev/null; then
        fail "eski TLS sürümü ($proto) kabul edildi"
    fi
done
ok "TLS 1.0/1.1 reddediliyor"

echo "- HTTP -> HTTPS yönlendirmesi"
code="$(curl -sS -o /dev/null -D "$WORK/h" -w '%{http_code}' "$HTTP_URL/giris?x=1")"
[ "$code" = "301" ] || fail "http beklenen 301, gelen $code"
location="$(header "$WORK/h" Location)"
[ "$location" = "https://$HOST_NO_PORT/giris?x=1" ] || fail "yönlendirme adresi beklenmedik: $location"
ok "301 -> $location"

echo "- güvenlik başlıkları"
c -f -o /dev/null -D "$WORK/h" "$BASE_URL/"
check_security_headers "$WORK/h" "/"
[ "$(header "$WORK/h" Cache-Control)" = "no-cache" ] || fail "index.html Cache-Control no-cache değil"
code="$(c -o /dev/null -D "$WORK/h" -w '%{http_code}' "$BASE_URL/api/v1/auth/me/")"
[ "$code" = "401" ] || fail "girişsiz /api/v1/auth/me/ beklenen 401, gelen $code"
check_security_headers "$WORK/h" "/api/v1/auth/me/ (401)"

echo "- SPA ve derlenmiş dosyalar"
c -f "$BASE_URL/" >"$WORK/index.html"
grep -q 'id="root"' "$WORK/index.html" || fail "SPA index.html gelmedi"
asset="$(grep -oE '/assets/[^"]+\.js' "$WORK/index.html" | head -n 1)"
[ -n "$asset" ] || fail "index.html içinde /assets/*.js yok"
c -f -o /dev/null -D "$WORK/h" "$BASE_URL$asset"
[ "$(header "$WORK/h" Cache-Control)" = "public, max-age=31536000, immutable" ] \
    || fail "$asset uzun süreli önbellek başlığı yok"
check_security_headers "$WORK/h" "$asset"
c -f -H 'Accept-Encoding: gzip' -o /dev/null -D "$WORK/h" "$BASE_URL$asset"
[ "$(header "$WORK/h" Content-Encoding)" = "gzip" ] || fail "$asset gzip ile gelmedi"
ok "SPA, /assets/ önbelleği ve gzip"
c -f "$BASE_URL/stok/bilinmeyen/sayfa" | grep -q 'id="root"' || fail "API dışı bilinmeyen yol SPA'ya düşmedi"
ok "API dışı bilinmeyen yol -> SPA (index.html)"

echo "- DEBUG=False kanıtı"
code="$(c -o "$WORK/body" -w '%{http_code}' "$BASE_URL/api/v1/xyz-yok/")"
[ "$code" = "404" ] || fail "/api/v1/xyz-yok/ beklenen 404, gelen $code"
jq -e '.code == "not_found"' "$WORK/body" >/dev/null || fail "404 yanıtı JSON değil: $(head -c 300 "$WORK/body")"
grep -qiE 'traceback|DEBUG = True|technical_404|URLconf' "$WORK/body" && fail "404'te hata ayıklama sayfası var"
ok "bilinmeyen API adresi JSON 404 (hata ayıklama sayfası yok)"

echo "- statik dosyalar (nginx, static volume)"
c -f -o "$WORK/base.css" -D "$WORK/h" "$BASE_URL/static/admin/css/base.css"
[ -s "$WORK/base.css" ] || fail "/static/admin/css/base.css boş"
[ "$(header "$WORK/h" Cache-Control)" = "public, max-age=604800" ] || fail "statik dosya nginx'ten gelmiyor"
header "$WORK/h" Content-Type | grep -q '^text/css' || fail "base.css içerik türü text/css değil"
ok "/static/admin/css/base.css nginx'ten"

echo "- bilinmeyen Host başlığı"
set +e
curl -sS --cacert "$CA" --http1.1 -o /dev/null -H 'Host: saldirgan.example' "$BASE_URL/" 2>/dev/null
rc=$?
set -e
[ "$rc" = "52" ] || fail "bilinmeyen Host için yanıt gelmemeliydi (curl çıkış kodu $rc, beklenen 52)"
ok "bilinmeyen Host -> yanıt yok (444)"

echo "- HTTPS üzerinden giriş: csrf -> login -> me -> websocket -> logout"
c -f -c "$JAR" -b "$JAR" -o /dev/null -D "$WORK/h" "$BASE_URL/api/v1/auth/csrf/"
grep -i '^set-cookie: csrftoken=' "$WORK/h" | grep -qi '; secure' || fail "csrftoken çerezi Secure değil"
csrf="$(awk '$6 == "csrftoken" { print $7 }' "$JAR")"
[ -n "$csrf" ] || fail "csrftoken çerezi gelmedi"
code="$(c -c "$JAR" -b "$JAR" -o "$WORK/body" -D "$WORK/h" -w '%{http_code}' \
    -H "Content-Type: application/json" -H "X-CSRFToken: $csrf" -H "Referer: $BASE_URL/" \
    -d "$(jq -cn --arg u "$SMOKE_USER" --arg p "$SMOKE_PASSWORD" '{username: $u, password: $p}')" \
    "$BASE_URL/api/v1/auth/login/")"
[ "$code" = "200" ] || fail "giriş başarısız ($code): $(head -c 300 "$WORK/body")"
session_cookie="$(grep -i '^set-cookie: sessionid=' "$WORK/h" || true)"
[ -n "$session_cookie" ] || fail "sessionid çerezi gelmedi"
echo "$session_cookie" | grep -qi '; secure' || fail "sessionid çerezi Secure değil"
echo "$session_cookie" | grep -qi '; httponly' || fail "sessionid çerezi HttpOnly değil"
ok "giriş; sessionid Secure + HttpOnly, csrftoken Secure"
c -f -b "$JAR" "$BASE_URL/api/v1/auth/me/" | jq -e --arg u "$SMOKE_USER" '.username == $u' >/dev/null \
    || fail "me yanıtı beklenen kullanıcı değil"
ok "/api/v1/auth/me/ -> $SMOKE_USER"
# RFC 6455'teki örnek anahtar (gizli bilgi değil)
WS_KEY="dGhlIHNhbXBsZSBub25jZQ==" # gitleaks:allow
code="$(c --http1.1 -b "$JAR" -o /dev/null -w '%{http_code}' --max-time 3 \
    -H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' \
    -H "Sec-WebSocket-Key: $WS_KEY" -H "Origin: $BASE_URL" \
    "$BASE_URL/ws/notifications/" 2>/dev/null || true)"
[ "$code" = "101" ] || fail "WebSocket (/ws/notifications/) beklenen 101, gelen $code"
ok "WebSocket yükseltmesi (101)"
csrf="$(awk '$6 == "csrftoken" { print $7 }' "$JAR")"
c -f -c "$JAR" -b "$JAR" -o /dev/null -X POST -H "X-CSRFToken: $csrf" -H "Referer: $BASE_URL/" \
    "$BASE_URL/api/v1/auth/logout/" || fail "çıkış başarısız"
code="$(c -o /dev/null -b "$JAR" -w '%{http_code}' "$BASE_URL/api/v1/auth/me/")"
[ "$code" = "401" ] || fail "çıkıştan sonra me beklenen 401, gelen $code"
ok "çıkış"

echo "- Django dağıtım denetimi (check --deploy)"
compose exec -T backend python manage.py check --deploy --fail-level WARNING >/dev/null \
    || fail "manage.py check --deploy uyarı verdi"
ok "check --deploy uyarısız"

if [ "${SKIP_BACKUP:-0}" != "1" ]; then
    echo "- yedek (backup servisi)"
    scripts/backup.sh >"$WORK/backup.log" 2>&1 || {
        cat "$WORK/backup.log" >&2
        fail "yedekleme başarısız"
    }
    compose exec -T backup cat /backups/status/latest-backup.json >"$WORK/b.json"
    jq -e '.kind == "backup" and .status == "ok" and .mismatches == [] and .tables > 0
        and .rows > 0 and .database_bytes > 0 and .run_id == .source_run_id' "$WORK/b.json" >/dev/null \
        || fail "latest-backup.json ok değil: $(cat "$WORK/b.json")"
    run_id="$(jq -r .run_id "$WORK/b.json")"
    ok "yedek $run_id: $(jq -r '"\(.tables) tablo, \(.rows) satır, \(.media_files) medya dosyası, dış kopya: \(.offsite)"' "$WORK/b.json")"
    # Backend durum dosyasını okuyabilmeli (uygulamada gösterilir; root olmayan kullanıcı).
    compose exec -T backend cat /backups/status/latest-backup.json | jq -e --arg r "$run_id" '.run_id == $r' >/dev/null \
        || fail "backend durum dosyasını okuyamıyor"
    ok "backend /backups/status/latest-backup.json okuyabiliyor"

    echo "- geri yükleme testi"
    compose exec -T backup /backup/restore-test.sh >"$WORK/restore.log" 2>&1 || {
        cat "$WORK/restore.log" >&2
        fail "geri yükleme testi başarısız"
    }
    compose exec -T backup cat /backups/status/latest-restore-test.json >"$WORK/r.json"
    jq -e --arg r "$run_id" '.kind == "restore_test" and .status == "ok" and .mismatches == []
        and .source_run_id == $r and .tables > 0' "$WORK/r.json" >/dev/null \
        || fail "latest-restore-test.json ok değil: $(cat "$WORK/r.json")"
    ok "geri yükleme testi: $(jq -r .message "$WORK/r.json")"
    compose exec -T backup sh -c 'tail -n 2 /backups/status/history.jsonl' | jq -s -e 'length == 2 and .[0].kind == "backup" and .[1].kind == "restore_test"' >/dev/null \
        || fail "history.jsonl son iki satırı beklenen gibi değil"
    ok "history.jsonl"
    leftover="$(compose exec -T db psql -U "${POSTGRES_USER:-deterjan}" -d postgres -Atc "SELECT count(*) FROM pg_database WHERE datname LIKE 'erp_restore_test_%'" 2>/dev/null || echo "?")"
    [ "$leftover" = "0" ] || fail "geçici geri yükleme veritabanı silinmemiş ($leftover)"
    ok "geçici veritabanı silindi"

    echo "- dış izleme ucu (/api/v1/ops/health/)"
    # Normalde Celery Beat birkaç dakikada bir okur; test için hemen içe aktar.
    compose exec -T backend python manage.py shell -c \
        "from apps.ops import services; services.ingest_backup_status(); services.record_heartbeat()" >/dev/null
    code="$(c -o "$WORK/ops.json" -w '%{http_code}' "$BASE_URL/api/v1/ops/health/")"
    [ "$code" = "200" ] || fail "/api/v1/ops/health/ beklenen 200, gelen $code: $(head -c 500 "$WORK/ops.json")"
    ok "/api/v1/ops/health/: $(jq -c . "$WORK/ops.json" | head -c 300)"
fi

echo "Üretim duman testi geçti."
