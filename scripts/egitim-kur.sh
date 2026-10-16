#!/usr/bin/env bash
# Eğitim ortamını boş bir Ubuntu 24.04 bulut sunucusuna tek komutla kurar (docs/EGITIM-ORTAMI.md).
# Demo veriyle çalışır, gerçek veri girilmez. Tekrar çalıştırılırsa sistemi günceller.
#
# Kullanım (root olarak):
#   EGITIM_SIFRE='En-az-10-karakter' bash scripts/egitim-kur.sh
# Bulut panelindeki "cloud-init / user data" kutusuna yapıştırmak için: docs/EGITIM-ORTAMI.md.
#
# Değişkenler:
#   EGITIM_SIFRE   (zorunlu) tüm demo hesapların şifresi; en az 10 karakter, Demo.12345 olamaz
#   EGITIM_ADRES   (isteğe bağlı) alan adı, ör. egitim.firma.com.tr; verilmezse <ip>.sslip.io
#   EGITIM_EPOSTA  (isteğe bağlı) Let's Encrypt sertifika uyarıları için e-posta
#   EGITIM_DAL     (isteğe bağlı) kurulacak git dalı, varsayılan main
set -euo pipefail

REPO_URL="${EGITIM_REPO:-https://github.com/cmhrkoseoglu-byte/deterjan-erp.git}"
BRANCH="${EGITIM_DAL:-main}"
APP_DIR="${EGITIM_DIZIN:-/srv/deterjan-erp}"
INFO_FILE=/root/egitim-bilgi.txt

log() { printf '\n==> %s\n' "$*"; }
fail() {
    printf 'HATA: %s\n' "$*" >&2
    exit 1
}

[ "$(id -u)" -eq 0 ] || fail "root olarak çalıştırın (sudo -i)."
password="${EGITIM_SIFRE:-}"
[ "${#password}" -ge 10 ] || fail "EGITIM_SIFRE en az 10 karakter olmalı."
[ "$password" != "Demo.12345" ] || fail "Örnek şifre (Demo.12345) kullanılamaz; sunucu internete açık."
# .env.prod'a ve sed'e güvenle yazılabilsin diye yalnızca bu karakterler.
[[ "$password" =~ ^[A-Za-z0-9._@%+=:,!-]+$ ]] ||
    fail "EGITIM_SIFRE yalnızca harf, rakam ve . _ @ % + = : , ! - içerebilir (Türkçe harf, boşluk, tırnak olmasın)."

export DEBIAN_FRONTEND=noninteractive

log "Paketler kuruluyor (git, certbot, ufw)"
apt-get update -qq
apt-get install -y -qq ca-certificates curl git certbot ufw openssl >/dev/null

if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
    log "Docker kuruluyor"
    curl -fsSL https://get.docker.com | sh
fi
# Bulut sunucusu internete doğrudan açık: istemci IP'leri nginx'e gerçek adresiyle ulaşsın
# (KURULUM.md §11, userland-proxy notu).
if [ ! -f /etc/docker/daemon.json ]; then
    echo '{"userland-proxy": false}' >/etc/docker/daemon.json
    systemctl restart docker
fi
systemctl enable --now docker >/dev/null

if [ -z "${EGITIM_ADRES:-}" ]; then
    ip="$(curl -fsS4 https://api.ipify.org || curl -fsS4 https://ifconfig.me)"
    [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "Sunucunun genel IP adresi bulunamadı; EGITIM_ADRES verin."
    EGITIM_ADRES="${ip//./-}.sslip.io"
fi
address="$EGITIM_ADRES"
log "Adres: https://$address"

log "Güvenlik duvarı: yalnızca SSH, 80 ve 443"
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

log "Kod alınıyor ($BRANCH)"
if [ -d "$APP_DIR/.git" ]; then
    git -C "$APP_DIR" fetch -q origin "$BRANCH"
    git -C "$APP_DIR" checkout -q -B "$BRANCH" "origin/$BRANCH"
else
    git clone -q --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

if [ ! -f .env.prod ]; then
    log ".env.prod üretiliyor"
    scripts/init-env-prod.sh "$address"
fi
# Eğitim ayarları her çalıştırmada yeniden yazılır (şifre değişikliği dahil).
set_env() {
    if grep -qE "^$1=" .env.prod; then
        sed -i "s|^$1=.*|$1=$2|" .env.prod
    else
        printf '%s=%s\n' "$1" "$2" >>.env.prod
    fi
}
set_env TRAINING_MODE true
set_env DEMO_USER_PASSWORD "$password"
# Ortak demo hesaplarını birden çok kişi kullanır; 2FA ilk kurana bağlanırdı (plan kararı).
set_env OTP_REQUIRED_ROLES ""
# Yönetim paneli ve API belgeleri internetten açılmaz.
set_env INTERNAL_NETWORKS 127.0.0.1/32
set_env WEB_CONCURRENCY 2
set_env SENTRY_ENVIRONMENT training
grep -qE '^COMPANY_NAME=.+' .env.prod || set_env COMPANY_NAME "Eğitim Ortamı"
chmod 600 .env.prod

log "Sertifika (Let's Encrypt)"
mkdir -p nginx/certs
hook_dir=/etc/letsencrypt/renewal-hooks
mkdir -p "$hook_dir/pre" "$hook_dir/deploy" "$hook_dir/post"
cat >"$hook_dir/pre/deterjan-erp.sh" <<EOF
#!/bin/sh
# Yenilemede 80. port boşalsın diye nginx kısa süre durur.
cd "$APP_DIR" && scripts/prod-compose.sh stop nginx || true
EOF
cat >"$hook_dir/deploy/deterjan-erp.sh" <<EOF
#!/bin/sh
cp -L "/etc/letsencrypt/live/$address/fullchain.pem" "$APP_DIR/nginx/certs/fullchain.pem"
cp -L "/etc/letsencrypt/live/$address/privkey.pem" "$APP_DIR/nginx/certs/privkey.pem"
chmod 600 "$APP_DIR/nginx/certs/privkey.pem"
EOF
cat >"$hook_dir/post/deterjan-erp.sh" <<EOF
#!/bin/sh
cd "$APP_DIR" && scripts/prod-compose.sh start nginx || true
EOF
chmod +x "$hook_dir"/*/deterjan-erp.sh
if [ ! -f "/etc/letsencrypt/live/$address/fullchain.pem" ]; then
    "$hook_dir/pre/deterjan-erp.sh" >/dev/null 2>&1 || true
    if [ -n "${EGITIM_EPOSTA:-}" ]; then
        email_args=(-m "$EGITIM_EPOSTA")
    else
        email_args=(--register-unsafely-without-email)
    fi
    certbot certonly --standalone --non-interactive --agree-tos "${email_args[@]}" -d "$address"
fi
"$hook_dir/deploy/deterjan-erp.sh"
systemctl enable --now certbot.timer >/dev/null 2>&1 || true

log "Servisler derleniyor ve başlatılıyor (ilk sefer 5-10 dk)"
scripts/prod-compose.sh up -d --build --wait

log "Demo kullanıcılar ve demo veri yükleniyor"
scripts/prod-compose.sh exec -T backend python manage.py create_demo_users
scripts/prod-compose.sh exec -T backend python manage.py seed_demo

log "Kontrol"
health="$(curl -fsS "https://$address/api/v1/health/")" || fail "Sağlık kontrolü geçmedi: https://$address/api/v1/health/"
site="$(curl -fsS "https://$address/api/v1/site/")"
case "$site" in
*'"training_mode":true'*) ;;
*) fail "Eğitim modu açık değil: $site" ;;
esac

umask 077
cat >"$INFO_FILE" <<EOF
Eğitim ortamı hazır: https://$address
Kullanıcı adları rol kodlarıdır: admin, yonetim, planlama, depo, uretim, laboratuvar, dolum,
sevkiyat, satin_alma. Hepsinin şifresi EGITIM_SIFRE ile verdiğiniz şifredir.
Sağlık: $health
EOF
log "HAZIR"
cat "$INFO_FILE"
