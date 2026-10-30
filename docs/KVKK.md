# KVKK kişisel veri envanteri

Faz 5, Adım 5.5. 6698 sayılı Kişisel Verilerin Korunması Kanunu kapsamında bu sistemde tutulan kişisel
veriler, işleme amacı, hukuki dayanak, kimin gördüğü ve saklama süresi. Hukuki metinler (aydınlatma metni,
VERBİS kaydı) firmanın sorumluluğundadır; bu belge onlara girdi olacak teknik envanterdir. Bir alan
eklendiğinde ya da yetki değiştiğinde bu tablo da güncellenir.

**Veri sorumlusu:** firma (**Ana veriler > Firma bilgileri** ekranındaki ticari unvan). **Veri nerede:** fabrikadaki sunucuda PostgreSQL
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
| Şahıs firması | Vergi no yerine TCKN | `masterdata_customer.tax_number`, `masterdata_supplier.tax_number`; firmamız şahıs firmasıysa `masterdata_companyprofile.tax_number` | Fatura, irsaliye, satın alma siparişi | Kanuni yükümlülük | Kartı görebilen roller; firma bilgilerini Ana veriler'i açan roller (planlama, yönetim) ve belgeleri görenler | 10 yıl |
| Çalışan (personel kartı; sistemi kullanmayanlar dahil) | Sicil no, ad soyad, birim, görev, işe giriş ve çıkış tarihi, telefon; bağlıysa sistem kullanıcısı | `personnel_employee` | Personel listesi, iletişim, işe giriş ve ayrılışın kaydı | Sözleşmenin ifası (iş sözleşmesi), kanuni yükümlülük (İş Kanunu, SGK) | Yalnızca admin ve yönetim (Personel ekranı; kartın değişiklik geçmişi de yalnızca onlara açık) | Çalışma süresince; ayrılınca kart pasife alınır, silinmez. Ayrılıştan sonraki saklama süresi (genel zamanaşımı 10 yıl) firma İK ve hukuk birimiyle teyit edilmeli |
| Çalışan (personel kartı) | **TC kimlik no**, doğum tarihi, doğum yeri | `personnel_employee.national_id`, `birth_date`, `birth_place` | Özlük dosyası, SGK işe giriş ve çıkış bildirimleri | Kanuni yükümlülük (4857 İş Kanunu m.75 özlük dosyası, 5510 SGK) | Yalnızca admin ve yönetim. TC no kartta açık görünür (Karar 2026-10-29); denetim günlüğüne ve kart geçmişine maskeli yazılır (`*******0146`) | Kartla aynı; ayrılıştan sonraki süre İK ve hukukla teyit edilmeli |
| Çalışan (personel kartı) | En son mezuniyet: öğrenim durumu, okul, bölüm, mezuniyet yılı | `personnel_employee.education_level`, `school`, `field_of_study`, `graduation_year` | Özlük dosyası, görevin gerektirdiği öğrenimin kaydı | Sözleşmenin ifası, kanuni yükümlülük (özlük dosyası) | Yalnızca admin ve yönetim | Kartla aynı |
| Çalışan (özlük belgeleri) | Kimlik fotokopisi, bordro, iş sözleşmesi, diploma (taranmış PDF ya da fotoğraf) | `personnel_employeedocument`; dosyalar ekler klasöründe `personnel/` altında, rastgele adla | Özlük dosyası (İş Kanunu m.75), ücret hesap pusulası (m.37), iş sözleşmesinin saklanması | Kanuni yükümlülük, sözleşmenin ifası | Yalnızca admin ve yönetim, yalnızca Personel ekranından; genel ek uç noktaları personel kartını kabul etmez. Her açılış, ekleme ve kaldırma kartın geçmişine yazılır | Bordro ve sözleşme: ayrılıştan sonra yasal süre (genel zamanaşımı 10 yıl). Kimlik fotokopisi ve diploma: kartla aynı. Süreler İK ve hukukla teyit edilmeli. Kaldırılan belge açılamaz ama dosyası sunucuda ve yedeklerde kalır; imha prosedürü firma ile belirlenmeli |
| Çalışan (puantaj) | Günlük durum (çalıştı, izin, **rapor**, devamsız), fazla mesai saati, gün notu | `personnel_attendanceentry`, `personnel_attendancemonth` | Puantaj, ücret ve SGK bildirimi için gün ve fazla mesai kaydı | Kanuni yükümlülük (4857 İş Kanunu m.41 fazla çalışma, m.75 özlük; 5510 SGK); rapor sağlık verisi olduğu için KVKK m.6/3 (istihdam ve sosyal güvenlik alanındaki hukuki yükümlülük) | Yalnızca admin ve yönetim (Personel > Puantaj); Excel çıktısı bordroyu hazırlayana verilir | Çalışma süresince + ayrılıştan sonra yasal süre (genel zamanaşımı 10 yıl); İK ve hukukla teyit edilmeli. Onaylı ay kilitlidir; düzeltme gerekçeyle yeniden açılarak yapılır. Ayrılışta çıkıştan sonraki günler açık aydan kaldırılır; eski halleri ayın denetim kaydında, tarihli özeti (durum kodlarıyla) kartın geçmişinde kalır |
| Çalışan (ücret) | Brüt aylık ücret ve geçerlilik tarihi; bundan ve puantajdan hesaplanan aylık personel maliyeti (ücretli gün, fazla mesai ücreti, işveren payı) | `costing_employeewage`, `costing_departmentcostcenter`; aylık rapor saklanmaz, her açılışta hesaplanır (işçilik oranı eklenirse aşamanın toplam maliyeti ve kg'ı oranın notunda kalır; tek kişilik aşamada bu kişinin maliyetidir) | Personel maliyeti ve işçilik oranı (maliyet hesabı) | Sözleşmenin ifası (iş sözleşmesi), meşru menfaat (maliyet yönetimi) | Yalnızca admin ve yönetim (Maliyet > Personel maliyeti, Personel ücretleri); Excel çıktısı yönetim içinde kalmalı. Ücret ekleme ve kaldırma denetim günlüğüne yazılır | Çalışma süresince + ayrılıştan sonra yasal süre (genel zamanaşımı 10 yıl); İK ve hukukla teyit edilmeli. Kayıt silinmez, gerekçeyle kaldırılır |
| Çalışanın yakını | Acil durumda aranacak kişinin adı ve telefonu | `personnel_employee.emergency_contact_name`, `emergency_contact_phone` | Kaza ya da acil durumda yakına haber vermek | Meşru menfaat; acil durumda hayati menfaat (m.5/2-b) | Yalnızca admin ve yönetim | Çalışma süresince; çalışan ayrılınca amaç biter, kartta boşaltılması önerilir (**Personel > kart > Düzenle**) |
| Kaza / olay kayıtlarında yaralanan | Ad soyad, yaralanma bilgisi, olay anlatımı | `hse_incident.injured_person`, `injury`, `description`; olay fotoğrafları (ekler) | İş sağlığı ve güvenliği kaydı, SGK bildirimi | Kanuni yükümlülük (6331 İSG Kanunu); sağlık verisi için m.6 | Yalnızca yönetim; diğer roller yalnızca kendi bildirdikleri olayları görür | 6331 gereği en az 15 yıl (iş kazası kayıtları) — firma İSG uzmanıyla teyit edilmeli |
| Herkes | Ek dosyalar (fotoğraf, belge) | `core_attachment`, ekler klasörü | Kayıtlara kanıt | Kaydın amacına bağlı | Kaydı görebilen roller; dosyalar yalnızca giriş yapmış kullanıcıya verilir | Bağlı olduğu kayıtla aynı |
| Çalışan | Arayüz hata kayıtları (sayfa adresi, kullanıcı no) | sunucu günlüğü (`docker compose logs`), Sentry tanımlıysa Sentry | Hata giderme | Meşru menfaat | Admin, sunucuyu yöneten BT | Günlük dosyaları 5 × 10 MB döner (birkaç hafta); Sentry'de 30–90 gün (hesap ayarı). Sentry'ye çerez, IP, istek gövdesi gönderilmez |

## Teknik tedbirler (KVKK m.12)

- Erişim yetkisi rol bazlıdır ve her uç noktada kontrol edilir (CLAUDE.md kural 12). Maliyet ve olay
  kayıtları gibi hassas alanlar ayrıca daraltılmıştır.
- Personel kartları ve değişiklik geçmişleri yalnızca admin ve yönetime açıktır; kayıtlara bağlı genel
  geçmiş ve yorum uç noktaları personel kartını kabul etmez.
- Özlük belgeleri (kimlik fotokopisi, bordro, sözleşme, diploma) yalnızca personel uç noktalarından
  admin ve yönetime verilir; tarayıcı önbelleğine alınmaz (`Cache-Control: no-store`). Her açılış
  ("Belge açıldı"), ekleme ve kaldırma kartın geçmişine yazılır. Eski tip nüfus cüzdanındaki din hanesi
  özel nitelikli veridir (KVKK m.6); fotokopide kapatılması önerilir, firma İK'sı teyit etmeli.
- Puantaj yalnızca admin ve yönetime açıktır. Rapor günleri sağlık verisidir: gün kaydında hastalık ya
  da tanı yazılmaz (not alanı kısa açıklama içindir). Her gün değişikliği eski ve yeni değeriyle,
  onay ve yeniden açma gerekçesiyle denetim günlüğüne yazılır; Excel çıktısı yalnızca bordroyu
  hazırlayanla paylaşılmalıdır. Ayrılışta kaldırılan günler de eski halleriyle denetim günlüğünde,
  tarihli özetleri (rapor günü kodu R dahil) kartın geçmişinde kalır; ikisini de yalnızca admin ve
  yönetim görür.
- Ücretler ve personel maliyeti (Maliyet > Personel maliyeti, Personel ücretleri) yalnızca admin ve
  yönetime açıktır. Ücret kayıtları kayda bağlı genel geçmiş ve yorum uç noktalarında açılmaz; ekleme
  ve kaldırmayı gösteren denetim günlüğünü de yalnızca admin ve yönetim görür. Aylık rapor saklanmaz;
  Excel çıktısı yalnızca yönetim içinde paylaşılmalıdır.
- Kayda bağlı yorumlar, değişiklik geçmişi ve dosya ekleri kaydın kendi ekranındaki okuma kuralına uyar
  (`core.records`): kaydı göremeyen (ör. başkasının bildirdiği İSG olayı) yorumunu, geçmişini ve ekini de
  göremez; böyle bir kişiden yorumda bahsedilirse bildirim gitmez. Kaydı görüp tutarı göremeyen (lot
  maliyeti, satın alma tutarı) geçmişte de tutarı görmez. Kurala kayıtlı olmayan türler bu uç noktalarda
  hiç açılmaz.
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
günlüğüne yazılır. Saklama süresi dolan özlük belgesi kartta **Kaldır** ile kaldırılır; dosyanın sunucudan
ve yedeklerden imhası firmanın imha prosedürüne göre sistem yöneticisince yapılır. Talep ve cevap 30 gün içinde (KVKK m.13) firma tarafından yazılı yürütülür.
