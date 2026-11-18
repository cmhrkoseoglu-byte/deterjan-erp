# Müşteri sipariş takibi (iç ekran ve müşteri portalı)

İstek (CUMHUR, 2026-11-19): "Müşterilerin siparişlerini takip edeceği ekranı tasarlayalım."
Plan onayı: CUMHUR, 2026-11-19 ("Onaylıyorum"; §3-4'teki ek kurallar "Hepsi uygun"; §5 CLAUDE.md
değişikliği "Evet, B1'de eklensin"). Uygulamaya geçmek ayrı onayla.

İki paket: **Paket A** çalışanlar için müşteri bazında sipariş takibi (dışarıya bir şey açılmaz).
**Paket B** müşterinin kendi hesabıyla girdiği portal (ayrı onayla, Paket A canlıya alındıktan
sonra). Her adımdan önce o adımın kısa planı yeniden onaya sunulur (CLAUDE.md §8 madde 2).

## 1. Sahibin kararları (2026-11-19)

| Konu | Karar |
|---|---|
| Kim kullanacak | **Önce iç ekran, sonra portal.** Paket A: sevkiyat ve yönetim müşteri bazında takip eder. Paket B (ayrı onayla): müşteri yetkilisi kendi hesabıyla girer. |
| Müşteri ne görür | Her durumda: sipariş durumu, sipariş / sevk edilen / kalan miktar, termin. Ek olarak **irsaliye PDF'i, fiyat ve tutar, cari bakiye ve ekstre**. **Lot no ve SKT gösterilmez.** |
| Giriş | **Ayrı müşteri hesabı + iki aşamalı doğrulama zorunlu.** Hesap tek bir müşteri kartına bağlıdır; yalnız portal sayfalarını açar. |
| İrsaliyede şoför TC | **Maskeli** (`*******8901`); ad soyad ve plaka görünür. Her açılış denetim günlüğüne yazılır. |
| Teslim tarihi | **Sözü verilen tarih alanı (Termin) eklenir.** Onayda zorunlu, onaydan sonra gerekçeyle değiştirilir. Gecikme ve müşterinin gördüğü tarih termindir; termin boşsa (eski siparişler) istenen teslim tarihi kullanılır. |
| Portal yetkisi | **Sipariş talebi girebilir.** Talep sipariş değildir; sevkiyat inceler, siparişe çevirir ya da gerekçeyle reddeder. |
| Talepte ürünler | **Tüm aktif mamuller** (malzeme türü Mamul, `is_active`). |
| Talepte fiyat | **Fiyatsız.** Müşteri ürün, miktar, birim, istenen tarih, kendi sipariş no'su ve not girer. Fiyat ve termini sevkiyat siparişe çevirirken girer. |
| Hesabı kim açar | **Yalnız admin** (Sistem > Kullanıcılar). Bir müşteriye birden çok kişi açılabilir. |
| Portal kullanıcısı ne görür | **Bağlı olduğu müşterinin tüm siparişlerini**, irsaliyelerini ve cari bakiyesini. |
| Bildirim | **İç: geciken teslim uyarısı** (sevkiyat ve yönetime, günlük). **Müşteriye e-posta: sipariş onaylandı ve sevk edildi.** |
| E-posta alıcısı | **Portal kullanıcıları** (e-postayı kapatmamış olanlar). Portal hesabı olmayan müşteriye e-posta gitmez. |

## 2. Bugünkü durum (2026-11-19, main = 47c4b15)

- `sales.SalesOrder` (`SS-`): müşteri, sipariş tarihi, istenen teslim tarihi (boş olabilir), teslim
  adresi, müşteri sipariş no, notlar; durum Taslak → Onaylandı → Kısmen sevk edildi → Sevk edildi →
  Kapandı / İptal. Satırda mamul, birim (ADET / KOLI / PALET), temel birim miktarı, isteğe bağlı fiyat
  ve para birimi (D-9).
- `sales.Shipment` (`SV-`): tek siparişe bağlı (D-10), Planlandı → Toplanıyor → Yüklendi → Sevk edildi;
  irsaliye PDF'i (`waybill.py`) şoför TC'sini tam basar, her açılış denetim günlüğüne yazılır.
- Sipariş satırının sevk edilen, planlanan ve kalan miktarı `services.shipped_quantity`,
  `planned_quantity`, `plannable_quantity` ve `selectors.lines_with_quantities` ile hesaplanıyor.
- Müşteri kartı (Sevkiyat > Müşteriler): sipariş geçmişi ve sevk edilen lotlar paneli var; termin,
  gecikme ve kalan miktar özeti yok.
- Cari hesaplar (`ledger`, PR #58): müşteri bakiyesi para birimi başına, yaşlandırma, ekstre Excel ve
  PDF'i. Tutarlar Fiyatları görür ister.
- Yetki: Satış siparişleri (Görür / Değiştirir / Onaylar), Sevkiyatlar ve irsaliye, Toplama ve
  yükleme, Müşteriye sevk edilen lotlar; Müşteri carileri. Siparişi gören fiyatını da görür (karar 6).
- Dışarıya açık hiçbir şey yok: her hesap çalışan hesabıdır; herkese açık okumalar (stok sorgu, lotlar,
  ana veri kartları, arama, bildirimler) giriş yapan **her** kullanıcıya açıktır. E-posta gönderimi
  (SMTP) kurulu değil.

## 3. Paket A — İç ekran: müşteri bazında sipariş takibi

### 3.1 Termin (`SalesOrder.promised_date`)

- Yeni alan "Termin" (`DateField`, boş olabilir). Taslakta serbestçe girilir; **onayda zorunlu**
  (`promised_date_required`). Onaylı, kısmen sevk edilmiş siparişte yalnız
  `sales.services.change_promised_date(actor, order, date, reason)` ile değişir: gerekçe zorunlu,
  denetim günlüğüne eski → yeni değerle yazılır, `sales_order.promised_date_changed` olayı yayınlanır.
  Sevk edildi, kapandı ve iptalde değişmez.
- Yetki: termin değiştirmek **Satış siparişleri: Değiştirir**.
- `selectors.due_date(order)`: termin, yoksa istenen teslim tarihi, yoksa boş. Göç mevcut siparişlere
  dokunmaz (eski onaylı siparişlerde termin boş kalır, istenen tarih kullanılır).

### 3.2 Okuma (selectors) ve API

- `selectors.order_tracking(customer=None, ...)`: açık siparişler (Onaylandı, Kısmen sevk edildi) ve
  isteğe göre son 90 günde kapananlar; satır başına sipariş / sevk edilen / sevke planlanan / kalan
  miktar (sipariş birimiyle ve temel birimde), vade (`due_date`), **gecikme günü** (vade geçmiş ve
  kalan > 0), son sevk tarihi, sevkiyatlar (no, durum, tarih).
- `selectors.customer_tracking_summary()`: müşteri başına açık sipariş sayısı, geciken sipariş sayısı,
  en eski gecikme, kalan satır sayısı, bu hafta vadesi gelen.
- API (`/api/v1/sales/tracking/`): `GET customers/` (müşteri özeti, sayfalı, süzgeç: arama, yalnız
  gecikenler), `GET orders/?customer=&late=&due_before=` (sipariş + satır özeti). Tutarlar sipariş
  fiyatından; fiyatı gören = siparişi gören (karar 6).
- Cari özeti (A2'de düzeltildi, CUMHUR onayı 2026-11-19): `sales` `ledger`'a bağımlı olamaz
  (CLAUDE.md bağımlılık yönü), bu yüzden takip API'si bakiye taşımaz. Ekran (A3) bakiyeyi mevcut
  Cari hesaplar API'sinden (`/api/v1/ledger/customers/`) yalnız **Müşteri carileri: Görür +
  Fiyatları görür** olana gösterir.
- Kapsam (CUMHUR, 2026-11-19): açık siparişler; "Biten siparişleri de göster" ile son 90 günde
  sevk edilen, kapanan ya da onaydan sonra iptal edilenler de (biten siparişte gecikme son sevk
  gününe göre).
- Yetki: **Satış siparişleri: Görür** (yeni bölüm yok). Yetkisiz rol 403.

### 3.3 Ekran

- Sevkiyat'a yeni sekme **"Sipariş takibi"**: müşteri listesi (açık / geciken sayısı, en eski gecikme,
  cari bakiye kolonları yetkiye göre), müşteri seçilince açık siparişler ve satırları; geciken satır
  kırmızı, "gecikme N gün" rozeti; süzgeç "Yalnız gecikenler", "Bu hafta vadesi gelenler".
- Müşteri kartına (Sevkiyat > Müşteriler > kart) aynı içerikte "Açık siparişler" paneli.
- Sipariş sayfasında Termin alanı, onay penceresinde zorunlu; "Termini değiştir" (gerekçeli) düğmesi.

### 3.4 Geciken teslim bildirimi

- Günlük kontrolde (`DAILY_CHECK`, 07:00) `sales_order.overdue` olayı: vadesi dün ya da daha önce dolmuş
  ve kalanı olan siparişlerin listesi (boşsa bildirim yok). Yeni geciken sipariş için ilk gün bildirim
  verilir; sonraki günlerde aynı sipariş tekrar bildirilmez, listede kalır (bildirim yorgunluğu
  olmasın). Termin ileri alınırsa sipariş listeden çıkar.
- `workflow` kuralı: **sevkiyat ve yönetim** rolündeki, Satış siparişleri: Görür'ü olan kişilere sistem
  içi bildirim, siparişlere bağlantılı.

### 3.5 Paket A adımları

1. **A1 Termin**: alan ve göç, onayda zorunluluk, `change_promised_date`, olay, denetim; servis,
   durum ve API testleri; sipariş formu ve onay penceresi.
2. **A2 Takip okuma ve API**: selectors, uç noktalar, cari özetin yetkiye göre gizlenmesi; servis,
   API ve 403 testleri.
3. **A3 Ekran**: "Sipariş takibi" sekmesi, müşteri kartı paneli; Vitest.
4. **A4 Geciken teslim bildirimi**: olay, workflow kuralı, tekrar bildirmeme; testler.
5. **A5 Belgeler**: DECISIONS, PROGRESS, yardım metni, yetki kataloğu (`kisi-yetkileri.md` §3.7 notu).

Her adımda: `pytest`, `ruff check`, `ruff format --check`, `mypy`, ön yüzde lint/typecheck/Vitest
yeşil; PROGRESS güncel; anlamlı commit.

## 4. Paket B — Müşteri portalı (ayrı onayla)

### 4.1 Yeni modül `portal`

Bağımlılık: `core ← masterdata ← sales, ledger ← portal`. `portal` satış ve cari modellerini okur;
siparişe çevirme `sales.services.create_order` ile yapılır. Kimse `portal`'a bağımlı olmaz; e-postalar
olayları dinleyerek gönderilir. **CLAUDE.md §3 tablosuna ve bağımlılık satırına eklenmesi onay ister
(§7).**

### 4.2 Portal hesabı

- `portal.PortalAccount(user (1-1), customer, email_notifications=True, is_active)`. Hesabı olan
  kullanıcı **portal kullanıcısıdır**: rol taşıyamaz (rol verilirse servis reddeder), kişiye özel yetki
  alamaz, yönetim paneline giremez, `is_staff` olamaz.
- **Varsayılan ret (en önemli kural):** portal kullanıcısı yalnız `/api/v1/auth/` (giriş, çıkış,
  şifre, iki aşamalı doğrulama) ve `/api/v1/portal/` uç noktalarını açabilir. Bunun dışındaki her
  istek — herkese açık okumalar (stok sorgu, lotlar, ana veri kartları, arama), bildirimler, görevler,
  WebSocket, ekler, yardım, sorun bildirimi dahil — 403 döner. Denetim merkezi bir ara katmanda yapılır
  (uç nokta tek tek işaretlenmez); bir sözleşme testi tüm URL'leri gezer ve izin listesi dışında
  kalanların portal kullanıcısına 403 döndüğünü doğrular. Tersine, çalışan hesapları portal uç
  noktalarını açamaz.
- **İki aşamalı doğrulama zorunlu** (`OTP_REQUIRED_ROLES`'tan bağımsız, her ortamda). Kurulum yapmadan
  yalnız Güvenlik sayfası açılır. Hareketsizlik süresi 30 dakika. Şifre politikası ve hesap kilidi
  çalışanlarla aynı.
- Hesabı yalnız admin açar ve kapatır: Sistem > Kullanıcılar'da "Portal kullanıcısı" türü, müşteri
  seçimi; listede ayrı süzgeç. Müşteri kartı pasife alınınca portal hesapları da kapanır.
- Bağlı müşteri değiştirilemez (yanlış bağlanan hesap kapatılıp yenisi açılır): böylece eski
  müşterinin verisi yeni müşteriye karışmaz.

### 4.3 Portalın gösterdikleri (`/api/v1/portal/`, hep bağlı müşteriyle süzülür)

- **Siparişlerim**: Onaylandı ve sonraki durumlar (taslak ve iptal edilmiş taslak görünmez; onaylıyken
  iptal edilen "İptal" görünür). Sipariş no, müşteri sipariş no, tarih, termin, durum, teslim adresi;
  satırlar: ürün kodu ve adı, sipariş / sevk edilen / kalan miktar (sipariş birimiyle), birim fiyat,
  para birimi, tutar. **Gösterilmez:** iç notlar, satır notu, rezervasyonlar, lotlar, SKT, oluşturan
  ve onaylayan kişiler, eksik (shortage) bilgisi.
- **Sevkiyatlar ve irsaliyeler**: yalnız Sevk edildi durumundakiler; no, sevk tarihi, plaka, taşıyıcı,
  satırlar ve miktarlar. **İrsaliye PDF'i** iç irsaliyeyle aynı içerik, şoför TC'si maskeli; lot
  sütunu basılmaz. `Cache-Control: no-store`; her açılış "İrsaliye görüntülendi (portal)" diye
  denetim günlüğüne ve sevkiyatın geçmişine yazılır.
- **Cari hesabım**: para birimi başına bakiye, vadesi geçen tutar, yaşlandırma; ekstre (tarih aralığı)
  ekranda ve PDF (`ledger` ekstre PDF'iyle aynı biçim). Tutarı eksik belgeler "fiyatı netleşmedi"
  diye bilgi satırıdır.
- **Taleplerim** (bkz. 4.4).

### 4.4 Sipariş talebi

- `portal.OrderRequest` (belge numarası kodlama sistematiğine göre; öneri `ST-` "Sipariş talebi",
  adım B3 öncesi kodlama listesine eklenir) ve satırları: aktif mamul, miktar (> 0), birim (malzemenin
  tanımlı birimleri: ADET / KOLI / PALET), istenen teslim tarihi, müşteri sipariş no, teslim adresi
  (varsayılan kart adresi), not.
- Durum makinesi (`state.py`): **Gönderildi → Siparişe çevrildi / Reddedildi**, Gönderildi →
  **Geri çekildi** (yalnız müşteri, yalnız Gönderildi'de). Her geçiş olay yayınlar ve denetlenir.
- İç taraf: Sevkiyat'a "Portal talepleri" sekmesi. **Siparişe çevir** (Satış siparişleri:
  Değiştirir): talepten taslak sipariş açılır (satırlar, istenen tarih, müşteri sipariş no, adres,
  not → sipariş notuna "Portal talebi ST-…" ile); fiyat ve termin taslakta girilir, onay bugünkü gibi
  (Onaylar). Talep ile sipariş birbirine bağlanır; müşteri talebinden siparişe gider. **Reddet**:
  gerekçe zorunlu, müşteri gerekçeyi portalda görür.
- `order_request.submitted` olayı → workflow: sevkiyat rolüne görev ("Portal talebi ST-… incele"),
  siparişe çevrilince ya da reddedilince kapanır.
- Portal stok, fiyat listesi ya da teslim tarihi vaadi göstermez.

### 4.5 E-posta

- Altyapı: SMTP ayarları `.env`'de (`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`,
  `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL`), gönderim Celery işi, yeniden deneme.
  `core.OutboundEmail` günlüğü: alıcı, konu, ilgili kayıt, durum, gönderim zamanı (içerik saklanmaz).
- Şablonlar (Türkçe, firma bilgili, düz metin + HTML):
  - **Sipariş onaylandı** (`sales_order.confirmed`): sipariş no, müşteri sipariş no, termin, satır
    sayısı ve portal bağlantısı. **Fiyat yazılmaz** (e-posta yönlendirilebilir; fiyat portalda).
  - **Sevk edildi** (`shipment.dispatched`): sevkiyat no, sipariş no, sevk tarihi, plaka, ürün ve
    miktarlar, portal bağlantısı. Şoför adı ve TC yazılmaz, irsaliye eklenmez (portaldan iner).
- Alıcı: müşterinin **etkin, e-postası dolu ve e-postayı kapatmamış** portal kullanıcıları. Portal
  kullanıcısı e-postayı Güvenlik sayfasından kapatıp açabilir. Gönderilemeyen e-posta işlemi
  bozmaz (olay commit sonrası), günlükte "başarısız" kalır, admin'e bildirim gider.

### 4.6 Ön yüz

- Ayrı düzen `/portal` (çalışan menüsü, bildirim zili ve arama yok); giriş sayfası ortak, girişten
  sonra hesap türüne göre yönlendirilir. Telefonda rahat kullanılır (PWA).
- Sayfalar: Siparişlerim (durum süzgeci, termin, kalan), Sipariş detayı, Sevkiyatlar (irsaliye
  indir), Cari hesabım (bakiye, ekstre, PDF), Yeni talep, Taleplerim, Güvenlik (şifre, iki aşamalı
  doğrulama, e-posta tercihi).

### 4.7 KVKK ve güvenlik

- KVKK envanterine yeni satırlar: **müşteri yetkilisi (portal kullanıcısı)** — ad soyad, e-posta,
  telefon, kullanıcı adı, şifre özeti ve 2FA anahtarı, giriş kayıtları ve IP (1 yıl), e-posta
  gönderim günlüğü; amaç sözleşmenin ifası, meşru menfaat. Şoför satırına "portal irsaliyesinde
  maskeli". Müşteri yetkilisine aydınlatma metni (firmanın hazırlayacağı) portal girişinde bağlantı.
- Portal internete açık ilk ekran olduğundan: giriş için IP başına sınır ve hesap kilidi; tüm portal
  uç noktalarında müşteri süzgeci tek yerde (`portal.selectors` her sorguyu `customer=account.customer`
  ile başlatır); başka müşterinin kayıt numarasıyla istek 404 döner (varlık sızdırılmaz); sızma testi
  sondaları (`access_contract`) portal kullanıcısıyla genişletilir.
- Bağlantı adresi: portal müşteriye `sslip.io` adresiyle verilmemeli; firmanın kendi alan adı altında
  bir adres (ör. `portal.<firma alan adı>`) ve sertifikası gerekir (adım B6 öncesi soru).

### 4.8 Paket B adımları

1. **B1 Portal hesabı ve varsayılan ret**: `portal` modülü, `PortalAccount`, ara katman, zorunlu 2FA,
   kullanıcı yönetiminde portal türü, sözleşme testi (her URL), WebSocket ve yönetim paneli reddi.
2. **B2 Portal okuma API'si**: siparişler, sevkiyatlar, maskeli irsaliye PDF'i, cari özet ve ekstre;
   müşteri süzgeci ve başka müşteri testleri.
3. **B3 Sipariş talebi**: model, durum makinesi, belge numarası, portal ve iç uç noktalar, siparişe
   çevirme, reddetme, workflow görevi; testler.
4. **B4 E-posta**: SMTP ayarı, Celery işi, `OutboundEmail`, iki şablon, alıcı kuralları, tercih;
   testler (e-posta arka ucu bellekte).
5. **B5 Portal ön yüzü**: `/portal` düzeni ve sayfaları, iç taraftaki "Portal talepleri" sekmesi,
   Sistem > Kullanıcılar'da portal türü; Vitest.
6. **B6 Güvenlik, belgeler ve canlı**: KVKK, DECISIONS, PROGRESS, CANLI-KONTROL (alan adı, SMTP,
   ilk portal hesabı), yardım metni, duman testi.

## 5. CLAUDE.md değişikliği (onay gerekir, §8 madde 6)

- §3 modül tablosuna: `portal` | Müşteri portalı: portal hesabı, müşterinin sipariş, irsaliye ve cari
  görünümü, sipariş talebi, müşteriye e-posta | canlı sonrası.
- §3 bağımlılık: "`portal` yalnızca `core`, `masterdata`, `sales` ve `ledger`'a bağlıdır; kimse
  `portal`'a bağımlı olmaz."
- §5 Roller'e: "Portal kullanıcısı (müşteri yetkilisi) rol taşımaz; yalnızca giriş ve portal uç
  noktalarını açar, başka her istek reddedilir."
- Paket A CLAUDE.md değişikliği gerektirmez; bu değişiklik B1 ile yapılır.

## 6. Sonra sorulacaklar (ilgili adımdan önce)

- **B4 öncesi:** e-posta hangi hesaptan gidecek (firmanın e-posta sağlayıcısı, gönderen adres ör.
  `siparis@…`) ve SMTP bilgileri (sunucuya `.env` ile girilir, depoya yazılmaz).
- **B6 öncesi:** portal adresi (firmanın alan adı), aydınlatma metni (firma hukuku hazırlar).
- **B6 öncesi:** ilk açılacak portal müşterileri ve kişileri (deneme müşterisi).

## 7. Kapsam dışı

Müşteriye özel fiyat listesi, portalda stok ya da teslim vaadi, portalda lot/SKT ve analiz
sertifikası, portalda iade talebi, online ödeme, fatura ve e-Fatura (muhasebe programında), SMS ve
WhatsApp bildirimi, müşteri kullanıcısının kendini kaydetmesi ya da şifresini e-postayla sıfırlaması
(şifreyi admin sıfırlar; e-postayla sıfırlama B4 sonrası ayrı onayla eklenebilir).
