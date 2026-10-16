#!/usr/bin/env bash
# Fabrika içi sertifika: bir iç sertifika otoritesi (CA) ve bu CA'nın imzaladığı sunucu sertifikası.
#
# Kullanım: scripts/gen-selfsigned-cert.sh <ad veya IP> [ad veya IP ...]
#   Örnek:  scripts/gen-selfsigned-cert.sh erp.firma.local 192.168.1.10
#
# Üretilenler:
#   nginx/certs/fullchain.pem, nginx/certs/privkey.pem  -> nginx kullanır
#   nginx/internal-ca/ca.key                            -> CA anahtarı: GİZLİ, sunucudan çıkarmayın
#   nginx/internal-ca/ca.crt (PEM), ca.cer (DER)        -> tabletlere ve bilgisayarlara kurulacak
#
# CA zaten varsa yeniden kullanılır: sunucu sertifikası yenilendiğinde (ör. 2 yılda bir ya da yeni
# bir ad eklendiğinde) cihazlara tekrar bir şey kurmak gerekmez.
#
# ÖNEMLİ: ca.crt her tablet ve bilgisayara BİR KEZ "güvenilen kök sertifika" olarak kurulmalıdır,
# yoksa tarayıcı "bağlantı güvenli değil" uyarısı verir (adımlar: docs/KURULUM.md, "Sertifika").
# Sertifika değiştikten sonra: scripts/prod-compose.sh exec nginx nginx -s reload
set -euo pipefail

cd "$(dirname "$0")/.."
CERT_DIR="${CERT_DIR:-nginx/certs}"
CA_DIR="${CA_DIR:-nginx/internal-ca}"
CA_DAYS="${CA_DAYS:-3650}"
# Apple cihazları 825 günden uzun sunucu sertifikalarını kabul etmez.
SERVER_DAYS="${SERVER_DAYS:-825}"
CA_NAME="${CA_NAME:-Deterjan ERP Ic Sertifika Otoritesi}"

if [ $# -lt 1 ]; then
    sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
fi
command -v openssl >/dev/null || {
    echo "HATA: openssl gerekli (sudo apt install openssl)" >&2
    exit 1
}

mkdir -p "$CERT_DIR" "$CA_DIR"
chmod 700 "$CA_DIR"
umask 077

if [ ! -s "$CA_DIR/ca.key" ] || [ ! -s "$CA_DIR/ca.crt" ]; then
    echo "- iç CA oluşturuluyor ($CA_DAYS gün)"
    openssl req -x509 -new -nodes -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -sha256 -days "$CA_DAYS" \
        -keyout "$CA_DIR/ca.key" -out "$CA_DIR/ca.crt" -subj "/O=Deterjan ERP/CN=$CA_NAME" \
        -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
        -addext "keyUsage=critical,keyCertSign,cRLSign" \
        -addext "subjectKeyIdentifier=hash"
else
    echo "- mevcut iç CA kullanılıyor: $CA_DIR/ca.crt"
fi
openssl x509 -in "$CA_DIR/ca.crt" -outform der -out "$CA_DIR/ca.cer"
chmod 644 "$CA_DIR/ca.crt" "$CA_DIR/ca.cer"

san=""
for name in "$@"; do
    if [[ "$name" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || [[ "$name" == *:* ]]; then
        san="${san:+$san,}IP:$name"
    else
        san="${san:+$san,}DNS:$name"
    fi
done

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cat >"$work/ext.cnf" <<CNF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature
extendedKeyUsage=serverAuth
subjectAltName=$san
authorityKeyIdentifier=keyid,issuer
subjectKeyIdentifier=hash
CNF

echo "- sunucu sertifikası: $san ($SERVER_DAYS gün)"
openssl req -new -nodes -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -sha256 \
    -keyout "$work/privkey.pem" -out "$work/server.csr" -subj "/O=Deterjan ERP/CN=$1"
openssl x509 -req -in "$work/server.csr" -CA "$CA_DIR/ca.crt" -CAkey "$CA_DIR/ca.key" \
    -CAcreateserial -CAserial "$CA_DIR/ca.srl" -days "$SERVER_DAYS" -sha256 \
    -extfile "$work/ext.cnf" -out "$work/server.crt" 2>/dev/null

cat "$work/server.crt" "$CA_DIR/ca.crt" >"$CERT_DIR/fullchain.pem"
install -m 600 "$work/privkey.pem" "$CERT_DIR/privkey.pem"
chmod 644 "$CERT_DIR/fullchain.pem"
# nginx ana süreci root olarak anahtarı okur; worker'lar okumaz.

echo
echo "Hazır:"
echo "  $CERT_DIR/fullchain.pem, $CERT_DIR/privkey.pem  (nginx)"
echo "  $CA_DIR/ca.crt (PEM) ve $CA_DIR/ca.cer (DER)  -> tablet/PC'lere BİR KEZ kurun"
echo "  $CA_DIR/ca.key -> GİZLİ; yedekleyin ama paylaşmayın"
openssl x509 -in "$CERT_DIR/fullchain.pem" -noout -subject -enddate -ext subjectAltName 2>/dev/null || true
