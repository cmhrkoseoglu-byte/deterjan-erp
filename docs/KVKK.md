# KVKK kişisel veri envanteri

Faz 5, Adım 5.5. 6698 sayılı Kişisel Verilerin Korunması Kanunu kapsamında bu sistemde tutulan kişisel
veriler, işleme amacı, hukuki dayanak, kimin gördüğü ve saklama süresi. Hukuki metinler (aydınlatma metni,
VERBİS kaydı) firmanın sorumluluğundadır; bu belge onlara girdi olacak teknik envanterdir. Bir alan
eklendiğinde ya da yetki değiştiğinde bu tablo da güncellenir.

**Veri sorumlusu:** firma (`.env` → `COMPANY_NAME`). **Veri nerede:** fabrikadaki sunucuda PostgreSQL
veritabanı ve ekler klasörü (Karar D-20); her gece yedek ve yedeğin ayrı konumdaki kopyası. Sunucu dışarıya
yalnızca VPN üzerinden açılır; trafik HTTPS ile şifrelidir.

## Envanter

| Kişi grubu | Veri | Tablo / alan | Amaç | Hukuki dayanak (KVKK m.5) | Kim görür | Saklama süresi |
|---|---|---|---|---|---|---|
| Çalışan (sistem kullanıcısı) | Ad soyad, kullanıcı adı, e-posta, telefon | `core_user` | Sisteme giriş, görev ve bildirim atama, kayıtlarda "kim yaptı" | Sözleşmenin ifası (iş sözleşmesi), meşru menfaat | Admin (tümü); diğer kullanıcılar kayıtlarda yalnızca ad soyad | Çalışma süresince; işten ayrılınca hesap pasife alınır (`is_active=False`), kayıtlardaki ad yasal süre (10 yıl) kalır |
| Çalışan | Şifre özeti, iki aşamalı doğrulama anahtarı, kurtarma kodu özetleri | `core_user.password`, `core_totpdevice`, `core_recoverycode` | Kimlik doğrulama | Meşru menfaat (bilgi güvenliği) | Hiç kimse (özet/şifreli; ekranda gösterilmez) | Hesap süresince; 2FA kapatılınca ya da sıfırlanınca silinir |
| Çalışan | Giriş, çıkış ve başarısız giriş kayıtları; IP adresi | `core_auditlog` (login, logout, login_failed) | Bilgi güvenliği, yetkisiz erişim tespiti | Kanuni yükümlülük (5651 ve KVKK m.12 güvenlik tedbiri), meşru menfaat | Admin, yönetim (Denetim günlüğü) | Kayıt kalır; **IP adresi 1 yıl sonra silinir** (`AUDIT_IP_RETENTION_DAYS`, her gece 03:30) |
| Çalışan | İşlem geçmişi (hangi kaydı ne zaman değiştirdi) | `core_auditlog` | Denetim izi (CLAUDE.md kural 7), izlenebilirlik | Kanuni yükümlülük, meşru menfaat | Admin, yönetim | Ticari kayıtlarla aynı: 10 yıl |
| Çalışan | Oturum çerezi ve oturum verisi | `django_session` | Oturumu açık tutmak | Sözleşmenin ifası | — | Hareketsizlikte 60 dk (saha tabletinde 10 dk), en çok 12 saat; süresi dolanlar her gece silinir |
| Çalışan | Hatalı giriş sayacı | `core_loginlockout` (kullanıcı adı) | Kaba kuvvet saldırısına karşı kilit | Meşru menfaat | Admin (kilitli bayrağı) | Kilit bitince 1 gün içinde silinir |
| Şoför | Ad soyad, **TC kimlik no**, araç plakası, taşıyıcı | `sales_shipment.driver_name`, `driver_id_no`, `vehicle_plate`, `carrier` | İrsaliye düzenleme (VUK, e-İrsaliye zorunlu alanları) | Kanuni yükümlülük (VUK 230, e-İrsaliye) | TC no ekranlarda maskelidir (`*******8901`); açık hali yalnızca irsaliye PDF'inde ve irsaliye verisinde. Sevkiyat ve yönetim rolleri | 10 yıl (VUK 253: defter ve belgeler) |
| Şoför | İrsaliye görüntüleme kaydı | `core_auditlog` ("İrsaliye görüntülendi") | TC no'nun kimler tarafından görüldüğünün izi (KVKK m.12) | Kanuni yükümlülük | Admin, yönetim | 10 yıl |
| Müşteri / tedarikçi yetkilisi | Yetkili kişi adı, telefon, e-posta, adres | `masterdata_customer`, `masterdata_supplier` (`contact_person`, `phone`, `email`, `address`) | Sipariş, sevkiyat, satın alma iletişimi | Sözleşmenin ifası, meşru menfaat | Kartı görebilen roller (planlama, yönetim, sevkiyat, satın alma) | Ticari ilişki süresince + 10 yıl; ilişki bitince kart pasife alınır |
| Şahıs firması | Vergi no yerine TCKN | `masterdata_customer.tax_number`, `masterdata_supplier.tax_number` | Fatura, irsaliye | Kanuni yükümlülük | Kartı görebilen roller | 10 yıl |
| Çalışan (personel kartı; sistemi kullanmayanlar dahil) | Sicil no, ad soyad, birim, görev, işe giriş ve çıkış tarihi, telefon; bağlıysa sistem kullanıcısı | `personnel_employee` | Personel listesi, iletişim, işe giriş ve ayrılışın kaydı | Sözleşmenin ifası (iş sözleşmesi), kanuni yükümlülük (İş Kanunu, SGK) | Yalnızca admin ve yönetim (Personel ekranı; kartın değişiklik geçmişi de yalnızca onlara açık) | Çalışma süresince; ayrılınca kart pasife alınır, silinmez. Ayrılıştan sonraki saklama süresi (genel zamanaşımı 10 yıl) firma İK ve hukuk birimiyle teyit edilmeli |
| Çalışanın yakını | Acil durumda aranacak kişinin adı ve telefonu | `personnel_employee.emergency_contact_name`, `emergency_contact_phone` | Kaza ya da acil durumda yakına haber vermek | Meşru menfaat; acil durumda hayati menfaat (m.5/2-b) | Yalnızca admin ve yönetim | Çalışma süresince; çalışan ayrılınca amaç biter, kartta boşaltılması önerilir (**Personel > kart > Düzenle**) |
| Kaza / olay kayıtlarında yaralanan | Ad soyad, yaralanma bilgisi, olay anlatımı | `hse_incident.injured_person`, `injury`, `description`; olay fotoğrafları (ekler) | İş sağlığı ve güvenliği kaydı, SGK bildirimi | Kanuni yükümlülük (6331 İSG Kanunu); sağlık verisi için m.6 | Yalnızca yönetim; diğer roller yalnızca kendi bildirdikleri olayları görür | 6331 gereği en az 15 yıl (iş kazası kayıtları) — firma İSG uzmanıyla teyit edilmeli |
| Herkes | Ek dosyalar (fotoğraf, belge) | `core_attachment`, ekler klasörü | Kayıtlara kanıt | Kaydın amacına bağlı | Kaydı görebilen roller; dosyalar yalnızca giriş yapmış kullanıcıya verilir | Bağlı olduğu kayıtla aynı |
| Çalışan | Arayüz hata kayıtları (sayfa adresi, kullanıcı no) | sunucu günlüğü (`docker compose logs`), Sentry tanımlıysa Sentry | Hata giderme | Meşru menfaat | Admin, sunucuyu yöneten BT | Günlük dosyaları 5 × 10 MB döner (birkaç hafta); Sentry'de 30–90 gün (hesap ayarı). Sentry'ye çerez, IP, istek gövdesi gönderilmez |

## Teknik tedbirler (KVKK m.12)

- Erişim yetkisi rol bazlıdır ve her uç noktada kontrol edilir (CLAUDE.md kural 12). Maliyet ve olay
  kayıtları gibi hassas alanlar ayrıca daraltılmıştır.
- Personel kartları ve değişiklik geçmişleri yalnızca admin ve yönetime açıktır; kayıtlara bağlı genel
  geçmiş ve yorum uç noktaları personel kartını kabul etmez.
- Şifre politikası (en az 10 karakter, harf ve rakam), hatalı girişte hesap kilidi, hareketsizlik süresi,
  admin ve yönetim rollerinde iki aşamalı doğrulama (docs/DECISIONS.md, "Giriş güvenliği").
- Trafik HTTPS (TLS 1.2+), güvenlik başlıkları; sunucu yalnızca iç ağ ve VPN'den erişilebilir; yönetim paneli
  ve API dokümantasyonu yalnızca iç ağ/VPN IP'lerine açık.
- Denetim günlüğü değiştirilemez ve silinemez (tek istisna: süresi dolan IP adreslerinin boşaltılması).
- Yedekler şifreli bağlantıyla ayrı konuma kopyalanır; yedek diski/NAS'ı fiziksel olarak korunmalıdır
  (yedek tüm kişisel verileri içerir). Bulut depolama kullanılırsa Türkiye'de veri merkezi ya da yurt dışı
  aktarım için KVKK m.9 şartları değerlendirilmelidir.

## Silme / anonimleştirme talebi gelirse

Kişi (ör. ayrılan çalışan, şoför) verisinin silinmesini isterse: yasal saklama süresi dolmamış belgelerdeki
(irsaliye, denetim izi) veri **saklanmaya devam eder** (KVKK m.7 ve m.5/2-ç). Süresi dolmuş ya da yasal
dayanağı olmayan veriler (ör. pasif kullanıcının telefonu, e-postası) **Sistem > Kullanıcılar > Düzenle** ile,
ayrılmış personelin telefonu ve acil durum kişisi **Personel > kart > Düzenle** ile boşaltılır; işlem denetim
günlüğüne yazılır. Talep ve cevap 30 gün içinde (KVKK m.13) firma tarafından yazılı yürütülür.
