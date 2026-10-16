#!/usr/bin/env bash
# GERÇEK GERİ YÜKLEME (felaket kurtarma): ana veritabanını ve medya klasörünü bir yedekle değiştirir.
# Mevcut veriler SİLİNİR. Normalde host'taki scripts/restore.sh üzerinden çalıştırılır; o betik
# backend/worker/beat'i durdurur, medya volume'ünü yazılabilir bağlar ve sonra servisleri başlatır.
#
# Kullanım (konteyner içinde):
#   /backup/restore.sh <çalışma kimliği | latest> [--yes] [--source local|offsite]
#                      [--no-media] [--no-safety-dump]
#   --yes             : onay sorusunu atla (yalnızca betiklerden)
#   --source offsite  : yedeği dış diskten al (varsayılan: /backups)
#   --no-media        : yalnızca veritabanı
#   --no-safety-dump  : geri yüklemeden önce mevcut veritabanının güvenlik dökümünü alma
set -Eeuo pipefail

# shellcheck source=backup/lib.sh
source /backup/lib.sh
LOG_TAG="geri-yukleme"

usage() {
    sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
}

fail() {
    log "HATA: $*"
    exit 1
}

RUN_ARG=""
ASSUME_YES=0
SOURCE="local"
WITH_MEDIA=1
SAFETY_DUMP=1
MEDIA_TARGET="${MEDIA_RESTORE_DIR:-/restore-media}"

while [ $# -gt 0 ]; do
    case "$1" in
        --yes | -y) ASSUME_YES=1 ;;
        --source)
            shift
            SOURCE="${1:-}"
            ;;
        --source=*) SOURCE="${1#--source=}" ;;
        --no-media) WITH_MEDIA=0 ;;
        --no-safety-dump) SAFETY_DUMP=0 ;;
        -h | --help) usage ;;
        -*) usage ;;
        *) RUN_ARG="$1" ;;
    esac
    shift
done
[ -n "$RUN_ARG" ] || usage
[ -n "$PGUSER" ] && [ -n "$PGDATABASE" ] || fail "POSTGRES_USER / POSTGRES_DB tanımlı değil."

case "$SOURCE" in
    local) SOURCE_ROOT="$DAILY_DIR" ;;
    offsite)
        reason="$(check_offsite_dir)" || fail "$reason"
        SOURCE_ROOT="$OFFSITE_ROOT/daily"
        ;;
    *) fail "Geçersiz --source: $SOURCE (local ya da offsite)" ;;
esac

if [ "$RUN_ARG" = "latest" ]; then
    RUN_ARG="$(latest_run "$SOURCE_ROOT")"
    [ -n "$RUN_ARG" ] || fail "$SOURCE_ROOT içinde tamamlanmış yedek yok."
fi
[[ "$RUN_ARG" =~ $RUN_ID_RE ]] || fail "Geçersiz çalışma kimliği: $RUN_ARG (ör. 20261017T020000)"
RUN_DIR="$SOURCE_ROOT/$RUN_ARG"
[ -s "$RUN_DIR/manifest.json" ] || {
    log "Mevcut yedekler ($SOURCE_ROOT):"
    list_runs "$SOURCE_ROOT" >&2
    fail "Yedek bulunamadı ya da tamamlanmamış: $RUN_DIR"
}

if [ "$WITH_MEDIA" -eq 1 ]; then
    [ -d "$MEDIA_TARGET" ] && [ -w "$MEDIA_TARGET" ] \
        || fail "Medya hedefi ($MEDIA_TARGET) yazılabilir bağlı değil. Host'ta scripts/restore.sh kullanın ya da --no-media verin."
fi

acquire_lock || fail "Başka bir yedekleme/geri yükleme işlemi sürüyor."

log "yedek doğrulanıyor: $RUN_DIR"
problems="$(verify_run_dir "$RUN_DIR")" || fail "Yedek dosyaları bozuk: $(echo "$problems" | tr '\n' ' ')"
summary="$(jq -r '"\(.created_at) tarihli yedek, \(.table_count) tablo, \(.total_rows) satır, \(.media_files) medya dosyası, uygulama sürümü: \(if .app_version == "" then "bilinmiyor" else .app_version end)"' "$RUN_DIR/manifest.json")"

cat <<MSG

  DİKKAT: '$PGDATABASE' veritabanı$([ "$WITH_MEDIA" -eq 1 ] && echo " ve medya klasörü") SİLİNİP şu yedekle değiştirilecek:
    $RUN_ARG - $summary

MSG
if [ "$ASSUME_YES" -ne 1 ]; then
    [ -t 0 ] || fail "Onay için terminal gerekli (ya da --yes verin)."
    read -r -p "  Devam etmek için büyük harflerle EVET yazın: " answer
    [ "$answer" = "EVET" ] || fail "Onaylanmadı, hiçbir şey değiştirilmedi."
fi

if [ "$SAFETY_DUMP" -eq 1 ]; then
    mkdir -p "$BACKUP_ROOT/pre-restore"
    safety="$BACKUP_ROOT/pre-restore/$(run_id_now)-$PGDATABASE.dump"
    log "güvenlik dökümü alınıyor (mevcut veritabanı): $safety"
    pg_dump -Fc -f "$safety" "$PGDATABASE" || fail "Güvenlik dökümü alınamadı; geri yükleme yapılmadı."
fi

log "bağlantılar kapatılıyor ve veritabanı yeniden oluşturuluyor: $PGDATABASE"
psql -X -q -d postgres -v ON_ERROR_STOP=1 -v db="$PGDATABASE" -v owner="$PGUSER" >/dev/null <<'SQL'
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :'db' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS :"db" WITH (FORCE);
CREATE DATABASE :"db" OWNER :"owner" TEMPLATE template0;
SQL

log "pg_restore çalışıyor"
pg_restore --no-owner --no-acl --exit-on-error -d "$PGDATABASE" "$RUN_DIR/db.dump"
log "istatistikler güncelleniyor (ANALYZE)"
psql -X -q -d "$PGDATABASE" -c "ANALYZE" || true

restored="$(psql -X -q -A -t -v ON_ERROR_STOP=1 -c "$COUNT_ROWS_SQL")"
diff_count="$(jq -n --argjson e "$(jq -c .tables "$RUN_DIR/manifest.json")" --argjson a "$restored" \
    '[(($e | keys) + ($a | keys) | unique)[] as $t | select($e[$t] != $a[$t])] | length')"
[ "$diff_count" -eq 0 ] || fail "Geri yüklenen veritabanında $diff_count tablonun satır sayısı manifest ile uyuşmuyor!"
log "veritabanı geri yüklendi; satır sayıları manifest ile aynı"

if [ "$WITH_MEDIA" -eq 1 ]; then
    log "medya klasörü değiştiriliyor: $MEDIA_TARGET"
    owner="$(stat -c %u:%g "$MEDIA_TARGET")"
    find "$MEDIA_TARGET" -mindepth 1 -delete
    tar -C "$MEDIA_TARGET" -xzf "$RUN_DIR/media.tar.gz"
    chown -R "$owner" "$MEDIA_TARGET"
    log "medya geri yüklendi: $(find "$MEDIA_TARGET" -type f | wc -l) dosya"
fi

log "GERİ YÜKLEME TAMAMLANDI: $RUN_ARG"
