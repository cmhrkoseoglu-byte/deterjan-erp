# Canlıya geçiş güvenlik kontrol listesi

Faz 5 kabul kriteri: "Canlı ortam HTTPS, güvenlik başlıkları ve `DEBUG=False` ile çalışıyor; güvenlik kontrol
listesi tamam." Sistemi kullanıma açmadan önce sunucuda bu liste işaretlenir. Kurulum adımları
`docs/KURULUM.md`'dedir. **Otomatik** satırlar `scripts/prod_smoke_test.sh` ile her CI çalışmasında ve
sunucuda elle doğrulanır; **Elle** satırlar sunucuda kontrol edilir.

## Uygulama ve HTTPS

| # | Kontrol | Nasıl | Tür |
|---|---|---|---|
| 1 | `DEBUG=False`, `config.settings.prod` | Bilinmeyen `/api/v1/xyz` JSON 404 döner, hata sayfası yok | Otomatik |
| 2 | Gizli anahtar rastgele ve ≥ 50 karakter; örnek değer değil | Uygulama aksi halde açılmaz (`prod.py`) | Otomatik |
| 3 | `python manage.py check --deploy` uyarısız | `scripts/prod-compose.sh exec backend python manage.py check --deploy` | Otomatik |
| 4 | HTTP → HTTPS 301, TLS 1.0/1.1 kapalı | duman testi | Otomatik |
| 5 | HSTS, CSP, X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy, COOP | duman testi her yanıtta arar | Otomatik |
| 6 | Oturum çerezi Secure + HttpOnly, CSRF çerezi Secure | duman testi | Otomatik |
| 7 | Bilinmeyen Host başlığına yanıt yok (444) | duman testi | Otomatik |
| 8 | Gerçek sertifika (alan adı ya da firma), son kullanma tarihi takvimde; iç CA ise tüm tablet/PC'lere yüklendi | Tarayıcıda kilit simgesi, uyarısız açılış | Elle |
| 9 | `/admin/` ve `/api/docs/` yalnızca iç ağ/VPN'den (`INTERNAL_NETWORKS`) | VPN dışından dene → 403 | Elle |
| 10 | `.env.prod` yalnızca root okuyabilir (`chmod 600`), depoda gizli bilgi yok | `ls -l .env.prod`; CI gitleaks yeşil | Elle + CI |

## Sunucu ve ağ

| # | Kontrol | Tür |
|---|---|---|
| 11 | Güvenlik duvarı: yalnızca 80/443 iç ağa açık; SSH yalnızca VPN'den; veritabanı ve Redis dışarı kapalı | Elle |
| 12 | Uzaktan erişim yalnızca VPN (WireGuard); her kişiye ayrı anahtar | Elle |
| 13 | RAID 1 sağlıklı (`cat /proc/mdstat` ya da RAID kartı arayüzü); disk arızası e-postası ayarlı | Elle |
| 14 | UPS bağlı; elektrik kesintisinde sunucu düzgün kapanıyor (NUT/apcupsd testi yapıldı) | Elle |
| 15 | İşletim sistemi otomatik güvenlik güncellemeleri açık (`unattended-upgrades`) | Elle |
| 16 | Sunucu etiket yazıcılarına (TCP 9100) ulaşabiliyor; sabit IP ve DNS adı var | Elle |

## Yedek ve geri yükleme

| # | Kontrol | Tür |
|---|---|---|
| 17 | Gece yedeği alınıyor ve Sistem > Sistem durumu "Normal" gösteriyor | Otomatik (izleme) |
| 18 | Ayrı konum kopyası (harici disk / NAS / bulut) çalışıyor; disk sunucudan ayrı yerde | Elle + izleme |
| 19 | İlk geri yükleme testi elle çalıştırıldı ve geçti (`scripts/prod-compose.sh run --rm backup restore-test`) | Elle |
| 20 | Tam geri yükleme provası bir kez yapıldı (`scripts/restore.sh`, KURULUM.md §9) | Elle |

## Kullanıcılar ve giriş

| # | Kontrol | Tür |
|---|---|---|
| 21 | Demo kullanıcılar yok (`create_demo_users` üretimde çalışmaz); her çalışanın kendi hesabı var | Elle |
| 22 | Admin ve yönetim kullanıcıları iki aşamalı doğrulamayı kurdu, kurtarma kodlarını sakladı | Elle |
| 23 | Ortak saha tabletleri Sistem > Bu cihaz ile "saha tableti" işaretlendi | Elle |
| 24 | Hesap kilidi ve hareketsizlik süresi bir kez denendi (yanlış şifre ×5; tablette 10 dk bekleme) | Elle |
| 25 | Superuser hesabı yalnızca bir/iki kişide; yönetim paneline giriş 2FA istiyor | Elle |

## İzleme ve KVKK

| # | Kontrol | Tür |
|---|---|---|
| 26 | Dış izleme aracı (ör. Uptime Kuma) `/api/v1/ops/health/` ucunu 5 dakikada bir yokluyor, hata halinde e-posta/SMS | Elle |
| 27 | Hata takibi (`SENTRY_DSN`) tanımlı ya da bilinçli olarak kapalı | Elle |
| 28 | Admin rolünde en az bir kişi bildirimleri izliyor (yedek, disk, kilit uyarıları admin'e gider) | Elle |
| 29 | `docs/KVKK.md` envanteri firma tarafından gözden geçirildi; aydınlatma metni ve VERBİS kaydı güncel | Elle |
| 30 | Bağımlılık güvenlik taraması (pip-audit, npm audit) CI'da yeşil | CI |
