#!/usr/bin/env bash
# Yedekleme konteynerinin giriş noktası.
#
#   cron (varsayılan)  : BACKUP_CRON ve RESTORE_TEST_CRON'a göre zamanlanmış görevler (busybox crond)
#   backup             : hemen bir yedek al
#   restore-test       : hemen bir geri yükleme testi yap
#   restore <kimlik>   : GERÇEK geri yükleme (bkz. restore.sh; host'ta scripts/restore.sh önerilir)
#   list               : tamamlanmış yedekleri listele
#
# Örnek: docker compose ... run --rm backup restore-test
set -Eeuo pipefail

ENV_FILE=/run/backup-env.sh

cron_valid() {
    # 5 alanlı cron ifadesi (dakika saat gün ay haftanın-günü)
    local re='^[0-9*/, -]+$'
    [ "$(echo "$1" | awk '{print NF}')" -eq 5 ] && [[ "$1" =~ $re ]]
}

case "${1:-cron}" in
    cron)
        backup_cron="${BACKUP_CRON:-0 2 * * *}"
        restore_cron="${RESTORE_TEST_CRON:-0 4 * * 0}"
        cron_valid "$backup_cron" || {
            echo "HATA: geçersiz BACKUP_CRON: '$backup_cron'" >&2
            exit 1
        }
        # Zamanlanmış görevler konteynerin ortam değişkenlerini bu dosyadan alır.
        (umask 077 && export -p >"$ENV_FILE")
        mkdir -p /etc/crontabs
        {
            echo "# Otomatik üretildi (entrypoint.sh). Saat dilimi: ${TZ:-UTC}"
            echo "$backup_cron /backup/entrypoint.sh cron-job backup"
            case "${restore_cron,,}" in
                "" | off | kapali | disabled) echo "# geri yükleme testi kapalı (RESTORE_TEST_CRON)" ;;
                *)
                    cron_valid "$restore_cron" || {
                        echo "HATA: geçersiz RESTORE_TEST_CRON: '$restore_cron'" >&2
                        exit 1
                    }
                    echo "$restore_cron /backup/entrypoint.sh cron-job restore-test"
                    ;;
            esac
        } >/etc/crontabs/root
        echo "Yedekleme zamanlayıcısı başladı (saat dilimi ${TZ:-UTC}, şu an $(date '+%Y-%m-%d %H:%M %Z')):"
        grep -v '^#' /etc/crontabs/root | sed 's/^/  /'
        exec crond -f -c /etc/crontabs -d "${CROND_LOG_LEVEL:-8}"
        ;;
    cron-job)
        # crond'un çağırdığı görev: ortamı yükle, çıktıyı konteyner günlüğüne (PID 1) yaz.
        # shellcheck disable=SC1090
        source "$ENV_FILE"
        case "${2:-}" in
            backup) exec /backup/backup.sh >/proc/1/fd/1 2>/proc/1/fd/2 ;;
            restore-test) exec /backup/restore-test.sh >/proc/1/fd/1 2>/proc/1/fd/2 ;;
            *) exit 2 ;;
        esac
        ;;
    backup)
        shift
        exec /backup/backup.sh "$@"
        ;;
    restore-test)
        shift
        exec /backup/restore-test.sh "$@"
        ;;
    restore)
        shift
        exec /backup/restore.sh "$@"
        ;;
    list)
        # shellcheck source=backup/lib.sh
        source /backup/lib.sh
        echo "Yerel yedekler ($DAILY_DIR):"
        list_runs "$DAILY_DIR" | sed 's/^/  /'
        if offsite_dir_enabled && check_offsite_dir >/dev/null; then
            echo "Dış disk ($OFFSITE_ROOT/daily):"
            list_runs "$OFFSITE_ROOT/daily" | sed 's/^/  /'
        fi
        ;;
    *)
        exec "$@"
        ;;
esac
