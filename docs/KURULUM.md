# Üretim Kurulumu (Fabrika Sunucusu)

Bu belge, Deterjan ERP'yi fabrikadaki sunucuya kuracak ve işletecek **bilgi işlem sorumlusu** içindir.
Aynı kurulum bir bulut sanal sunucusunda da çalışır (bkz. [Bulut sunucusu](#13-bulut-sunucusu)). Bulutta
tek komutla kurulum (D-21, Turhost): [bölüm 14](#14-bulut-sunucusuna-tek-komutla-kurulum).

Kısaca mimari: tek sunucuda Docker Compose ile çalışan servisler.

| Servis | Görevi | Dışarı açık mı? |
|---|---|---|
| `nginx` | HTTPS (443), HTTP→HTTPS yönlendirme (80), derlenmiş arayüz, statik dosyalar | **Evet**: 80, 443 |
| `backend` | Django API + WebSocket (uvicorn) | Hayır |
| `worker`, `beat` | Arka plan işleri ve zamanlanmış görevler (Celery) | Hayır |
| `migrate` | Her açılışta bir kez: veritabanı güncellemesi, statik dosyalar, roller | Hayır |
| `db` | PostgreSQL 16 | Hayır |
| `redis` | Bildirim kanalı, iş kuyruğu, önbellek (şifreli) | Hayır |
| `backup` | Gece yedeği, haftalık geri yükleme testi, dış kopya | Hayır |

Bütün komutlar depo kökünden çalıştırılır. `scripts/prod-compose.sh` şu komutun kısaltmasıdır:
`docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.prod ...`

---

## 1. Sunucu gereksinimleri

**Önerilen donanım** (≈ 30–60 eşzamanlı kullanıcı, 10 yıl veri için):

| Kaynak | En az | Önerilen | Not |
|---|---|---|---|
| İşlemci | 4 çekirdek | 8 çekirdek | `WEB_CONCURRENCY` ≈ çekirdek sayısı |
| Bellek | 8 GB | 16 GB | Servis bellek sınırları toplamı ≈ 7 GB |
| Sistem diski | 64 GB SSD | 128 GB SSD | İşletim sistemi + Docker imajları |
| Veri diski | 2 × 500 GB SSD, **RAID 1** | 2 × 1 TB SSD, RAID 1 | Veritabanı, ekler, yerel yedekler |
| Dış yedek | 1–2 adet USB disk ya da NAS | | Sunucudan **ayrı** bir yerde saklanır |

Tahmin: veritabanı yılda birkaç GB büyür; asıl yer ekler (fotoğraf, PDF) ve 30 günlük yerel yedeklerdir.
Bir yedeğin boyutunu ilk haftadan sonra `<BACKUP_DIR>/daily/*/` klasörlerinden görüp diski ona göre büyütün.

- **RAID 1:** iki veri diski aynalanır; biri bozulursa sistem çalışmaya devam eder. Donanım RAID kartı
  ya da Linux yazılım RAID'i (`mdadm`) kullanılabilir. RAID **yedek değildir** (silinen kayıt iki
  diskte birden silinir); yedekleme ayrıca yapılır (bölüm 9).
- **UPS:** sunucu ve ağ anahtarı UPS'e bağlanır. Elektrik kesildiğinde, akü bitmeden sunucunun
  **kendini düzgün kapatması** gerekir (aksi halde veritabanı bozulabilir):
  - APC marka UPS: `sudo apt install apcupsd`, `/etc/apcupsd/apcupsd.conf` içinde
    `UPSCABLE usb`, `UPSTYPE usb`, `BATTERYLEVEL 30`, `MINUTES 5`.
  - Diğer markalar: `sudo apt install nut` (Network UPS Tools), `upsmon` ile `SHUTDOWNCMD "/sbin/shutdown -h now"`.
  - Docker servisleri `restart: unless-stopped` olduğundan elektrik geldiğinde sunucu açılınca kendiliğinden başlar.
    BIOS'ta "elektrik gelince aç" (AC power recovery: Power On) ayarını açın.
- **İşletim sistemi:** Ubuntu Server 24.04 LTS (ya da 22.04 LTS). Otomatik güvenlik güncellemeleri:
  `sudo apt install unattended-upgrades && sudo dpkg-reconfigure -plow unattended-upgrades`.
- **Saat:** `timedatectl set-timezone Europe/Istanbul` ve NTP açık olmalı (`timedatectl` → "System clock synchronized: yes").

Veri diskini örneğin `/srv` altına bağlayın ve depoyu oraya alın; Docker'ın veri klasörünü de veri
diskine taşıyın (`/etc/docker/daemon.json` → `{"data-root": "/srv/docker"}`), çünkü veritabanı ve ekler
Docker volume'lerinde durur.

## 2. Docker kurulumu

```bash
# Docker'ın resmi deposundan (Ubuntu paketindeki docker.io eskidir)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER            # oturumu kapatıp açın
docker --version && docker compose version   # Compose v2.24 ya da üstü gerekir

sudo apt install -y git openssl jq
cd /srv && sudo git clone <depo adresi> deterjan-erp && sudo chown -R $USER: deterjan-erp
cd /srv/deterjan-erp && git checkout <sürüm etiketi>   # ör. v1.0.0
```

## 3. Ağ

- Sunucuya **sabit IP** verin (DHCP rezervasyonu ya da netplan'da statik adres) ve iç DNS'te bir ad
  tanımlayın (ör. `erp.firma.local` → `192.168.1.10`). Tabletler ve bilgisayarlar bu adı kullanır;
  sertifika da bu ada verilir.
- Backend, **etiket yazıcılarına TCP 9100** ile doğrudan bağlanır (ZPL). Sunucu ile yazıcılar arasında
  9100 açık olmalı; yazıcılara da sabit IP verin. İleride tartı (terazi) aracısı da sunucuya bağlanacak.
  Test: `nc -vz <yazıcı IP> 9100`.
- Konteynerler Docker'ın varsayılan köprü ağındadır; fabrika ağına normal şekilde çıkabilirler. Fabrika
  ağı `172.16.0.0/12` aralığını kullanıyorsa Docker'ın ağ aralığıyla çakışabilir:
  `/etc/docker/daemon.json` → `"default-address-pools": [{"base": "10.200.0.0/16", "size": 24}]`.

### Güvenlik duvarı (ufw)

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from 192.168.1.0/24 to any port 443 proto tcp   # fabrika iç ağı (kendi aralığınız)
sudo ufw allow from 192.168.1.0/24 to any port 80 proto tcp    # yalnızca https'e yönlendirir
sudo ufw allow from 10.8.0.0/24 to any port 22 proto tcp       # SSH yalnızca VPN'den
sudo ufw allow 51820/udp                                       # WireGuard (VPN sunucusu buradaysa)
sudo ufw enable
```

> **Dikkat:** Docker, yayınladığı portlar (80/443) için ufw kurallarını kendi iptables zincirleriyle
> atlayabilir. Sunucu yalnızca iç ağdaysa sorun değildir; internete doğrudan açıksa ya da kesin kısıtlama
> gerekiyorsa erişimi önündeki güvenlik duvarında/modemde sınırlayın ya da `DOCKER-USER` zincirine kural
> ekleyin.

### Uzaktan erişim: VPN (WireGuard)

Sistem **internete açılmaz**. Fabrika dışından (yönetim, bakım) erişim yalnızca VPN ile yapılır.
WireGuard önerilir (hızlı, basit). Firmanın güvenlik duvarında (FortiGate, pfSense, MikroTik vb.)
WireGuard varsa orada kurun; yoksa sunucuda:

```bash
sudo apt install wireguard
# /etc/wireguard/wg0.conf: Address = 10.8.0.1/24, ListenPort = 51820, her kullanıcı için bir [Peer]
sudo systemctl enable --now wg-quick@wg0
```

Modemde yalnızca UDP 51820 sunucuya yönlendirilir. VPN alt ağı (`10.8.0.0/24`) `.env.prod`'daki
`INTERNAL_NETWORKS` içinde olmalıdır (varsayılan `10.0.0.0/8` bunu kapsar); yönetim paneli (`/admin/`)
ve API dokümantasyonu (`/api/docs/`) yalnızca bu ağlardan açılır, diğer adreslere 403 döner.

## 4. Sertifika (HTTPS)

Uygulama yalnızca HTTPS ile çalışır (oturum çerezleri `Secure`). nginx sertifikayı şu iki dosyadan okur:

```
nginx/certs/fullchain.pem   # sunucu sertifikası + ara sertifikalar
nginx/certs/privkey.pem     # özel anahtar (chmod 600)
```

Sertifika değiştikten sonra: `scripts/prod-compose.sh exec nginx nginx -s reload`.
Üç seçenek vardır:

### a) Firma alan adı + Let's Encrypt (DNS-01)

Firmanın bir alan adı varsa (ör. `firma.com.tr`) iç ağdaki sunucuya `erp.firma.com.tr` adı verilip
**ücretsiz** ve tüm cihazların zaten güvendiği bir sertifika alınabilir. Sunucu internete açılmaz;
doğrulama DNS kaydıyla yapılır (DNS sağlayıcısının API anahtarı gerekir: Cloudflare, Route53 vb.).
`lego` örneği (host'ta çalışır):

```bash
sudo snap install lego   # ya da https://github.com/go-acme/lego/releases
export CLOUDFLARE_DNS_API_TOKEN=...   # sağlayıcıya göre değişir
lego --email bt@firma.com.tr --dns cloudflare --domains erp.firma.com.tr --path /srv/lego run
cp /srv/lego/certificates/erp.firma.com.tr.crt /srv/deterjan-erp/nginx/certs/fullchain.pem
cp /srv/lego/certificates/erp.firma.com.tr.key /srv/deterjan-erp/nginx/certs/privkey.pem
chmod 600 /srv/deterjan-erp/nginx/certs/privkey.pem
```

Yenileme (sertifika 90 gün geçerli) — `crontab -e`:

```
30 3 * * 1 cd /srv && lego --email bt@firma.com.tr --dns cloudflare --domains erp.firma.com.tr --path /srv/lego renew --days 30 --renew-hook "cp /srv/lego/certificates/erp.firma.com.tr.crt /srv/deterjan-erp/nginx/certs/fullchain.pem && cp /srv/lego/certificates/erp.firma.com.tr.key /srv/deterjan-erp/nginx/certs/privkey.pem && cd /srv/deterjan-erp && scripts/prod-compose.sh exec -T nginx nginx -s reload"
```

İç DNS'te `erp.firma.com.tr` → sunucunun iç IP'si tanımlanmalıdır. `certbot` ile de aynı yapılabilir
(`certbot certonly --manual --preferred-challenges dns` ya da DNS eklentisiyle).

### b) Satın alınmış firma sertifikası

Sertifika sağlayıcısından gelen sunucu sertifikası ve ara sertifikalar **sırayla** birleştirilir:

```bash
cat erp_firma_com_tr.crt ara_sertifika.crt > nginx/certs/fullchain.pem
cp erp_firma_com_tr.key nginx/certs/privkey.pem && chmod 600 nginx/certs/privkey.pem
```

### c) İç sertifika otoritesi (alan adı yoksa)

```bash
scripts/gen-selfsigned-cert.sh erp.firma.local 192.168.1.10
```

Bu komut bir iç CA (`nginx/internal-ca/ca.crt`) ve ona bağlı sunucu sertifikası üretir. **CA sertifikası
her tablet ve bilgisayara bir kez kurulmalıdır**, yoksa tarayıcı "bağlantınız gizli değil" uyarısı
verir. Sunucu sertifikası 825 günde bir (ya da yeni bir ad eklendiğinde) aynı komutla yenilenir; CA
değişmediği için cihazlara tekrar bir şey kurulmaz. `nginx/internal-ca/ca.key` gizlidir: sunucudan
çıkarmayın, ama bir kopyasını kasada/şifreli diskte saklayın.

`ca.crt` (ya da Windows/Android için `ca.cer`) dosyasını cihazlara e-posta, USB ya da iç web sayfasıyla
dağıtın:

- **Android:** Ayarlar → Güvenlik → Şifreleme ve kimlik bilgileri → Sertifika yükle → **CA sertifikası**
  → dosyayı seçin (menü adları markaya göre değişir). Chrome yeniden başlatılır.
- **iPad / iPhone:** Dosyayı açın → "Profil indirildi" → Ayarlar → Genel → VPN ve Aygıt Yönetimi →
  profili yükleyin. Ardından **Ayarlar → Genel → Hakkında → Sertifika Güven Ayarları** → "Deterjan ERP İç
  Sertifika Otoritesi" için tam güveni açın (bu adım unutulursa Safari yine uyarır).
- **Windows:** `ca.cer`'e çift tıklayın → Sertifika Yükle → Yerel Makine → "Tüm sertifikaları aşağıdaki
  depolama alanına yerleştir" → **Güvenilen Kök Sertifika Yetkilileri**. Çok bilgisayar varsa Active
  Directory Grup İlkesi ile dağıtın. Firefox kendi deposunu kullanır: `about:config` →
  `security.enterprise_roots.enabled = true`.

## 5. .env.prod hazırlama

```bash
scripts/init-env-prod.sh erp.firma.local          # birden çok ad: ... erp.firma.local 192.168.1.10
nano .env.prod
```

Betik `.env.prod.example`'ı kopyalar, `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`'ü
rastgele üretir, `SERVER_NAME`, `DJANGO_ALLOWED_HOSTS` ve `DJANGO_CSRF_TRUSTED_ORIGINS`'i verilen adla
doldurur ve dosyayı `chmod 600` yapar. Elle doldurmak isterseniz:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"   # DJANGO_SECRET_KEY
openssl rand -hex 32                                             # POSTGRES_PASSWORD, REDIS_PASSWORD
```

Sonra kontrol edin: firma bilgileri (`COMPANY_*`; yalnızca ilk değer, sonra **Ana veriler > Firma
bilgileri** ekranından değiştirilir), `INTERNAL_NETWORKS` (iç ağ + VPN), `BACKUP_*`
(bölüm 9), `SENTRY_DSN` (bölüm 12), `OTP_REQUIRED_ROLES` ve oturum/kilitleme süreleri.

- `.env.prod` **depoya girmez**; içeriğini şifre kasasında (ör. KeePass) ayrıca saklayın. Sunucu
  kaybolursa yedekten dönmek için bu değerlere (özellikle `POSTGRES_*`) gerekir.
- Uygulama güvensiz ayarla **başlamaz**: örnek/kısa gizli anahtar, `*` içeren ya da boş
  `DJANGO_ALLOWED_HOSTS`, `https://` olmayan CSRF adresi. Hata `scripts/prod-compose.sh logs migrate` ile görülür.
- `POSTGRES_PASSWORD` veritabanı **ilk oluşturulurken** kullanılır; sonradan değiştirmek için önce
  veritabanında da değiştirin:
  `scripts/prod-compose.sh exec db psql -U deterjan -c "ALTER USER deterjan PASSWORD 'yeni'"`,
  sonra `.env.prod`'u güncelleyip `scripts/prod-compose.sh up -d`.

## 6. İlk çalıştırma

```bash
scripts/prod-compose.sh up -d --build --wait     # imajları derler ve başlatır (ilk sefer 3-5 dk)
scripts/prod-compose.sh ps                        # hepsi "healthy", migrate "exited (0)" olmalı
curl -s https://erp.firma.local/api/v1/health/    # {"status":"ok","db":"ok","redis":"ok"}
```

`migrate` servisi her başlatmada veritabanı güncellemelerini uygular, statik dosyaları toplar ve rolleri
(`seed_roles`) oluşturur; backend o bitmeden açılmaz.

İlk yönetici ve kullanıcılar:

```bash
scripts/prod-compose.sh exec backend python manage.py createsuperuser
```

Bu hesapla uygulamaya girip **Sistem > Kullanıcılar** ekranından her çalışana hesap açın ve rollerini
verin: sistem geçici şifre üretip bir kez gösterir, çalışan ilk girişte kendi şifresini belirler
(`docs/DECISIONS.md` "Kullanıcı yönetimi uygulamada"). `admin` ve `yonetim` rolleri iki adımlı
doğrulama (TOTP, ör. Google Authenticator) gerektirir (`OTP_REQUIRED_ROLES`). Demo kullanıcı komutu
(`create_demo_users`) üretimde çalışmaz.

Sonra canlıya geçiş öncesi güvenlik ve KVKK kontrol listesini (`docs/CANLI-KONTROL-LISTESI.md`,
`docs/KVKK.md`) maddesi maddesine uygulayın. Kurulumu doğrulamak için duman testi:

```bash
scripts/prod-compose.sh exec -e SMOKE_PASSWORD='Gecici.Sifre-123' backend python manage.py shell -c \
  "import os; from apps.core.models import User; from django.contrib.auth.models import Group; \
   u, _ = User.objects.get_or_create(username='smoke'); u.set_password(os.environ['SMOKE_PASSWORD']); \
   u.save(); u.groups.add(Group.objects.get(name='depo'))"
SMOKE_CA=nginx/internal-ca/ca.crt SMOKE_PASSWORD='Gecici.Sifre-123' scripts/prod_smoke_test.sh https://erp.firma.local
# Test kullanıcısını sonra Sistem > Kullanıcılar ekranından pasife alın (kullanıcılar silinmez).
```

(Let's Encrypt/satın alınmış sertifikada `SMOKE_CA=/etc/ssl/certs/ca-certificates.crt`.) Duman testi
bir yedek ve bir geri yükleme testi de çalıştırır.

## 7. Günlük işletim

| İş | Komut |
|---|---|
| Durum | `scripts/prod-compose.sh ps` |
| Günlükler | `scripts/prod-compose.sh logs -f --tail=100 backend` (ya da `worker`, `nginx`, `backup`) |
| Yeniden başlatma | `scripts/prod-compose.sh restart backend worker beat` |
| Durdurma / başlatma | `scripts/prod-compose.sh stop` / `scripts/prod-compose.sh up -d` |
| Django komutu | `scripts/prod-compose.sh exec backend python manage.py <komut>` |

Günlükler Docker'ın `json-file` sürücüsündedir; servis başına en çok 5 × 10 MB tutulur
(`/srv/docker/containers/*/*.log`). **`docker compose down -v` kullanmayın**: `-v` veritabanı ve
ekler dahil tüm volume'leri siler.

## 8. Güncelleme

```bash
cd /srv/deterjan-erp
scripts/backup.sh                     # 1. güncelleme öncesi yedek (çalışma kimliğini not edin)
git fetch --tags && git checkout v1.1.0   # 2. yeni sürüm
scripts/prod-compose.sh up -d --build --wait   # 3. derle ve başlat (migrate otomatik)
scripts/prod-compose.sh ps            # 4. hepsi healthy mi?
```

Değişiklik notlarında `.env.prod.example`'a yeni bir değişken eklendiyse `.env.prod`'a da ekleyin
(`diff <(grep -o '^[A-Z_]*=' .env.prod.example) <(grep -o '^[A-Z_]*=' .env.prod)`).

**Geri dönüş:** yeni sürüm sorunluysa ve veritabanı değişikliği (migration) içeriyorsa önceki koda
dönmek yetmez, veritabanı da güncelleme öncesine dönmelidir:

```bash
git checkout v1.0.0
scripts/prod-compose.sh build
scripts/restore.sh <güncelleme öncesi yedeğin kimliği>   # veritabanı + ekler, servisleri yeniden başlatır
```

Güncellemeden sonra girilen kayıtlar bu durumda kaybolur; bu yüzden güncellemeleri mesai dışında yapın.

## 9. Yedekleme

`backup` servisi her gece **02:00**'de (`BACKUP_CRON`) tam yedek alır, her pazar **04:00**'te
(`RESTORE_TEST_CRON`) en son yedeği geçici bir veritabanına geri yükleyerek **test eder**.

### Nereye yazılır?

```
<BACKUP_DIR>/                       # varsayılan ./backups (RAID'li veri diskinde olmalı)
  daily/20261017T020000/
    db.dump                         # PostgreSQL dökümü (pg_dump -Fc, tutarlı anlık görüntü)
    media.tar.gz                    # ekler (fotoğraf, PDF)
    manifest.json                   # tablo satır sayıları, dosya boyutları, SHA-256 özetleri, sürüm
    SHA256SUMS
  status/latest-backup.json         # son yedeğin sonucu (uygulamadaki sistem durumu ekranı okur)
  status/latest-restore-test.json   # son geri yükleme testinin sonucu
  status/history.jsonl              # tüm çalışmaların geçmişi (satır başına bir JSON)
  pre-restore/                      # gerçek geri yüklemeden önce alınan güvenlik dökümleri
```

Yedek önce geçici bir klasöre yazılır, bitince adı değiştirilir; yarım kalan bir yedek hiçbir zaman
tamamlanmış görünmez. `BACKUP_RETENTION_DAYS` (varsayılan 30) günden eski yedekler, **yalnızca yeni yedek
başarıyla alındığında** silinir. `pre-restore/` klasörü otomatik temizlenmez; geri yükleme başarılı
olduktan bir süre sonra elle silin. Yedek klasörleri yalnızca root tarafından okunabilir.

### Dış kopya (zorunlu)

Sunucu çalınır, yanar ya da fidye yazılımına yakalanırsa sunucudaki yedekler de gider. En az bir
kopya **başka bir yerde** durmalıdır. İki yol (birlikte de kullanılabilir):

**a) USB / harici disk.** İki disk alıp haftalık dönüşümlü kullanmak önerilir (biri sunucuda, biri başka binada).

```bash
sudo mkfs.ext4 -L ERPYEDEK /dev/sdX1                     # diski bir kez biçimlendir
sudo mkdir -p /mnt/erp-yedek
echo 'LABEL=ERPYEDEK /mnt/erp-yedek ext4 defaults,nofail 0 2' | sudo tee -a /etc/fstab
sudo mount /mnt/erp-yedek
sudo touch /mnt/erp-yedek/.deterjan-erp-offsite          # "bu doğru disk" işareti (her diske bir kez)
```

`.env.prod`: `BACKUP_OFFSITE_ENABLED=true`, `BACKUP_OFFSITE_DIR=/mnt/erp-yedek`, sonra
`scripts/prod-compose.sh up -d backup`. Her yedekten sonra kopya SHA-256 ile doğrulanır. Disk takılı
değilse (işaret dosyası görünmüyorsa) yedeğin durumu `failed` olur ve uygulamada uyarı çıkar; yerel yedek
yine alınmıştır. **Disk değiştirildikten ya da yeniden bağlandıktan sonra** konteynerin yeni diski
görmesi için: `scripts/prod-compose.sh restart backup`.

**b) NAS ya da uzak sunucu (rclone).** `cp backup/rclone/rclone.conf.example backup/rclone/rclone.conf`,
dosyada NAS bilgilerini girin (SMB, SFTP, S3 örnekleri içinde) ve `.env.prod`'da
`BACKUP_RCLONE_REMOTE=nas:erp-yedek` verin. Şifreyi `rclone obscure` ile yazın:

```bash
scripts/prod-compose.sh run --rm --no-deps --entrypoint rclone backup obscure 'NAS-sifresi'
scripts/prod-compose.sh run --rm --no-deps --entrypoint rclone backup lsd nas:   # bağlantı testi
```

Her yedekten sonra `rclone check` ile doğrulanır; eski uzak yedekler de `BACKUP_RETENTION_DAYS`'e göre silinir.
NAS'ta ERP kullanıcısına yalnızca bu klasörde yazma izni verin; mümkünse NAS'ta anlık görüntü (snapshot)
açın (fidye yazılımı uzak kopyayı da silmeye çalışabilir).

### Durumu kontrol etme

- Uygulamadaki sistem durumu ekranı ve `GET /api/v1/ops/health/` (bölüm 12) son yedek ve son geri
  yükleme testinin durumunu gösterir; son başarılı yedek 26 saatten (`BACKUP_MAX_AGE_HOURS`), son başarılı
  test 8 günden (`RESTORE_TEST_MAX_AGE_DAYS`) eskiyse uyarı verir.
- Komut satırından: `jq . backups/status/latest-backup.json` ve `jq . backups/status/latest-restore-test.json`
  (`status: "ok"`, `offsite: "ok"`, `mismatches: []` olmalı).
- Yedek listesi: `scripts/prod-compose.sh run --rm --no-deps backup list`

### Elle yedek ve elle geri yükleme testi

```bash
scripts/backup.sh            # hemen yedek
scripts/backup.sh --test     # yedek + hemen geri yükleme testi
```

Geri yükleme testi, aynı veritabanı sunucusunda `erp_restore_test_<zaman>` adlı geçici bir veritabanı
açar, yedeği yükler, **her tablonun satır sayısını** yedekteki sayımla karşılaştırır, ek arşivini baştan
sona okur ve geçici veritabanını her durumda siler. Dış kopyadan test etmek için `.env.prod`'da
`RESTORE_TEST_SOURCE=offsite` (ayda bir böyle yapmak iyi bir alışkanlıktır).

### Tam geri yükleme (felaket kurtarma)

> Mevcut veritabanı ve ekler **silinir**, yerine seçilen yedek gelir. Yedekten sonraki kayıtlar kaybolur.

1. Hangi yedeğe dönüleceğini belirleyin: `scripts/prod-compose.sh run --rm --no-deps backup list`
   (genellikle sorundan önceki son gece yedeği).
2. Kullanıcılara sistemin kapanacağını duyurun.
3. Geri yükleyin:
   ```bash
   scripts/restore.sh 20261017T020000          # ya da: scripts/restore.sh latest
   # dış diskten: scripts/restore.sh 20261017T020000 --source offsite
   ```
   Betik onay için **EVET** yazmanızı ister, sonra: nginx/backend/worker/beat'i durdurur → yedeğin
   SHA-256 özetlerini doğrular → mevcut veritabanının güvenlik dökümünü `pre-restore/`'a alır →
   veritabanını silip yeniden oluşturur ve yükler → satır sayılarını kontrol eder → ekleri değiştirir →
   servisleri başlatır (yedek eski bir sürümdense `migrate` veritabanını mevcut koda yükseltir).
4. Uygulamaya girip son kayıtları (son üretim emri, son sevkiyat) kontrol edin.
5. Hemen yeni bir yedek alın: `scripts/backup.sh`.

**Sunucu tamamen kaybolduysa:** yeni sunucuda bölüm 1–5'i uygulayın (aynı `.env.prod` değerleriyle),
dış diskteki/NAS'taki `daily/<kimlik>/` klasörünü yeni sunucunun `<BACKUP_DIR>/daily/` altına
kopyalayın, `scripts/prod-compose.sh up -d --build --wait` ile boş sistemi kaldırın, sonra
`scripts/restore.sh <kimlik>`.

**Geri yükleme yanlışlıkla yapıldıysa:** `pre-restore/<zaman>-deterjan.dump` geri yüklemeden hemen önceki
veritabanıdır. Bu dosyayı bir çalışma klasörüne kopyalayıp `scripts/restore.sh` ile değil, elle
`pg_restore` ile dönülür; bu durumda destek alın.

## 10. Şifre ve anahtar değişimi

- `DJANGO_SECRET_KEY`: değiştirilirse tüm kullanıcıların oturumu kapanır. `.env.prod`'u düzenleyip `scripts/prod-compose.sh up -d`.
- `REDIS_PASSWORD`: `.env.prod`'da değiştirip `scripts/prod-compose.sh up -d` yeterlidir (URL'ler aynı değeri kullanır).
- `POSTGRES_PASSWORD`: bölüm 5'teki `ALTER USER` adımıyla.

## 11. Erişim kısıtları (özet)

- Dışarıdan yalnızca 80 (→ 443 yönlendirme) ve 443 açıktır; db, redis, backend portları yayınlanmaz.
- nginx yalnızca `SERVER_NAME`'deki adlarla gelen istekleri yanıtlar; IP ile ya da başka adla gelen
  istekler yanıtsız kapatılır. Tarayıcıda yazılan adres `SERVER_NAME`'de olmalıdır.
- `/admin/`, `/api/docs/`, `/api/schema/` yalnızca `INTERNAL_NETWORKS` ağlarından açılır.
  Sunucu internete doğrudan açıksa ve Docker'ın kullanıcı alanı vekili (`userland-proxy`) devredeyse
  dışarıdan gelen bağlantılar `172.x` adresinden geliyormuş gibi görünebilir; o durumda
  `INTERNAL_NETWORKS`'ten `172.16.0.0/12`'yi çıkarın (`/etc/docker/daemon.json` → `"userland-proxy": false`).
- Giriş denemeleri hem Django'da (hesap kilitleme, IP başına sınır) hem nginx'te (dakikada 10 istek) sınırlıdır.
- Her yanıtta HSTS, CSP, X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy başlıkları vardır.

## 12. İzleme

- **Dış izleme (önerilen: Uptime Kuma):** başka bir makinede (ör. BT bilgisayarı ya da NAS'ta Docker ile)
  `https://erp.firma.local/api/v1/ops/health/` adresini dakikada bir izleyin. Kimlik doğrulama
  gerektirmez; veritabanı, Redis, son yedek, son geri yükleme testi ve Celery'den biri sorunluysa **503**
  döner. Uptime Kuma'da "HTTP(s) - Keyword" tipiyle `"status":"ok"` aranabilir; bildirim için e-posta/
  Telegram/WhatsApp tanımlayın. İç CA kullanıyorsanız izleme makinesine de CA'yı kurun ya da "ignore TLS"
  seçin. (`/api/v1/health/` yalnızca veritabanı ve Redis'e bakar; Docker'ın kendi sağlık kontrolü içindir.)
- **Hata izleme:** `.env.prod`'da `SENTRY_DSN` verilirse uygulama hataları Sentry'ye (ya da kendi
  sunucunuzda GlitchTip'e) gider; `SENTRY_ENVIRONMENT` ve `APP_VERSION` ile birlikte. Kişisel veri
  gönderilmez; KVKK açısından Türkiye'de/kendi sunucunuzda çalışan GlitchTip tercih edilebilir.
- **Günlükler:** `scripts/prod-compose.sh logs --since 1h backend worker nginx backup`.
- **Disk:** uygulama disk doluluğunu (`OPS_DISK_ALERT_PCT`, varsayılan %85) izler ve uyarır. Ayrıca
  `df -h /srv` ve `docker system df`. Eski imajları temizlemek için: `docker image prune`.
- **RAID:** yazılım RAID'de `cat /proc/mdstat` (`[UU]` olmalı); `mdadm --monitor` için `MAILADDR` ayarlayın.
  Donanım RAID'de kartın yönetim aracıyla e-posta uyarısı açın. Diskler için `smartctl -H /dev/sdX`.
- **UPS:** `apcaccess status` (apcupsd) ya da `upsc <ups>` (NUT).

## 13. Bulut sunucusu

Aynı compose dosyaları bir bulut sanal sunucusunda değişiklik olmadan çalışır. Farklar:

- **KVKK:** kişisel veri (çalışan adları, müşteri bilgileri) içerdiği için **Türkiye'deki bir veri
  merkezi** seçin (yurt dışına aktarım ayrı açık rıza/izin gerektirir); bkz. `docs/KVKK.md`.
- Sunucu internete açıktır: bulut güvenlik grubunda **yalnızca 443** (ve Let's Encrypt HTTP doğrulaması
  kullanılmıyorsa 80'i de kapatın) açılır; SSH yalnızca VPN'den ya da sabit firma IP'sinden.
- Sertifika: seçenek (a) Let's Encrypt.
- `INTERNAL_NETWORKS` yalnızca VPN alt ağını içermeli (`10.8.0.0/24` gibi); varsayılan geniş aralıkları
  daraltın ve bölüm 11'deki `userland-proxy` notunu uygulayın.
- Etiket yazıcıları ve tartı fabrika ağındadır; bulut sunucusunun onlara ulaşması için fabrika ile bulut
  arasında site-to-site VPN gerekir (yazıcıya TCP 9100).
- Dış yedek: rclone ile fabrikadaki NAS'a ya da başka bir bölgedeki (yine Türkiye) nesne deposuna.

## 14. Bulut sunucusuna tek komutla kurulum

D-21 (2026-10-21): sistem Turhost'taki bulut sunucusunda gerçek veriyle çalışır. Bölüm 2-6'daki adımları
`scripts/bulut-kur.sh` sırayla yapar. Gerekenler: **Ubuntu 24.04**, **root yetkili VPS** (paylaşımlı
hosting olmaz), en az 4 çekirdek / 8 GB bellek / 80 GB disk, genel IPv4 adresi.

Alan adı kullanılacaksa önce DNS'te `erp.firma.com.tr` için sunucu IP'sini gösteren bir **A kaydı**
açın (sertifika bu adla alınır). Sonra sunucuya root olarak (Turhost panelindeki konsol ya da SSH)
girip:

```bash
export ADRES=erp.firma.com.tr          # alan adı yoksa bu satırı atlayın: adres <ip>.sslip.io olur
export EPOSTA=bt@firma.com.tr          # sertifika süresi uyarıları için
export FIRMA_ADI='Firma Adı A.Ş.'      # irsaliye ve etiketlerde
curl -fsSL https://raw.githubusercontent.com/cmhrkoseoglu-byte/deterjan-erp/main/scripts/bulut-kur.sh | bash
```

İlk kurulum 10-15 dakika sürer. Sonunda adres ve ilk yönetici bilgileri yazılır (ayrıca
`/root/erp-bilgi.txt`, `/root/erp-ilk-giris.txt`). `yonetici` hesabıyla girin; ilk girişte iki aşamalı
doğrulama kurulur. Şifreyi Güvenlik sayfasından değiştirip `/root/erp-ilk-giris.txt`'yi silin.
Kullanıcıları **Sistem > Kullanıcılar** ekranından açın (her çalışana ayrı hesap). Firmanın ticari
bilgilerini (unvan, adres, vergi dairesi, vergi no, ticaret sicil ve MERSİS no) yönetim ya da sistem
yöneticisi **Ana veriler > Firma bilgileri** ekranından girer; irsaliye ve satın alma siparişi buradan
basılır.

Güvenlik duvarı (ufw) yalnızca 80, 443 ve SSH portunu açık bırakır. SSH portu sshd ayarından ve o anki
bağlantıdan bulunur (Turhost gibi 22 dışında port veren sağlayıcılar için); emin olmak için
`export SSH_PORT=23422` gibi açıkça verin.

Betik tekrar çalıştırılırsa sistemi son sürüme günceller (bölüm 8); veriye ve şifrelere dokunmaz. Bir
kipte (canlı/eğitim) kurulan sunucu öbür kipe çevrilmez.

Betiğin yapmadıkları, canlıya geçmeden önce tamamlanır (`docs/CANLI-KONTROL-LISTESI.md`):

- **Dış yedek** (madde 18): yedekler sunucuda `/srv/deterjan-erp/backups` altında birikir; bir kopyası
  rclone ile sunucudan ayrı bir yere (fabrikadaki NAS/PC ya da Türkiye'de bir nesne deposu) gönderilir
  (bölüm 9). O ayarlanana kadar Sistem ekranı uyarı verir.
- **Etiket yazıcıları ve terazi** (madde 16): fabrika ile sunucu arasında VPN (WireGuard, bölüm 3);
  `INTERNAL_NETWORKS` VPN ağını (`10.8.0.0/24`) zaten içerir. VPN gelene kadar etiketler PDF basılır.
- **SSH:** yalnızca anahtarla giriş (`PasswordAuthentication no`), mümkünse yalnızca firma IP'sinden.
- **KVKK** (madde 29): aydınlatma metni ve VERBİS kaydında sunucu yeri (Turhost, Türkiye).
- **Açılış stoku:** sayım günü (`docs/GECIS-PLANI.md`).
