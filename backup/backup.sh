#!/usr/bin/env bash
# Tam yedek: PostgreSQL (tutarlı anlık görüntü) + medya (ekler) + manifest.
#
# Çıktı: /backups/daily/<çalışma kimliği>/{db.dump, media.tar.gz, manifest.json, SHA256SUMS}
#   - Önce /backups/daily/.tmp-<kimlik>/ altına yazılır, tamamlanınca adı değiştirilir; yarım kalan
#     bir yedek hiçbir zaman geçerli görünmez.
#   - Tablo satır sayıları, dökümle AYNI anlık görüntüde (pg_export_snapshot) sayılır; böylece
#     geri yükleme testi sayıları birebir karşılaştırabilir.
# Ardından dış kopya (disk ve/veya rclone uzak hedefi) alınır ve doğrulanır, eski yedekler silinir.
# Her çalışma sonunda /backups/status/latest-backup.json yazılır (başarısızlıkta da).
#
# Kullanım (konteyner içinde): /backup/backup.sh
# Host'tan elle: scripts/backup.sh
set -Eeuo pipefail

# shellcheck source=backup/lib.sh
source /backup/lib.sh
LOG_TAG="yedek"

KIND="backup"
RUN_ID="$(run_id_now)"
SOURCE_RUN_ID="$RUN_ID"
STARTED_AT="$(iso_now)"
STATUS="failed"
MESSAGE=""
STEP="başlatma"
DB_BYTES=0 MEDIA_BYTES=0 MEDIA_FILES=0 TABLES=0 ROWS=0
MISMATCHES="[]"
OFFSITE="disabled"
OFFSITE_MESSAGE="Dış kopya tanımlı değil (BACKUP_OFFSITE_ENABLED / BACKUP_RCLONE_REMOTE)."
TMP_DIR=""
RUN_DIR=""
PSQL_CHILD=""

# stderr bir dosyaya gider (hata mesajı durum dosyasına eklenir), sonunda asıl stderr'e aktarılır.
ERRLOG="$(mktemp /tmp/backup-err.XXXXXX)"
exec 3>&2 2>"$ERRLOG"

# shellcheck disable=SC2329 # trap ile çağrılır
finish() {
    local rc=$?
    set +e
    if [ -n "$PSQL_CHILD" ]; then
        kill "$PSQL_CHILD" 2>/dev/null
        wait "$PSQL_CHILD" 2>/dev/null
    fi
    if [ "$rc" -ne 0 ] || [ "$STATUS" != "ok" ]; then
        STATUS="failed"
        [ "$rc" -ne 0 ] || rc=1
        if [ -z "$MESSAGE" ]; then
            MESSAGE="Yedekleme başarısız: '$STEP' adımında hata (çıkış kodu $rc)."
            local err
            err="$(last_errors)"
            [ -z "$err" ] || MESSAGE="$MESSAGE Ayrıntı: $err"
        fi
        [ -z "$TMP_DIR" ] || rm -rf -- "$TMP_DIR"
        log "BAŞARISIZ: $MESSAGE"
    else
        log "tamamlandı: $MESSAGE"
    fi
    write_status backup "$(status_json)" || log "UYARI: durum dosyası yazılamadı"
    cat "$ERRLOG" >&3
    rm -f "$ERRLOG"
    exit "$rc"
}
trap finish EXIT
trap 'exit 130' INT TERM

STEP="kilit alma"
if ! acquire_lock; then
    MESSAGE="Yedekleme başlatılamadı: başka bir yedekleme/geri yükleme işlemi sürüyor."
    exit 1
fi

STEP="ön denetim"
[ -n "$PGUSER" ] && [ -n "$PGDATABASE" ] || {
    MESSAGE="Yedekleme başlatılamadı: POSTGRES_USER / POSTGRES_DB tanımlı değil."
    exit 1
}
[ -d "$MEDIA_DIR" ] || {
    MESSAGE="Yedekleme başlatılamadı: medya klasörü ($MEDIA_DIR) bağlı değil."
    exit 1
}
mkdir -p "$DAILY_DIR"
chmod 700 "$DAILY_DIR"
# Kilit bizde: önceki yarım kalmış çalışmalar artık geçersiz.
rm -rf -- "$DAILY_DIR"/.tmp-*
TMP_DIR="$DAILY_DIR/.tmp-$RUN_ID"
mkdir -p "$TMP_DIR"
log "yedekleme başladı: $RUN_ID (veritabanı $PGDATABASE@$PGHOST)"

STEP="veritabanı sürümü"
PG_VERSION="$(psql -X -A -t -c 'SHOW server_version')"

# --- tutarlı anlık görüntü -------------------------------------------------------------------
STEP="anlık görüntü"
coproc PSQL { exec psql -X -q -A -t -v ON_ERROR_STOP=1; }
PSQL_CHILD="$PSQL_PID"
# Okuma/yazma uçları kopyalanır (coproc sonlanınca bash PSQL dizisini siler).
exec 4>&"${PSQL[1]}" 5<&"${PSQL[0]}"
printf '%s\n' \
    "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;" \
    "SELECT pg_export_snapshot();" >&4
SNAPSHOT=""
IFS= read -r -t 60 SNAPSHOT <&5 || true
[ -n "$SNAPSHOT" ] || {
    MESSAGE="Yedekleme başarısız: veritabanı anlık görüntüsü alınamadı. $(last_errors)"
    exit 1
}
log "anlık görüntü: $SNAPSHOT"

STEP="tablo satır sayımı"
printf '%s\n' "$COUNT_ROWS_SQL" >&4
COUNTS_JSON=""
IFS= read -r -t "${BACKUP_COUNT_TIMEOUT_SECONDS:-3600}" COUNTS_JSON <&5 || true
jq -e 'type == "object"' >/dev/null <<<"$COUNTS_JSON" || {
    MESSAGE="Yedekleme başarısız: tablo satır sayıları alınamadı. $(last_errors)"
    exit 1
}

STEP="veritabanı dökümü (pg_dump)"
pg_dump -Fc --snapshot="$SNAPSHOT" -f "$TMP_DIR/db.dump"

printf '%s\n' "COMMIT;" '\q' >&4
exec 4>&- 5<&-
wait "$PSQL_CHILD" || true
PSQL_CHILD=""

TABLES="$(jq 'length' <<<"$COUNTS_JSON")"
ROWS="$(jq '[.[]] | add // 0' <<<"$COUNTS_JSON")"
DB_BYTES="$(file_size "$TMP_DIR/db.dump")"
log "veritabanı: $TABLES tablo, $ROWS satır, $DB_BYTES bayt"

# --- medya -------------------------------------------------------------------------------------
STEP="medya arşivi"
tar -C "$MEDIA_DIR" -czf "$TMP_DIR/media.tar.gz" .
# Sayı arşivin kendisinden alınır (arşivlenirken eklenen dosya sayımı bozmasın).
MEDIA_FILES="$(tar -tvzf "$TMP_DIR/media.tar.gz" | awk '/^-/ {n++} END {print n + 0}')"
MEDIA_BYTES="$(file_size "$TMP_DIR/media.tar.gz")"
log "medya: $MEDIA_FILES dosya, $MEDIA_BYTES bayt"

# --- manifest ----------------------------------------------------------------------------------
STEP="manifest"
DB_SHA="$(sha256_of "$TMP_DIR/db.dump")"
MEDIA_SHA="$(sha256_of "$TMP_DIR/media.tar.gz")"
jq -n \
    --arg run_id "$RUN_ID" \
    --arg created_at "$STARTED_AT" \
    --arg app_version "${APP_VERSION:-}" \
    --arg postgres_version "$PG_VERSION" \
    --arg pg_dump_version "$(pg_dump --version)" \
    --arg database "$PGDATABASE" \
    --argjson tables "$COUNTS_JSON" \
    --argjson media_files "$MEDIA_FILES" \
    --argjson db_bytes "$DB_BYTES" --arg db_sha "$DB_SHA" \
    --argjson media_bytes "$MEDIA_BYTES" --arg media_sha "$MEDIA_SHA" \
    '{format_version: 1, run_id: $run_id, created_at: $created_at, app_version: $app_version,
      postgres_version: $postgres_version, pg_dump_version: $pg_dump_version, database: $database,
      table_count: ($tables | length), total_rows: ([$tables[]] | add // 0), tables: $tables,
      media_files: $media_files,
      files: {"db.dump": {bytes: $db_bytes, sha256: $db_sha},
              "media.tar.gz": {bytes: $media_bytes, sha256: $media_sha}}}' \
    >"$TMP_DIR/manifest.json"
(cd "$TMP_DIR" && sha256sum db.dump media.tar.gz >SHA256SUMS)

STEP="yedeği tamamlama"
mv "$TMP_DIR" "$DAILY_DIR/$RUN_ID"
TMP_DIR=""
RUN_DIR="$DAILY_DIR/$RUN_ID"
log "yerel yedek hazır: $RUN_DIR"

# --- dış kopya ---------------------------------------------------------------------------------
STEP="dış kopya"
offsite_failed=0
offsite_parts=()

if offsite_dir_enabled; then
    if reason="$(check_offsite_dir)"; then
        dest_tmp="$OFFSITE_ROOT/daily/.tmp-$RUN_ID"
        mkdir -p "$OFFSITE_ROOT/daily"
        rm -rf -- "$OFFSITE_ROOT"/daily/.tmp-*
        if cp -R "$RUN_DIR" "$dest_tmp" && problems="$(verify_run_dir "$dest_tmp")" \
            && mv "$dest_tmp" "$OFFSITE_ROOT/daily/$RUN_ID"; then
            offsite_parts+=("dış disk: kopyalandı ve SHA-256 doğrulandı")
        else
            rm -rf -- "$dest_tmp"
            offsite_failed=1
            offsite_parts+=("dış disk: kopya doğrulanamadı (${problems:-kopyalama hatası})")
        fi
    else
        offsite_failed=1
        offsite_parts+=("dış disk: $reason")
    fi
fi

if rclone_enabled; then
    remote="${BACKUP_RCLONE_REMOTE%/}/daily/$RUN_ID"
    # manifest en son gönderilir: yarım kalan uzak kopya tamamlanmış görünmez.
    # shellcheck disable=SC2086 # BACKUP_RCLONE_FLAGS bilerek kelimelere bölünür
    if rclone copy "$RUN_DIR" "$remote" --exclude manifest.json ${BACKUP_RCLONE_FLAGS:-} \
        && rclone copyto "$RUN_DIR/manifest.json" "$remote/manifest.json" ${BACKUP_RCLONE_FLAGS:-} \
        && rclone check "$RUN_DIR" "$remote" --one-way ${BACKUP_RCLONE_FLAGS:-}; then
        offsite_parts+=("rclone ($BACKUP_RCLONE_REMOTE): kopyalandı ve rclone check doğrulandı")
    else
        offsite_failed=1
        offsite_parts+=("rclone ($BACKUP_RCLONE_REMOTE): kopyalama/doğrulama başarısız ($(last_errors))")
    fi
fi

if [ "${#offsite_parts[@]}" -gt 0 ]; then
    OFFSITE_MESSAGE="$(printf '%s; ' "${offsite_parts[@]}")"
    OFFSITE_MESSAGE="${OFFSITE_MESSAGE%; }."
    if [ "$offsite_failed" -eq 0 ]; then OFFSITE="ok"; else OFFSITE="failed"; fi
fi
log "dış kopya: $OFFSITE - $OFFSITE_MESSAGE"

# --- eski yedekleri temizle -------------------------------------------------------------------
# Yalnızca yeni yedek başarıyla alındıktan sonra; başarısız gecelerde eski yedekler korunur.
STEP="eski yedekleri silme"
prune_local_runs "$DAILY_DIR" "$RUN_ID"
if offsite_dir_enabled && check_offsite_dir >/dev/null; then
    prune_local_runs "$OFFSITE_ROOT/daily" "$RUN_ID"
fi
if rclone_enabled && [ "${BACKUP_RETENTION_DAYS:-30}" -gt 0 ] 2>/dev/null; then
    cutoff="$(date -d "@$(($(date +%s) - ${BACKUP_RETENTION_DAYS:-30} * 86400))" +%Y%m%dT%H%M%S)"
    # shellcheck disable=SC2086
    while IFS= read -r name; do
        name="${name%/}"
        [[ "$name" =~ $RUN_ID_RE ]] || continue
        [ "$name" != "$RUN_ID" ] || continue
        if [[ "$name" < "$cutoff" ]]; then
            log "eski uzak yedek siliniyor: $name"
            rclone purge "${BACKUP_RCLONE_REMOTE%/}/daily/$name" ${BACKUP_RCLONE_FLAGS:-} || true
        fi
    done < <(rclone lsf --dirs-only "${BACKUP_RCLONE_REMOTE%/}/daily" ${BACKUP_RCLONE_FLAGS:-} || true)
fi

if [ "$OFFSITE" = "failed" ]; then
    MESSAGE="Yerel yedek alındı ($RUN_ID; $TABLES tablo, $ROWS satır, $MEDIA_FILES medya dosyası) ancak dış kopya başarısız: $OFFSITE_MESSAGE"
    exit 1
fi

STATUS="ok"
MESSAGE="Yedek alındı: $RUN_ID ($TABLES tablo, $ROWS satır, $MEDIA_FILES medya dosyası)."
exit 0
