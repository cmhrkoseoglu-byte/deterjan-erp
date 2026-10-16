#!/usr/bin/env bash
# GERÇEK GERİ YÜKLEME (felaket kurtarma). Ana veritabanı ve ekler (medya) seçilen yedekle
# DEĞİŞTİRİLİR; o andan sonraki kayıtlar kaybolur. Adımlar:
#   1. backend, worker, beat ve nginx durdurulur (kimse yazmasın)
#   2. yedek konteynerinde /backup/restore.sh: SHA-256 doğrulaması, mevcut veritabanının güvenlik
#      dökümü (<BACKUP_DIR>/pre-restore/), veritabanını sil-oluştur, pg_restore, medya
#   3. servisler yeniden başlatılır (migrate otomatik çalışır)
#
# Kullanım: scripts/restore.sh <kimlik | latest> [--source offsite] [--no-media] [--yes]
#   Yedekleri listelemek için: scripts/prod-compose.sh run --rm backup list
set -euo pipefail

cd "$(dirname "$0")/.."
compose() { scripts/prod-compose.sh "$@"; }

if [ $# -lt 1 ] || [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
fi

run_id="$1"
shift
assume_yes=0
args=()
for arg in "$@"; do
    if [ "$arg" = "--yes" ]; then assume_yes=1; else args+=("$arg"); fi
done

echo "Mevcut yedekler:"
compose run --rm --no-deps -T backup list || true
echo
echo "DİKKAT: Ana veritabanı ve ekler '$run_id' yedeğiyle DEĞİŞTİRİLECEK. Uygulama bu sırada kapalı olacak."
if [ "$assume_yes" -ne 1 ]; then
    read -r -p "Devam etmek için büyük harflerle EVET yazın: " answer
    if [ "$answer" != "EVET" ]; then
        echo "Onaylanmadı, hiçbir şey değiştirilmedi."
        exit 1
    fi
fi

echo "- uygulama servisleri durduruluyor"
compose stop nginx backend worker beat

echo "- geri yükleme"
# Medya volume'ü bu tek seferlik konteynere yazılabilir bağlanır (backup servisinde salt okunur).
# Proje adı docker-compose.yml'deki `name:` alanıdır (COMPOSE_PROJECT_NAME ile değiştirilebilir).
project="${COMPOSE_PROJECT_NAME:-deterjan-erp}"
if ! compose run --rm --no-deps -T -v "${project}_media:/restore-media" backup restore "$run_id" --yes "${args[@]}"; then
    echo
    echo "HATA: geri yükleme başarısız. Servisler DURDURULMUŞ bırakıldı."
    echo "Geri yüklemeden önce alınan güvenlik dökümü: <BACKUP_DIR>/pre-restore/ (docs/KURULUM.md)."
    exit 1
fi

echo "- servisler başlatılıyor"
compose up -d --wait
echo "Geri yükleme tamamlandı. Uygulamaya girip son kayıtları kontrol edin."
