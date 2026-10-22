#!/usr/bin/env bash
# Sistemi boş bir Ubuntu 24.04 bulut sunucusuna (VPS, root) tek komutla kurar. Tekrar çalıştırılırsa
# son sürüme günceller; veriye dokunmaz.
#
#   KIP=canli  (varsayılan) gerçek kullanım: demo veri yok, admin/yönetim için 2FA zorunlu,
#              ilk yönetici hesabını açar (docs/KURULUM.md §14)
#   KIP=egitim demo veriyle eğitim ortamı (docs/EGITIM-ORTAMI.md); EGITIM_SIFRE zorunlu
#
# Kullanım (root olarak):
#   curl -fsSL https://raw.githubusercontent.com/cmhrkoseoglu-byte/deterjan-erp/main/scripts/bulut-kur.sh | bash
#
# Değişkenler (hepsi isteğe bağlı, EGITIM_SIFRE yalnızca eğitimde zorunlu):
#   ADRES      alan adı, ör. erp.firma.com.tr (DNS kaydı sunucu IP'sini göstermeli);
#              verilmezse <ip>.sslip.io
#   EPOSTA     Let's Encrypt sertifika uyarıları için e-posta (canlıda önerilir)
#   FIRMA_ADI  irsaliye ve etiketlerde görünen firma adı (sonra .env.prod'dan da değişir)
#   DAL        kurulacak git dalı, varsayılan main
#   SSH_PORT   güvenlik duvarında açık kalacak SSH portu; verilmezse sshd ayarından bulunur
# Eğitim betiğinin eski adları (EGITIM_ADRES, EGITIM_EPOSTA, EGITIM_DAL) de geçerlidir.
set -euo pipefail

MODE="${KIP:-canli}"
ADDRESS="${ADRES:-${EGITIM_ADRES:-}}"
EMAIL="${EPOSTA:-${EGITIM_EPOSTA:-}}"
BRANCH="${DAL:-${EGITIM_DAL:-main}}"
REPO_URL="${KURULUM_REPO:-${EGITIM_REPO:-https://github.com/cmhrkoseoglu-byte/deterjan-erp.git}}"
APP_DIR="${KURULUM_DIZIN:-${EGITIM_DIZIN:-/srv/deterjan-erp}}"

log() { printf '\n==> %s\n' "$*"; }
fail() {
    printf 'HATA: %s\n' "$*" >&2
    exit 1
}

[ "$(id -u)" -eq 0 ] || fail "root olarak çalıştırın (sudo -i)."
case "$MODE" in
canli)
    INFO_FILE=/root/erp-bilgi.txt
    ;;
egitim)
    INFO_FILE=/root/egitim-bilgi.txt
    password="${EGITIM_SIFRE:-}"
    [ "${#password}" -ge 10 ] || fail "EGITIM_SIFRE en az 10 karakter olmalı."
    [ "$password" != "Demo.12345" ] || fail "Örnek şifre (Demo.12345) kullanılamaz; sunucu internete açık."
    # .env.prod'a ve sed'e güvenle yazılabilsin diye yalnızca bu karakterler.
    [[ "$password" =~ ^[A-Za-z0-9._@%+=:,!-]+$ ]] ||
        fail "EGITIM_SIFRE yalnızca harf, rakam ve . _ @ % + = : , ! - içerebilir (Türkçe harf, boşluk, tırnak olmasın)."
    ;;
*) fail "KIP canli ya da egitim olmalı (verilen: $MODE)." ;;
esac
if [ -n "${FIRMA_ADI:-}" ] && [[ "$FIRMA_ADI" == *[\|\&\\\"\']* ]]; then
    fail "FIRMA_ADI içinde | & \\ ve tırnak olmasın."
fi
. /etc/os-release 2>/dev/null || true
[ "${ID:-}" = "ubuntu" ] || fail "Bu betik Ubuntu içindir (24.04 önerilir); bulunan: ${PRETTY_NAME:-bilinmiyor}."

export DEBIAN_FRONTEND=noninteractive

log "Paketler kuruluyor (git, certbot, ufw)"
apt-get update -qq
apt-get install -y -qq ca-certificates curl git certbot ufw openssl >/dev/null
if [ "$MODE" = canli ]; then
    # Canlı sunucuda işletim sistemi güvenlik güncellemeleri kendiliğinden kurulsun (kontrol listesi 15).
    apt-get install -y -qq unattended-upgrades >/dev/null
    printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' \
        >/etc/apt/apt.conf.d/20auto-upgrades
    timedatectl set-timezone Europe/Istanbul || true
fi

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

if [ -z "$ADDRESS" ]; then
    ip="$(curl -fsS4 https://api.ipify.org || curl -fsS4 https://ifconfig.me)"
    [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "Sunucunun genel IP adresi bulunamadı; ADRES verin."
    ADDRESS="${ip//./-}.sslip.io"
fi
address="$ADDRESS"
log "Adres: https://$address"

# SSH portu sağlayıcıya göre değişir (ör. Turhost 22 yerine başka port verir). sshd'nin dinlediği
# portlar ve bu oturumun geldiği port açılmazsa güvenlik duvarı sizi sunucudan kilitler.
ssh_ports="$(
    {
        [ -z "${SSH_PORT:-}" ] || echo "$SSH_PORT"
        sshd -T 2>/dev/null | awk '$1 == "port" {print $2}'
        [ -z "${SSH_CONNECTION:-}" ] || echo "${SSH_CONNECTION##* }"
    } | grep -E '^[0-9]+$' | sort -un
)"
[ -n "$ssh_ports" ] || ssh_ports=22
log "Güvenlik duvarı: SSH ($(echo $ssh_ports | tr ' ' ',')), 80 ve 443"
for port in $ssh_ports; do
    ufw allow "$port/tcp" >/dev/null
done
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
# Bir kipte kurulmuş sunucu öbür kipe çevrilmez: eğitimin demo kayıtları gerçek veriye karışmasın.
if grep -qE '^TRAINING_MODE=true' .env.prod; then current=egitim; else current=canli; fi
if grep -qE '^KURULUM_KIPI=' .env.prod; then
    [ "$current" = "$MODE" ] ||
        fail "Bu sunucu '$current' kipinde kurulu; '$MODE' kipine çevrilmez. Yeni bir sunucu kullanın."
fi
set_env() {
    if grep -qE "^$1=" .env.prod; then
        sed -i "s|^$1=.*|$1=$2|" .env.prod
    else
        printf '%s=%s\n' "$1" "$2" >>.env.prod
    fi
}
set_env KURULUM_KIPI "$MODE"
# Yönetim paneli ve API belgeleri internetten açılmaz; yalnızca sunucunun kendisinden ve ileride
# kurulacak VPN ağından (WireGuard 10.8.0.0/24, KURULUM.md §3).
if [ "$MODE" = egitim ]; then
    set_env TRAINING_MODE true
    set_env DEMO_USER_PASSWORD "$password"
    # Ortak demo hesaplarını birden çok kişi kullanır; 2FA ilk kurana bağlanırdı (plan kararı).
    set_env OTP_REQUIRED_ROLES ""
    set_env INTERNAL_NETWORKS 127.0.0.1/32
    set_env WEB_CONCURRENCY 2
    set_env SENTRY_ENVIRONMENT training
    grep -qE '^COMPANY_NAME=.+' .env.prod || set_env COMPANY_NAME "Eğitim Ortamı"
else
    set_env TRAINING_MODE false
    set_env INTERNAL_NETWORKS 127.0.0.1/32,10.8.0.0/24
    grep -qE '^WEB_CONCURRENCY=.+' .env.prod || set_env WEB_CONCURRENCY "$(nproc)"
fi
[ -z "${FIRMA_ADI:-}" ] || set_env COMPANY_NAME "$FIRMA_ADI"
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
    if [ -n "$EMAIL" ]; then
        email_args=(-m "$EMAIL")
    else
        email_args=(--register-unsafely-without-email)
    fi
    certbot certonly --standalone --non-interactive --agree-tos "${email_args[@]}" -d "$address"
fi
"$hook_dir/deploy/deterjan-erp.sh"
systemctl enable --now certbot.timer >/dev/null 2>&1 || true

log "Servisler derleniyor ve başlatılıyor (ilk sefer 5-10 dk)"
scripts/prod-compose.sh up -d --build --wait

umask 077
if [ "$MODE" = egitim ]; then
    log "Demo kullanıcılar ve demo veri yükleniyor"
    scripts/prod-compose.sh exec -T backend python manage.py create_demo_users
    scripts/prod-compose.sh exec -T backend python manage.py seed_demo
else
    log "İlk yönetici hesabı"
    # Harf + rakam içeren rastgele şifre; yalnızca ilk kurulumda kullanılır (hesap varsa değişmez).
    admin_password="$(openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | head -c 14)Ab3"
    admin_out="$(scripts/prod-compose.sh exec -T -e FIRST_ADMIN_PASSWORD="$admin_password" backend \
        python manage.py create_first_admin --username yonetici)"
    echo "$admin_out"
    if [[ "$admin_out" == *"açıldı"* ]]; then
        cat >/root/erp-ilk-giris.txt <<EOF
İlk yönetici girişi: https://$address
Kullanıcı adı: yonetici
Şifre: $admin_password
İlk girişte iki aşamalı doğrulama (ör. Google Authenticator) kurulur ve kurtarma kodları verilir.
Sonra Güvenlik sayfasından şifreyi değiştirin ve bu dosyayı silin: rm /root/erp-ilk-giris.txt
EOF
    fi
fi

log "Kontrol"
health="$(curl -fsS "https://$address/api/v1/health/")" || fail "Sağlık kontrolü geçmedi: https://$address/api/v1/health/"
site="$(curl -fsS "https://$address/api/v1/site/")"
expected='"training_mode":false'
[ "$MODE" = egitim ] && expected='"training_mode":true'
case "$site" in
*"$expected"*) ;;
*) fail "Ortam kipi beklenen gibi değil ($MODE): $site" ;;
esac

if [ "$MODE" = egitim ]; then
    cat >"$INFO_FILE" <<EOF
Eğitim ortamı hazır: https://$address
Kullanıcı adları rol kodlarıdır: admin, yonetim, planlama, depo, uretim, laboratuvar, dolum,
sevkiyat, satin_alma. Hepsinin şifresi EGITIM_SIFRE ile verdiğiniz şifredir.
Sağlık: $health
EOF
else
    cat >"$INFO_FILE" <<EOF
Sistem hazır: https://$address
Kullanıcıları yonetici hesabıyla Sistem > Kullanıcılar ekranından açın.
Kalan işler (docs/CANLI-KONTROL-LISTESI.md): dış yedek yeri, etiket yazıcıları için VPN,
KVKK aydınlatma metni ve VERBİS, sayım günü açılış stoku (docs/GECIS-PLANI.md).
Sağlık: $health
EOF
fi
log "HAZIR"
cat "$INFO_FILE"
[ ! -f /root/erp-ilk-giris.txt ] || cat /root/erp-ilk-giris.txt
