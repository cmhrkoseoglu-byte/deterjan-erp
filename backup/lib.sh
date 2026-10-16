# shellcheck shell=bash
# Değişkenler bu dosyayı yükleyen betiklerde kullanılır; durum alanları onlarda atanır.
# shellcheck disable=SC2034,SC2153
# Yedekleme betiklerinin ortak yardımcıları (backup.sh, restore-test.sh, restore.sh).
# Bu dosya doğrudan çalıştırılmaz; `source` ile yüklenir.

BACKUP_ROOT="${BACKUP_ROOT:-/backups}"
DAILY_DIR="$BACKUP_ROOT/daily"
STATUS_DIR="$BACKUP_ROOT/status"
OFFSITE_ROOT="${OFFSITE_ROOT:-/offsite}"
MEDIA_DIR="${MEDIA_DIR:-/media}"
# Dış diskin gerçekten takılı olduğunu gösteren işaret dosyası (diskin kökünde, elle oluşturulur).
OFFSITE_MARKER=".deterjan-erp-offsite"
# Compose, BACKUP_OFFSITE_DIR tanımsızken bu işareti taşıyan boş bir klasörü bağlar.
OFFSITE_PLACEHOLDER_MARKER=".offsite-disabled"
RUN_ID_RE='^[0-9]{8}T[0-9]{6}$'
LOCK_FILE="$BACKUP_ROOT/.lock"

export RCLONE_CONFIG="${RCLONE_CONFIG:-/config/rclone/rclone.conf}"

# PostgreSQL bağlantısı: .env.prod'daki POSTGRES_* değerlerinden.
export PGHOST="${PGHOST:-db}"
export PGPORT="${PGPORT:-5432}"
export PGUSER="${PGUSER:-${POSTGRES_USER:-}}"
export PGPASSWORD="${PGPASSWORD:-${POSTGRES_PASSWORD:-}}"
export PGDATABASE="${PGDATABASE:-${POSTGRES_DB:-}}"
export PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-10}"

# Yedek dosyaları yalnızca root okuyabilir; durum dosyaları herkese açık (backend okur).
umask 077

log() {
    printf '%s [%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "${LOG_TAG:-yedek}" "$*"
}

# ISO 8601, saat dilimi farkı iki noktalı (2026-10-17T02:00:00+03:00). busybox ve GNU date ile çalışır.
iso_now() {
    local d
    d="$(date +%Y-%m-%dT%H:%M:%S%z)"
    printf '%s:%s\n' "${d:0:22}" "${d:22:2}"
}

run_id_now() {
    date +%Y%m%dT%H%M%S
}

is_true() {
    case "${1,,}" in
        1 | true | yes | evet | on) return 0 ;;
        *) return 1 ;;
    esac
}

file_size() {
    stat -c %s "$1"
}

sha256_of() {
    sha256sum "$1" | awk '{print $1}'
}

# Hata günlüğünün (stderr) son satırları, durum mesajına eklenmek üzere tek satır.
last_errors() {
    [ -n "${ERRLOG:-}" ] && [ -s "$ERRLOG" ] || return 0
    tail -n 3 "$ERRLOG" | tr '\n' ' ' | sed 's/  */ /g; s/ $//' | cut -c1-500
}

# public şemasındaki her tablonun satır sayısı, tek satırlık JSON nesnesi olarak
# ({"tablo": sayı, ...}). query_to_xml her tabloyu aynı işlem (aynı anlık görüntü) içinde sayar.
COUNT_ROWS_SQL="SELECT coalesce(json_object_agg(t.relname, t.n ORDER BY t.relname), '{}'::json) FROM (SELECT c.relname, (xpath('/row/n/text()', query_to_xml(format('SELECT count(*) AS n FROM %I.%I', ns.nspname, c.relname), false, true, '')))[1]::text::bigint AS n FROM pg_class c JOIN pg_namespace ns ON ns.oid = c.relnamespace WHERE ns.nspname = 'public' AND c.relkind = 'r') t;"

# Bir klasördeki tamamlanmış yedekler (adı çalışma kimliği olan ve manifest.json içeren), eskiden yeniye.
list_runs() {
    local root="$1" d name
    [ -d "$root" ] || return 0
    for d in "$root"/*/; do
        [ -d "$d" ] || continue
        name="$(basename "$d")"
        [[ "$name" =~ $RUN_ID_RE ]] || continue
        [ -s "$d/manifest.json" ] || continue
        printf '%s\n' "$name"
    done | sort
}

latest_run() {
    list_runs "$1" | tail -n 1
}

# Bir yedek klasöründeki dosyaları manifest'teki boyut ve SHA-256 değerleriyle karşılaştırır.
# Uyuşmazlıkları stdout'a yazar; hepsi doğruysa 0 döner.
verify_run_dir() {
    local dir="$1" manifest="$1/manifest.json" name expected_sha expected_size actual_sha bad=0
    if ! jq -e '.files | type == "object"' "$manifest" >/dev/null 2>&1; then
        echo "manifest.json okunamadı ($dir)"
        return 1
    fi
    while IFS=$'\t' read -r name expected_sha expected_size; do
        if [ ! -f "$dir/$name" ]; then
            echo "$name eksik"
            bad=1
            continue
        fi
        if [ "$(file_size "$dir/$name")" != "$expected_size" ]; then
            echo "$name boyutu farklı"
            bad=1
            continue
        fi
        actual_sha="$(sha256_of "$dir/$name")"
        if [ "$actual_sha" != "$expected_sha" ]; then
            echo "$name SHA-256 özeti farklı"
            bad=1
        fi
    done < <(jq -r '.files | to_entries[] | [.key, .value.sha256, (.value.bytes | tostring)] | @tsv' "$manifest")
    return "$bad"
}

offsite_dir_enabled() {
    is_true "${BACKUP_OFFSITE_ENABLED:-false}"
}

rclone_enabled() {
    [ -n "${BACKUP_RCLONE_REMOTE:-}" ]
}

# Dış disk kullanılabilir mi? Değilse nedenini stdout'a yazar ve 1 döner.
check_offsite_dir() {
    if [ -e "$OFFSITE_ROOT/$OFFSITE_PLACEHOLDER_MARKER" ]; then
        echo "BACKUP_OFFSITE_ENABLED açık ama BACKUP_OFFSITE_DIR tanımlı değil (.env.prod)"
        return 1
    fi
    if [ ! -e "$OFFSITE_ROOT/$OFFSITE_MARKER" ]; then
        echo "Dış diskte $OFFSITE_MARKER işaret dosyası yok: disk takılı/bağlı değil ya da hazırlanmamış (docs/KURULUM.md)"
        return 1
    fi
    if ! touch "$OFFSITE_ROOT/.yazma-denemesi" 2>/dev/null; then
        echo "Dış diske yazılamıyor ($OFFSITE_ROOT)"
        return 1
    fi
    rm -f "$OFFSITE_ROOT/.yazma-denemesi"
}

# Durum sözleşmesi: /backups/status/latest-<tür>.json (atomik) + history.jsonl (bir satır).
# $1: backup | restore_test, $2: JSON nesnesi
write_status() {
    local kind="$1" json="$2" target tmp
    case "$kind" in
        backup) target="$STATUS_DIR/latest-backup.json" ;;
        restore_test) target="$STATUS_DIR/latest-restore-test.json" ;;
        *) return 1 ;;
    esac
    mkdir -p "$STATUS_DIR"
    chmod 755 "$STATUS_DIR"
    tmp="$(mktemp "$STATUS_DIR/.status.XXXXXX")"
    printf '%s\n' "$json" | jq . >"$tmp"
    chmod 644 "$tmp"
    mv -f "$tmp" "$target"
    (
        flock 8
        printf '%s\n' "$json" | jq -c . >>"$STATUS_DIR/history.jsonl"
        chmod 644 "$STATUS_DIR/history.jsonl"
    ) 8>>"$STATUS_DIR/.history.lock"
}

# Durum nesnesi; alanlar çağıranın kabuk değişkenlerinden okunur.
status_json() {
    jq -n \
        --arg kind "$KIND" \
        --arg run_id "$RUN_ID" \
        --arg started_at "$STARTED_AT" \
        --arg finished_at "$(iso_now)" \
        --arg status "$STATUS" \
        --arg message "$MESSAGE" \
        --argjson database_bytes "${DB_BYTES:-0}" \
        --argjson media_bytes "${MEDIA_BYTES:-0}" \
        --argjson media_files "${MEDIA_FILES:-0}" \
        --argjson tables "${TABLES:-0}" \
        --argjson rows "${ROWS:-0}" \
        --arg offsite "$OFFSITE" \
        --arg offsite_message "$OFFSITE_MESSAGE" \
        --argjson mismatches "${MISMATCHES:-[]}" \
        --arg source_run_id "${SOURCE_RUN_ID:-}" \
        '{kind: $kind, run_id: $run_id, started_at: $started_at, finished_at: $finished_at,
          status: $status, message: $message, database_bytes: $database_bytes,
          media_bytes: $media_bytes, media_files: $media_files, tables: $tables, rows: $rows,
          offsite: $offsite, offsite_message: $offsite_message, mismatches: $mismatches,
          source_run_id: $source_run_id}'
}

# Aynı anda tek yedekleme / geri yükleme işlemi (fd 9 kilidi).
acquire_lock() {
    mkdir -p "$BACKUP_ROOT"
    exec 9>>"$LOCK_FILE"
    # busybox flock'ta -w (bekleme süresi) yok: -n ile dene, bekle, tekrar dene.
    local waited=0 limit="${BACKUP_LOCK_WAIT_SECONDS:-3600}"
    until flock -n 9; do
        [ "$waited" -lt "$limit" ] || return 1
        [ "$waited" -gt 0 ] || log "başka bir işlem sürüyor, kilit bekleniyor (en çok $limit sn)"
        sleep 5
        waited=$((waited + 5))
    done
}

# Retention: çalışma kimliği (zaman damgası) BACKUP_RETENTION_DAYS günden eski yedekleri siler.
# $1: kök klasör, $2: korunacak çalışma kimliği (az önce alınan)
prune_local_runs() {
    local root="$1" keep="$2" days="${BACKUP_RETENTION_DAYS:-30}" cutoff d name
    [ "$days" -gt 0 ] 2>/dev/null || return 0
    cutoff="$(date -d "@$(($(date +%s) - days * 86400))" +%Y%m%dT%H%M%S)"
    for d in "$root"/*/; do
        [ -d "$d" ] || continue
        name="$(basename "$d")"
        [[ "$name" =~ $RUN_ID_RE ]] || continue
        [ "$name" = "$keep" ] && continue
        if [[ "$name" < "$cutoff" ]]; then
            log "eski yedek siliniyor: $root/$name"
            rm -rf -- "${d%/}"
        fi
    done
}
