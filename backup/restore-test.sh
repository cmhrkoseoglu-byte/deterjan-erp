#!/usr/bin/env bash
# Geri yükleme testi: en son tamamlanmış yedeği geçici bir veritabanına geri yükler ve doğrular.
#
#   1. Yedeği seç (RESTORE_TEST_SOURCE=local: /backups, offsite: dış disk ya da rclone hedefi)
#   2. Dosyaların SHA-256 özetlerini manifest ile karşılaştır
#   3. Aynı sunucuda geçici veritabanı (erp_restore_test_<zaman>) oluştur, pg_restore ile yükle
#   4. Her tablonun satır sayısını manifest ile karşılaştır
#   5. Medya arşivini baştan sona oku, dosya sayısını karşılaştır
#   6. Dış kopya açıksa aynı yedeğin dış kopyasını da doğrula
#   7. Geçici veritabanını HER DURUMDA sil
# Sonuç /backups/status/latest-restore-test.json dosyasına yazılır (başarısızlıkta da).
#
# Kullanım (konteyner içinde): /backup/restore-test.sh
set -Eeuo pipefail

# shellcheck source=backup/lib.sh
source /backup/lib.sh
LOG_TAG="geri-yukleme-testi"

KIND="restore_test"
RUN_ID="$(run_id_now)"
SOURCE_RUN_ID=""
STARTED_AT="$(iso_now)"
STATUS="failed"
MESSAGE=""
STEP="başlatma"
DB_BYTES=0 MEDIA_BYTES=0 MEDIA_FILES=0 TABLES=0 ROWS=0
MISMATCHES="[]"
OFFSITE="disabled"
OFFSITE_MESSAGE="Dış kopya tanımlı değil (BACKUP_OFFSITE_ENABLED / BACKUP_RCLONE_REMOTE)."
TEST_DB=""
DOWNLOAD_DIR=""
SOURCE="${RESTORE_TEST_SOURCE:-local}"

ERRLOG="$(mktemp /tmp/restore-test-err.XXXXXX)"
exec 3>&2 2>"$ERRLOG"

# shellcheck disable=SC2329 # finish içinden çağrılır
drop_test_db() {
    [ -n "$TEST_DB" ] || return 0
    psql -X -q -d postgres -v ON_ERROR_STOP=1 \
        -c "DROP DATABASE IF EXISTS \"$TEST_DB\" WITH (FORCE)" \
        && log "geçici veritabanı silindi: $TEST_DB"
}

# shellcheck disable=SC2329 # trap ile çağrılır
finish() {
    local rc=$?
    set +e
    drop_test_db || log "UYARI: geçici veritabanı silinemedi: $TEST_DB"
    [ -z "$DOWNLOAD_DIR" ] || rm -rf -- "$DOWNLOAD_DIR"
    if [ "$rc" -ne 0 ] || [ "$STATUS" != "ok" ]; then
        STATUS="failed"
        [ "$rc" -ne 0 ] || rc=1
        if [ -z "$MESSAGE" ]; then
            MESSAGE="Geri yükleme testi başarısız: '$STEP' adımında hata (çıkış kodu $rc)."
            local err
            err="$(last_errors)"
            [ -z "$err" ] || MESSAGE="$MESSAGE Ayrıntı: $err"
        fi
        log "BAŞARISIZ: $MESSAGE"
    else
        log "tamamlandı: $MESSAGE"
    fi
    write_status restore_test "$(status_json)" || log "UYARI: durum dosyası yazılamadı"
    cat "$ERRLOG" >&3
    rm -f "$ERRLOG"
    exit "$rc"
}
trap finish EXIT
trap 'exit 130' INT TERM

STEP="kilit alma"
if ! acquire_lock; then
    MESSAGE="Geri yükleme testi başlatılamadı: başka bir yedekleme/geri yükleme işlemi sürüyor."
    exit 1
fi

# --- kaynak yedeği seç -------------------------------------------------------------------------
STEP="yedek seçimi"
case "$SOURCE" in
    local)
        SOURCE_ROOT="$DAILY_DIR"
        SOURCE_LABEL="yerel ($DAILY_DIR)"
        ;;
    offsite)
        if offsite_dir_enabled; then
            reason="$(check_offsite_dir)" || {
                MESSAGE="Geri yükleme testi başlatılamadı: $reason"
                exit 1
            }
            SOURCE_ROOT="$OFFSITE_ROOT/daily"
            SOURCE_LABEL="dış disk ($SOURCE_ROOT)"
        elif rclone_enabled; then
            remote_root="${BACKUP_RCLONE_REMOTE%/}/daily"
            latest_remote=""
            # shellcheck disable=SC2086
            while IFS= read -r name; do
                name="${name%/}"
                [[ "$name" =~ $RUN_ID_RE ]] || continue
                if rclone lsf "$remote_root/$name/" ${BACKUP_RCLONE_FLAGS:-} | grep -qx 'manifest.json'; then
                    latest_remote="$name"
                fi
            done < <(rclone lsf --dirs-only "$remote_root" ${BACKUP_RCLONE_FLAGS:-} | sort)
            [ -n "$latest_remote" ] || {
                MESSAGE="Geri yükleme testi başarısız: uzak hedefte ($remote_root) tamamlanmış yedek yok."
                exit 1
            }
            DOWNLOAD_DIR="$BACKUP_ROOT/.restore-test-download"
            rm -rf -- "$DOWNLOAD_DIR"
            mkdir -p "$DOWNLOAD_DIR"
            log "uzak yedek indiriliyor: $remote_root/$latest_remote"
            # shellcheck disable=SC2086
            rclone copy "$remote_root/$latest_remote" "$DOWNLOAD_DIR/$latest_remote" ${BACKUP_RCLONE_FLAGS:-}
            SOURCE_ROOT="$DOWNLOAD_DIR"
            SOURCE_LABEL="rclone ($remote_root)"
        else
            MESSAGE="RESTORE_TEST_SOURCE=offsite ama dış kopya tanımlı değil (BACKUP_OFFSITE_ENABLED / BACKUP_RCLONE_REMOTE)."
            exit 1
        fi
        ;;
    *)
        MESSAGE="Geçersiz RESTORE_TEST_SOURCE: '$SOURCE' (local ya da offsite olmalı)."
        exit 1
        ;;
esac

SOURCE_RUN_ID="$(latest_run "$SOURCE_ROOT")"
[ -n "$SOURCE_RUN_ID" ] || {
    MESSAGE="Geri yükleme testi başarısız: $SOURCE_LABEL içinde tamamlanmış yedek bulunamadı."
    exit 1
}
RUN_DIR="$SOURCE_ROOT/$SOURCE_RUN_ID"
MANIFEST="$RUN_DIR/manifest.json"
log "test edilen yedek: $SOURCE_RUN_ID, kaynak: $SOURCE_LABEL"

STEP="SHA-256 doğrulaması"
if ! problems="$(verify_run_dir "$RUN_DIR")"; then
    MESSAGE="Geri yükleme testi başarısız: $SOURCE_RUN_ID yedeğinin dosyaları bozuk: $(echo "$problems" | tr '\n' ' ')"
    exit 1
fi
DB_BYTES="$(file_size "$RUN_DIR/db.dump")"
MEDIA_BYTES="$(file_size "$RUN_DIR/media.tar.gz")"

# --- veritabanı --------------------------------------------------------------------------------
STEP="geçici veritabanı oluşturma"
TEST_DB="erp_restore_test_$RUN_ID"
TEST_DB="${TEST_DB,,}"
psql -X -q -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$TEST_DB\" TEMPLATE template0"
log "geçici veritabanı: $TEST_DB"

STEP="pg_restore"
pg_restore --no-owner --no-acl --exit-on-error -d "$TEST_DB" "$RUN_DIR/db.dump"

STEP="satır sayılarını karşılaştırma"
ACTUAL_JSON="$(psql -X -q -A -t -v ON_ERROR_STOP=1 -d "$TEST_DB" -c "$COUNT_ROWS_SQL")"
EXPECTED_JSON="$(jq -c '.tables' "$MANIFEST")"
MISMATCHES="$(jq -cn --argjson e "$EXPECTED_JSON" --argjson a "$ACTUAL_JSON" '
    [ (($e | keys) + ($a | keys) | unique)[] as $t
      | select($e[$t] != $a[$t])
      | {table: $t, expected: ($e[$t] // -1), actual: ($a[$t] // -1)} ]')"
TABLES="$(jq 'length' <<<"$ACTUAL_JSON")"
ROWS="$(jq '[.[]] | add // 0' <<<"$ACTUAL_JSON")"
mismatch_count="$(jq 'length' <<<"$MISMATCHES")"
log "veritabanı: $TABLES tablo, $ROWS satır, uyuşmayan tablo: $mismatch_count"

# --- medya -------------------------------------------------------------------------------------
STEP="medya arşivini okuma"
MEDIA_FILES="$(tar -tvzf "$RUN_DIR/media.tar.gz" | awk '/^-/ {n++} END {print n + 0}')"
EXPECTED_MEDIA="$(jq '.media_files' "$MANIFEST")"
log "medya: $MEDIA_FILES dosya (manifest: $EXPECTED_MEDIA)"

# --- dış kopya ---------------------------------------------------------------------------------
STEP="dış kopya doğrulaması"
offsite_failed=0
offsite_parts=()
if offsite_dir_enabled; then
    if [ "$SOURCE_ROOT" = "$OFFSITE_ROOT/daily" ]; then
        offsite_parts+=("dış disk: test bu kopyadan yapıldı")
    elif reason="$(check_offsite_dir)"; then
        if [ ! -d "$OFFSITE_ROOT/daily/$SOURCE_RUN_ID" ]; then
            offsite_failed=1
            offsite_parts+=("dış disk: $SOURCE_RUN_ID yedeği dış diskte yok")
        elif problems="$(verify_run_dir "$OFFSITE_ROOT/daily/$SOURCE_RUN_ID")"; then
            offsite_parts+=("dış disk: $SOURCE_RUN_ID kopyası SHA-256 ile doğrulandı")
        else
            offsite_failed=1
            offsite_parts+=("dış disk: $SOURCE_RUN_ID kopyası bozuk ($(echo "$problems" | tr '\n' ' '))")
        fi
    else
        offsite_failed=1
        offsite_parts+=("dış disk: $reason")
    fi
fi
if rclone_enabled; then
    if [ -n "$DOWNLOAD_DIR" ]; then
        offsite_parts+=("rclone ($BACKUP_RCLONE_REMOTE): test bu kopyadan yapıldı")
    else
        # shellcheck disable=SC2086
        if rclone check "$RUN_DIR" "${BACKUP_RCLONE_REMOTE%/}/daily/$SOURCE_RUN_ID" --one-way ${BACKUP_RCLONE_FLAGS:-}; then
            offsite_parts+=("rclone ($BACKUP_RCLONE_REMOTE): $SOURCE_RUN_ID kopyası rclone check ile doğrulandı")
        else
            offsite_failed=1
            offsite_parts+=("rclone ($BACKUP_RCLONE_REMOTE): $SOURCE_RUN_ID kopyası doğrulanamadı")
        fi
    fi
fi
if [ "${#offsite_parts[@]}" -gt 0 ]; then
    OFFSITE_MESSAGE="$(printf '%s; ' "${offsite_parts[@]}")"
    OFFSITE_MESSAGE="${OFFSITE_MESSAGE%; }."
    if [ "$offsite_failed" -eq 0 ]; then OFFSITE="ok"; else OFFSITE="failed"; fi
fi

# --- sonuç -------------------------------------------------------------------------------------
STEP="sonuç"
failures=()
[ "$mismatch_count" -eq 0 ] || failures+=("$mismatch_count tabloda satır sayısı farklı ($(jq -r 'map(.table) | join(", ")' <<<"$MISMATCHES"))")
[ "$MEDIA_FILES" -eq "$EXPECTED_MEDIA" ] || failures+=("medya dosya sayısı farklı (beklenen $EXPECTED_MEDIA, arşivde $MEDIA_FILES)")
[ "$OFFSITE" != "failed" ] || failures+=("dış kopya doğrulanamadı: $OFFSITE_MESSAGE")
if [ "${#failures[@]}" -gt 0 ]; then
    MESSAGE="Geri yükleme testi başarısız ($SOURCE_RUN_ID): $(printf '%s; ' "${failures[@]}")"
    MESSAGE="${MESSAGE%; }."
    exit 1
fi

STATUS="ok"
MESSAGE="Geri yükleme testi başarılı: $SOURCE_RUN_ID yedeği ($SOURCE_LABEL) geçici veritabanına yüklendi; $TABLES tablo ve $ROWS satır manifest ile aynı, $MEDIA_FILES medya dosyası okundu."
exit 0
