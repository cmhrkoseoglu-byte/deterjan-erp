#!/bin/sh
# nginx açılmadan önce: yapılandırmayı denetle ve iç ağ izin listesini üret.
set -eu

fail() {
    echo "HATA (nginx): $*" >&2
    exit 1
}

[ -n "${SERVER_NAME:-}" ] || fail "SERVER_NAME tanımlı değil (.env.prod). Örnek: SERVER_NAME=erp.firma.local"

for f in /etc/nginx/certs/fullchain.pem /etc/nginx/certs/privkey.pem; do
    [ -s "$f" ] || fail "$f bulunamadı. Sertifikayı nginx/certs/ klasörüne koyun (docs/KURULUM.md, 'Sertifika')."
done

# INTERNAL_NETWORKS: boşlukla ya da virgülle ayrılmış CIDR listesi (iç ağ ve VPN alt ağları).
networks="${INTERNAL_NETWORKS:-127.0.0.1/32 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16}"
out=/etc/nginx/internal-networks.conf
{
    echo "# Otomatik üretildi (INTERNAL_NETWORKS). Elle değiştirmeyin."
    for net in $(echo "$networks" | tr ',' ' '); do
        case "$net" in
            *[!0-9a-fA-F:./]*) fail "INTERNAL_NETWORKS içinde geçersiz değer: $net" ;;
        esac
        echo "$net 1;"
    done
} >"$out"
echo "05-deterjan-erp.sh: iç ağ izin listesi: $(echo "$networks" | tr ',' ' ')"
