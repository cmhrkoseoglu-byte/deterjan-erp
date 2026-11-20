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
| 21 | Demo kullanıcılar yok (`create_demo_users` üretimde çalışmaz); her çalışanın kendi kişisel hesabı var, ortak hat, vardiya ya da tablet hesabı yok (ortak tablette herkes kendi hesabıyla girer, işi bitince çıkış yapar; DECISIONS.md 2026-11-18) | Elle |
| 22 | İki aşamalı doğrulama admin ve yönetim rollerinde zorunlu (`OTP_REQUIRED_ROLES=admin,yonetim`); bu rollerdeki kullanıcılar kurdu, kurtarma kodlarını sakladı. 04.11.2026'dan beri geçici olarak zorunlu değil (DECISIONS.md); yetki ekranı (kişiye özel yetkiler, Paket B) canlıya alınmadan önce yeniden açılır | Elle |
| 23 | Ortak saha tabletleri Sistem > Bu cihaz ile "saha tableti" işaretlendi | Elle |
| 24 | Hesap kilidi ve hareketsizlik süresi bir kez denendi (yanlış şifre ×5; tablette 10 dk bekleme) | Elle |
| 25 | Superuser hesabı yalnızca bir/iki kişide; yönetim paneline giriş 2FA istiyor (madde 22 ile birlikte yeniden açılır). Django yönetim panelinde roller, süper kullanıcı ve panele giriş işaretleri salt okunur; mevcut bir kullanıcının rolleri yalnızca Sistem > Kullanıcılar > Yetkiler'den, gerekçe yazılarak değişir (Paket B ile) | Elle |
| 31 | Canlıya geçiş > Hazırlık'ta "Her görevi alabilecek biri var" Tamam (Sistem > Sistem durumu'nda da Normal) | Elle |
| 32 | Sistem > Rol yetkileri > **Excel'e aktar** dosyası gözden geçirildi: kişiye özel ayarlar gerekçeli ve beklenen kişilerde, görev ayrılığı sayfasındaki riskli birleşimler bilinçli | Elle |

## İzleme ve KVKK

| # | Kontrol | Tür |
|---|---|---|
| 26 | Dış izleme aracı (ör. Uptime Kuma) `/api/v1/ops/health/` ucunu 5 dakikada bir yokluyor, hata halinde e-posta/SMS | Elle |
| 27 | Hata takibi (`SENTRY_DSN`) tanımlı ya da bilinçli olarak kapalı | Elle |
| 28 | Admin rolünde en az bir kişi bildirimleri izliyor (yedek, disk, kilit uyarıları admin'e gider) | Elle |
| 29 | `docs/KVKK.md` envanteri firma tarafından gözden geçirildi; aydınlatma metni ve VERBİS kaydı güncel | Elle |
| 30 | Bağımlılık güvenlik taraması (pip-audit, npm audit) CI'da yeşil | CI |

## Müşteri ve tedarikçi portalı

Portal (docs/plan/musteri-siparis-takibi.md §4) dış firmalara açılmadan önce:

| # | Kontrol | Tür |
|---|---|---|
| 33 | Portal adresi: alan adı olana kadar bugünkü adres (`https://<ip>.sslip.io`) kullanılır (CUMHUR, 2026-11-20); sertifika geçerli. Alan adı alınınca KURULUM.md §14 "Alan adına geçiş" uygulanır, yeni adres çalışanlara ve portal kullanıcılarına duyurulur | Elle |
| 34 | Aydınlatma metni (`/aydinlatma`) firmanın bilgileriyle dolduruldu, hukuk danışmanı onayladı ve "taslak" uyarısı kaldırıldı (`PrivacyNoticePage.tsx`, `APPROVED`); KVKK envanteri (madde 29) portal satırlarıyla gözden geçirildi | Elle |
| 35 | Bir deneme müşteri ve bir deneme tedarikçi hesabıyla girildi: ilk girişte şifre değiştirildi; yalnız kendi firmasının siparişleri, sevkiyat ya da teslimatları ve cari hesabı göründü; başka bir firmanın sipariş adresi elle yazılınca "bulunamadı" geldi; `/sevkiyat`, `/depo` gibi çalışan adresleri portala döndü | Elle |
| 36 | Portal kullanıcısıyla `/api/v1/inventory/lots/` ve `/api/v1/masterdata/materials/` istekleri `403 portal_forbidden` döndü; `/admin/` açılmadı | Elle |
| 37 | Müşteri nüshası irsaliyede lot, SKT ve açık şoför TC'si yok; açılışı sevkiyatın Geçmiş panelinde "İrsaliye görüntülendi (portal)" olarak göründü | Elle |
| 38 | Portal hesapları yalnız gerçekten yetkili kişilere açıldı (her yetkiliye ayrı hesap, ortak hesap yok); hesap bilgisi ve geçici şifre kişiye güvenli yoldan iletildi | Elle |
| 40 | Deneme müşteri hesabıyla bir sipariş talebi gönderildi; sevkiyata "Portal talebi incele" görevi düştü; talep siparişe çevrildi (taslak sipariş açıldı) ve bir başkası gerekçeyle reddedildi; müşteri ikisini de portalda gördü | Elle |
| 41 | SMTP tanımlandı (`.env.prod`: `EMAIL_URL`, `DEFAULT_FROM_EMAIL`; gerekirse `PORTAL_BASE_URL`); deneme müşteri hesabına sipariş onayı ve sevk e-postası geldi, fiyat ve şoför bilgisi yok, bağlantı portalda açıldı; yönetim panelinde portal e-postaları "Gönderildi" | Elle |
| 39 | Duman testi portal satırları (girişsiz 401, çalışan 403) yeşil (`scripts/smoke_test.sh`) | Otomatik |

