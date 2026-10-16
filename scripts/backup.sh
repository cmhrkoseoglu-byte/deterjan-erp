#!/usr/bin/env bash
# Elle yedek alır (gece yedeğiyle aynı betik: /backup/backup.sh). Sonuç:
#   <BACKUP_DIR>/daily/<kimlik>/ ve <BACKUP_DIR>/status/latest-backup.json
# Kullanım: scripts/backup.sh            # yedek
#           scripts/backup.sh --test     # yedek + hemen geri yükleme testi
set -euo pipefail

cd "$(dirname "$0")/.."
compose() { scripts/prod-compose.sh "$@"; }

run_in_backup() {
    # Servis çalışıyorsa içinde, değilse tek seferlik konteynerde çalıştır.
    if [ -n "$(compose ps --status running -q backup 2>/dev/null)" ]; then
        compose exec -T backup "$@"
    else
        compose run --rm --no-deps -T backup "$@"
    fi
}

run_in_backup /backup/backup.sh
if [ "${1:-}" = "--test" ]; then
    run_in_backup /backup/restore-test.sh
fi
