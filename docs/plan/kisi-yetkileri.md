# Kişiye özel yetkiler

> **Durum:** CUMHUR onayladı (2026-11-11); adım adım uygulanıyor (§10, ilerleme `docs/PROGRESS.md`).
> Sahip kararları `docs/DECISIONS.md` "2026-11-10 — Kişiye özel yetkiler" kaydındadır.

## 1. Amaç ve sahip kararları

İstek (CUMHUR): "kullanıcılara yetkinlik atamak istiyorum. modülleri görüntüleye bilme ve
değiştirebileceği bir sistem geliştirelim".

Bugün yetki yalnızca roldür: kişi rolünün gördüğü her şeyi görür, rolünün yaptığı her şeyi yapar.
Bu çalışmayla admin, modüllerin bölümlerini kişi bazında açıp kapatabilir. Sahip kararları
(CUMHUR, 2026-11-10):

1. **Rol ve kişiye ekle/kaldır.** Roller varsayılan yetki paketidir. Admin bir kişiye paketinde
   olmayan bir yetkiyi ekleyebilir, paketinden gelen bir yetkiyi kaldırabilir. İlk gün herkesin
   erişimi bugünküyle aynıdır.
2. **Modül ve alt bölüm.** Yetki, modülün bölümü bazındadır (ör. Üretim: emirler, malzeme
   hazırlama, şarj ve tartım).
3. **Üç düzey: Görür, Değiştirir, Onaylar.** Onay ve karar adımları ayrı bir yetkidir.
4. **Hassas veri ayrı hak, sınırlı.** "Fiyatları görür" ve "Maliyetleri görür" ayrı haklardır.
   Personel ve bordro yalnız yönetim rolündekilere verilebilir (KVKK).
5. **Görevler.** Görev ve bildirimler role gitmeye devam eder. Rolde olup görevin gerektirdiği
   yetkisi kaldırılan kişi o görevi ve bildirimini almaz, göremez, üstlenemez. Rolde işi
   yapabilecek kimse kalmazsa yetki kaydedilirken uyarı çıkar.
6. **"Fiyatları görür" alış fiyatlarıdır:** mal kabul fiyat ve masrafları, satın alma tutarları ve
   sipariş PDF'i. Satış siparişindeki fiyatları bugünkü gibi siparişi gören herkes görür.
7. **Onaylar'ın kapsamı:** sahibin listesi (lot serbest bırakma ve ret, şartlı kabul, emir ve
   reçete onayı, D-13 limitiyle satın alma onayı, sevk onayı, puantaj ve bordro onayı), ayrıca
   satış siparişinde "Onayla ve rezerve et", sayım düzeltmede "Kaydet ve stoka al" ve onaylanmış
   bir belgeyi iptal etme ya da yeniden açma. Modül ayarları (onay limiti, bakım ve İSG ayarları)
   ve canlı başlangıç tarihi ayrı bir "Ayarlar" satırında Değiştirir'dir.
8. **Rol paketleri sürümle değişir.** Ekranda salt okunur görünür. Değişiklik testle ve DECISIONS
   kaydıyla yeni sürümde gelir.
9. **"Olaylar ve kazalar" ve "Denetim günlüğü" de yalnız yönetim rolündekilere verilebilir**
   (KVKK).
10. **Görev ayrılığı.** Şartlı kabulü öneren kişi onu onaylayamaz (admin dahil). Diğer riskli
    birleşimlerde yetki kaydedilirken uyarı çıkar, engellenmez.
11. **İki aşamalı doğrulama**, yetki ekranı canlıya alınmadan önce admin ve yönetim için yeniden
    zorunlu olur.
12. **Açık okumalar.** Bugün giriş yapan herkesin okuyabildiği kayıtlar ilk sürümde aynen kalır;
    bir kişi için kapatılabilir, lot sayfası ve seçim listeleri çalışmaya devam eder. Sonra ayrı
    bir adımda (Faz B, §10) yalnız Görür yetkisi olanlara kapatılır. Planın önerisi (onayınızı
    ister): stok, lotlar, palet listesi, tehlike bilgileri ve kişinin kendi bildirdiği olaylar
    kişiden hiç kapatılamaz; seçimler ve etiket basımı için gereken öteki okumalar (müşteri ve
    tedarikçinin vergi, adres ve iletişim bilgileri dışındaki ana veri kartları, birimler, yazıcılar,
    etiket ayarları, firma bilgileri) ve duruş kayıtları ilk sürümde kişiden kapatılamaz (§4).

## 2. Nasıl çalışır

- **Yetki = bölüm + düzey.** Bölüm bir ekran, sekme ya da işlem grubudur. Düzeyler:
  - **Görür:** bölümün ekranını (sekmesini) açar, kayıtlarını ve çıktılarını (Excel, PDF) görür.
  - **Değiştirir:** kayıt açar, düzenler, taslağı iptal eder, işi kaydeder (tartım, dolum, toplama).
  - **Onaylar:** onay ve karar adımları (karar 7).
- Değiştirir ve Onaylar, Görür düzeyi olan bölümlerde Görür'ü de verir. **Onaylar Değiştirir'i
  vermez, Değiştirir de Onaylar'ı vermez:** kaydeden ile onaylayan ayrılabilir (ISO 9001 md. 8.6,
  görev ayrılığı). Bugün bir rol ikisini de yapıyorsa (planlama emri yazar ve onaylar) paketi
  ikisini de verir.
- **Yalnız işlem bölümleri** (Görür'ü olmayanlar: arıza bildirimi, lot bloke etme, mal kabul fiyat
  ve masrafları, iade teslim alma ve imha, limit üstü sipariş onayı, tüm birimlerin iş emirlerini
  yürütme) menüde modül açmaz. Bir modül, Görür'ü olan bölümlerinden birinde Görür varsa menüde
  görünür. Hassas veriler, Görevler ve Sistem gruplarının menüde kendi modülü yoktur; bölümleri menü
  açmaz (Sistem menüsü bugünkü gibi yalnız admine açıktır).
- **Geçerli yetki** = herkese açık temel + kişinin rollerinin paketleri + kişiye eklenenler −
  kişiden kaldırılanlar. Ardından iki kısıt uygulanır:
  - **Yalnız yönetim (KVKK):** personel, bordro, personel maliyeti, olaylar ve kazalar ve denetim
    günlüğü yalnız yönetim rolündeki kişide geçerlidir. Rol alınınca bu yetkiler de düşer.
  - **Ön koşul:** bazı yetkiler başka bir yetki olmadan geçersizdir. Örnekler:
    - Maliyet bölümleri "Maliyetleri görür" ister; "Maliyetleri görür" de "Fiyatları görür" ister
      (hammadde lotunun maliyeti alış fiyatıdır).
    - Satın alma siparişinde Değiştirir ve Onaylar "Fiyatları görür" ister, Görür istemez (depo
      siparişi fiyatsız görür).
- **Admin** (sistem yöneticisi rolü ya da süper kullanıcı) her yetkiye sahiptir; ona kişiye özel
  yetki tanımlanmaz. Rolsüz kullanıcı yalnız temel yetkileri ve kişiye eklenenleri kullanır, görev
  almaz.
- **İlk gün** kişiye özel ayar yoktur ve herkesin erişimi bugünküyle birebir aynıdır. Bunu bugünkü
  koddan üretilen bir sözleşme testi her adımda kanıtlar (§5.5). Bilerek yapılan küçük düzeltmeler
  §8'de tek listededir.
- Yetki her istekte sunucuda denetlenir (CLAUDE.md kural 12); ekranın düğmeyi gizlemesi yetki
  sayılmaz. Değişiklik, kişinin açık oturumuna saniyeler içinde yansır.

## 3. Yetki kataloğu (rol varsayılanları = bugünkü erişim)

Hücrelerde o düzeyin varsayılan olarak verildiği roller yazılıdır.

- **Herkes:** rolü olmayan dahil her etkin kullanıcı.
- **Rolü olan herkes:** admin dışındaki 8 rolden en az birine sahip olan.
- **🔒:** kişiden kaldırılamaz.
- **Yalnız admin:** verilemez; yalnız sistem yöneticisi yapar.
- **—:** bölümde bu düzey yok.
- **Açık okuma:** bölümün kayıtları bugün giriş yapan herkese açıktır (lot sayfasından, bağlantıdan
  ya da @bahsetmeyle ulaşılır). İlk sürümde aynen kalır; modülün "Açık kayıtlar" satırından bir
  kişi için kapatılabilir (§5.3). Faz B'de Görür'e bağlanır.

Varsayılanlar bugünkü kod (262dede) okunarak çıkarıldı; her satırı ve planın koda dair iddiaları dört
bağımsız doğrulama turunda koda karşı denetlendi. 1. adımdaki sözleşme testi hepsini bugünkü
erişimle bir kez daha birebir karşılaştırır; fark çıkarsa tablo düzeltilir ve size bildirilir.

### 3.1 Ana veriler

| Bölüm | Kapsam | Görür | Değiştirir | Onaylar |
|---|---|---|---|---|
| Ana veri kartları | Malzeme, tedarikçi, müşteri, depo, lokasyon, ekipman, kategori, birim dönüşümü; Excel'den içe aktarma, GTIN önerisi, pasife alma. Müşteri ve tedarikçinin vergi, adres ve iletişim bilgileri açık okuma | planlama, yönetim | planlama | — |
| Birimler, yazıcılar ve etiket ayarları | Salt okunur sekmeler | planlama, yönetim | yalnız admin | — |
| Firma bilgileri | Ticari unvan, adres, vergi ve sicil bilgileri | planlama, yönetim | yönetim | — |

- Kartlar (müşteri ve tedarikçinin vergi, adres ve iletişim bilgileri hariç; aşağıda), birim ve
  yazıcı listeleri ve etiket ayarları seçimler ve etiket basımı için herkese açık okunur (bugünkü
  gibi); bu okumalar kişiden kapatılamaz.
- Müşteri ve tedarikçi kartlarındaki vergi dairesi ve numarası, adres, telefon, e-posta ve yetkili
  kişi açık okumadır. Bu alanları her durumda tam görenler: tedarikçide Ana veri kartları: Görür'ü
  olan; müşteride Ana veri kartları ya da Satış siparişleri: Görür'ü olan (Sevkiyat'ın Müşteriler
  sekmesi ve müşteri kartı siparişleri gören kişide tam kalır). Ana veriler'in "Açık kayıtlar"
  satırı bir kişi için kapatılınca, bu Görür'lerden birine sahip değilse kişiye bu alanlar boş
  döner (sade kart, §5.6); seçimler çalışmaya devam eder. İrsaliye ve sipariş belgeleri kendi
  bölümlerinin yetkisini izler. Faz B'de sade kart, bu bölümlerde Görür'ü olmayan herkese
  uygulanır.
- Firma bilgileri irsaliyeye ve sipariş PDF'ine basıldığı için herkes okuyabilir; kişiden
  kapatılamaz.
- Lokasyon etiketi basma ve yazıcı deneme baskısı herkese açık kalır. Kaydın kodunu sonradan
  değiştirmek yalnız adminin işidir (kodlama sistematiği).

### 3.2 Reçeteler

| Bölüm | Kapsam | Görür | Değiştirir | Onaylar |
|---|---|---|---|---|
| Reçeteler ve sürümler | Reçete kartı, sürümler, satırlar, adımlar, ölçekleme, Excel'den taslak, pasife alma. Onaylar: sürüm onayı. Açık okuma | planlama, laboratuvar | planlama, laboratuvar | planlama, laboratuvar |

### 3.3 Depo ve stok

| Bölüm | Kapsam | Görür | Değiştirir | Onaylar |
|---|---|---|---|---|
| Stok sorgu, hareketler ve transfer | Stok ve hareket listeleri. Değiştirir: transfer, ters kayıt, açılış stoku içe aktarma | herkes 🔒 | depo | — |
| Lotlar | Lot sayfası, soy ağacı, lot etiketi, analiz sertifikası PDF'i (düğmesi numune sayfasında) | herkes 🔒 | — | — |
| Palet etiketleri (SSCC) | Palet listesi. Değiştirir: palet oluşturma | herkes 🔒 | depo, dolum, sevkiyat, üretim | — |
| Mal kabul | Mal kabul belgeleri (fiyatsız). Değiştirir: hazırlar, taslağı düzenler, kaydeder ve stoka alır, taslağı iptal eder. Lot etiketlerini indirme ve yazdırma herkese açıktır (Açık kayıtlar kapatılınca da). Açık okuma (belge sayfası dahil) | depo, planlama, yönetim, satın alma, laboratuvar | depo | — |
| Mal kabul fiyat ve masrafları | Birim fiyat, para birimi, kur ve ek masraf girme ve düzeltme. Ön koşul: Mal kabul: Görür ve Fiyatları görür | — | satın alma, yönetim | — |
| Sayım düzeltme | Değiştirir: hazırlar, taslağı düzenler, taslağı iptal eder. Onaylar: kaydeder ve stoka alır (D-3). Açık okuma (belge sayfası dahil) | depo, yönetim | depo | depo |
| Lot bloke etme | Lotu gerekçeyle bloke eder | — | — | laboratuvar |
| Elle serbest bırakma (D-5) | | — | — | yalnız admin |

Lotu serbest bırakma ve reddetme yalnız kalite kararıyla olur (§3.5).

### 3.4 Üretim

| Bölüm | Kapsam | Görür | Değiştirir | Onaylar |
|---|---|---|---|---|
| Üretim emirleri | Emir listesi ve sayfası. Değiştirir: açar, taslağı düzenler, taslağı iptal eder, yeniden işleme emri açar, emri elle tamamlar (yalnız API). Onaylar: onaylar, onaylı emri iptal eder. Açık okuma | üretim, planlama, depo, yönetim | planlama | planlama |
| Malzeme hazırlama | Hazırlama sekmesi. Değiştirir: hazırlığı başlatır, malzeme okutur, hazır bildirir. Açık okuma | depo | depo | — |
| Şarj ve tartım | Şarj başlatma, tartım, bitirme, tartım yapılmamış şarjı iptal etme. Açık okuma | üretim, planlama, depo, yönetim | üretim | — |

Hazırlama sayfası bugünkü gibi Üretim'in herhangi bir bölümünde Görür ile salt okunur açılır;
okutma ve "hazır" düğmeleri Malzeme hazırlama: Değiştirir ister.

### 3.5 Kalite kontrol

| Bölüm | Kapsam | Görür | Değiştirir | Onaylar |
|---|---|---|---|---|
| Numuneler ve kalite kararı | Numuneler, sonuçlar, kararlar. Değiştirir: numune açar, numune alma bilgilerini düzenler, spesifikasyon atar, sonuç girer ve düzeltir, numuneyi iptal eder (Numune kuyruğu sekmesi). Onaylar: karar verir (serbest bırak, reddet, yeniden işle, şartlı kabul öner). Açık okuma (kuyruk ve karar listesi dahil) | laboratuvar, yönetim | laboratuvar | laboratuvar |
| Şartlı kabul onayı | Önerilen şartlı kabulü onaylar ya da reddeder; öneren kişi onaylayamaz | yönetim | — | yönetim |
| Spesifikasyonlar ve test tanımları | Spesifikasyon sürümleri ve test tanımları. Onaylar: sürüm onayı. Açık okuma | laboratuvar, yönetim | laboratuvar | laboratuvar |

### 3.6 Dolum

| Bölüm | Kapsam | Görür | Değiştirir | Onaylar |
|---|---|---|---|---|
| Dolum emirleri | Değiştirir: açar, taslağı düzenler, taslağı iptal eder. Onaylar: onaylar, onaylı emri iptal eder. Açık okuma | dolum, planlama, depo, yönetim | planlama | planlama |
| Ambalaj hazırlama | Hazırlama sekmesi. Değiştirir: hazırlığı başlatır, ambalaj okutur, hazır bildirir. Açık okuma | depo | depo | — |
| Dolum hattı | Değiştirir: parti başlatır, bulk tüketimini ve ambalaj okutmayı kaydeder, fire girer, partiyi bitirir, kaydı olmayan partiyi iptal eder, dolumu bitirir. Parti ve emir tüketim raporları açık okumadır; koli etiketi basma herkese açıktır (Lotlar). Açık okuma | dolum, planlama, depo, yönetim | dolum | — |
| Ambalaj reçeteleri | Sürümler ve satırlar. Onaylar: sürüm onayı. Açık okuma | dolum, planlama, depo, yönetim | planlama | planlama |
| Dolum emrini geri alma | 2026-11-14'te eklendi (DECISIONS "Dolum emrini geri alma"). Değiştirir: fiilen yapılmamış dolumu geri alır; emrin stok hareketleri ters kayıtla geri alınır, partiler ve açık numuneler iptal edilir, emir iptal olur. Dolum emirleri: Görür'ü ister | — | yönetim | — |

Ambalaj hazırlama sayfası bugünkü gibi Dolum'un herhangi bir bölümünde Görür ile salt okunur açılır.

### 3.7 Sevkiyat

| Bölüm | Kapsam | Görür | Değiştirir | Onaylar |
|---|---|---|---|---|
| Satış siparişleri | Siparişler ve fiyatları, Müşteriler sekmesi ve müşteri kartı (iletişim bilgileri dahil, §3.1). Değiştirir: taslak, rezervasyon, siparişi kapatma, taslağı iptal. Onaylar: onaylar ve rezerve eder, onaylı siparişi iptal eder | sevkiyat, yönetim, planlama, depo | sevkiyat, yönetim | sevkiyat, yönetim |
| Sevkiyatlar ve irsaliye | Sevkiyatlar, irsaliye PDF'i. Değiştirir: planlar, araç ve şoför, sevk öncesi iptal. Onaylar: sevki onaylar | sevkiyat, yönetim, planlama, depo | sevkiyat | sevkiyat |
| Toplama ve yükleme | Toplama sekmesi. Değiştirir: lot okutma, okutmayı geri alma, yükleme tamam | depo | depo | — |
| Müşteriye sevk edilen lotlar | Müşteri kartındaki panel | sevkiyat, yönetim | — | — |

Toplama sayfası ve toplama önerisi bugünkü gibi Sevkiyatlar ve irsaliye: Görür ile de salt okunur
açılır.

### 3.8 İadeler

| Bölüm | Kapsam | Görür | Değiştirir | Onaylar |
|---|---|---|---|---|
| İade kayıtları | İade listesi ve sayfası. Değiştirir: açar, taslağı düzenler, taslağı iptal eder. Açık okuma | sevkiyat, laboratuvar, depo, yönetim | sevkiyat | — |
| İade teslim alma ve imha | Teslim al, imha et. Ön koşul: İade kayıtları: Görür | — | sevkiyat, depo | — |

İade edilen malın akıbeti, iade numunesindeki kalite kararıdır (§3.5).

### 3.9 İzlenebilirlik

| Bölüm | Kapsam | Görür | Değiştirir | Onaylar |
|---|---|---|---|---|
| Geri ve ileri izleme, geri çağırma | Raporlar, Excel ve PDF | laboratuvar, yönetim | — | — |

### 3.10 Satın alma

| Bölüm | Kapsam | Görür | Değiştirir | Onaylar |
|---|---|---|---|---|
| Satın alma talepleri | Talepler sekmesi; kişi kendi talebini düzenler ve iptal eder | planlama, depo, üretim, satın alma, yönetim | planlama, depo, üretim, satın alma, yönetim | — |
| Talep önerileri | Öneriler sekmesi | satın alma, yönetim, planlama | — | — |
| Satın alma siparişleri | Siparişler (fiyatlar yalnız Fiyatları görür ile). Değiştirir: sipariş yazma, yönetim onayına ve tedarikçiye gönderme, kalanı kapatma, taslağı ya da onay bekleyeni iptal, başkasının talebini düzenleme ve iptal etme. Onaylar: D-13 limiti içinde onay, onaylı siparişi iptal. Değiştirir ve Onaylar için ön koşul: Fiyatları görür | satın alma, yönetim, depo | satın alma, yönetim | satın alma, yönetim |
| Limit üstü sipariş onayı | Limit üstü ya da limit girilmemişken onay; taslağa geri gönderme. Ön koşul: Satın alma siparişleri: Görür ve Fiyatları görür | — | — | yönetim |
| Beklenen teslimatlar ve siparişten mal kabul | Açık sipariş satırları (fiyatsız) ve mal kabullerin sipariş bağlantıları; siparişten mal kabul taslağı. Değiştirir için ön koşul: Satın alma siparişleri: Görür | satın alma, yönetim, depo | depo, satın alma, yönetim | — |
| Tedarikçi performansı | | satın alma, yönetim | — | — |
| Satın alma ayarları | Onay limiti ve fazla teslim toleransı | yönetim | yönetim | — |

Satın alma ayarlarının değerlerini sipariş yazan kişi de okuyabilir (bugünkü gibi; sekmeyi görmez).

### 3.11 Maliyet

| Bölüm | Kapsam | Görür | Değiştirir | Onaylar |
|---|---|---|---|---|
| Lot maliyetleri ve maliyet raporları | Lot maliyeti, maliyet raporları, hesaplama. Ön koşul: Maliyetleri görür | yönetim | yönetim | — |
| Gider oranları ve standart maliyetler | Değiştirir: oran ekler ve düzeltir; standart maliyet ekler, düzeltir, pasife alır. Ön koşul: Maliyetleri görür | yönetim | yönetim | — |
| Personel maliyeti | Sekme ve Excel'i (açılışı bordro erişim günlüğüne yazılır). Değiştirir: birimlerin maliyet aşaması; onaylı aydan işçilik oranı ekleme (ayrıca Gider oranları: Değiştirir ister). Ön koşul: Maliyetleri görür, Ücretler: Görür ve Bordro: Görür. Yalnız yönetim rolündekilere (KVKK) | yönetim | yönetim | — |

### 3.12 Bakım

| Bölüm | Kapsam | Görür | Değiştirir | Onaylar |
|---|---|---|---|---|
| Bakım iş emirleri | Kişinin kendi biriminin (sorumlu rol) iş emirleri: işe başla, parça ekle, tamamla, iptal | üretim, dolum, laboratuvar, planlama, yönetim | üretim, dolum, laboratuvar, planlama, yönetim | — |
| Tüm birimlerin iş emirlerini yürütme | Sorumlu birim kuralının istisnası. Ön koşul: Bakım iş emirleri: Değiştirir (işe başla, parça, tamamla ve iptal uç noktaları bugün bunu ister) | — | yönetim | — |
| Bakım planları ve iş emri açma | Planlar, elle iş emri açma | üretim, dolum, laboratuvar, planlama, yönetim | üretim, dolum, laboratuvar, yönetim | — |
| Arıza bildirimi | | — | rolü olan herkes 🔒 | — |
| Duruşlar | Duruş başlatma ve bitirme | üretim, dolum, laboratuvar, planlama, yönetim | üretim, dolum, laboratuvar, planlama, yönetim | — |
| Tank temizliği | Temizlik kaydı; tamamlanmış temizlik iş emri açar | üretim, dolum, laboratuvar, planlama, yönetim | üretim, yönetim | — |
| Kalibrasyon | Terazi kalibrasyon durumu | üretim, dolum, laboratuvar, planlama, yönetim | — | — |
| Temizliksiz geçişler (D-14) | | üretim, dolum, laboratuvar, planlama, yönetim | laboratuvar | — |
| Bakım ayarları | Kalibrasyon uyarı süresi, iş emri açma süresi | yönetim | yönetim | — |

- İş emri görevi bugünkü gibi sorumlu role gider.
- Tartım ve şarj başlatma, kalibrasyon ve tank temizliği durumunu Bakım yetkisi olmadan da okur.
- Duruş kayıtlarını rolü olan herkes okuyabilir (bugünkü gibi; rolsüz kullanıcı okuyamaz); bu
  okuma kişiden kapatılamaz.
- Bakım ayarlarının değerlerini Bakım'ı gören herkes okuyabilir.

### 3.13 İSG ve çevre

| Bölüm | Kapsam | Görür | Değiştirir | Onaylar |
|---|---|---|---|---|
| Olay bildirimi | Olay bildirme; kişinin kendi bildirdiği olayları görme, yorum ve fotoğraf ekleme | rolü olan herkes 🔒 | rolü olan herkes 🔒 | — |
| Olaylar ve kazalar | Bütün olaylar (yaralanan kişi ve yaralanma bilgisi); incele, kapat, iptal et. Yalnız yönetim rolündekilere (KVKK) | yönetim | yönetim | — |
| GBF arşivi | GBF'ler, eksik ve süresi geçmiş GBF raporu. Değiştirir: yeni GBF, PDF yükleme | yönetim, depo, laboratuvar | yönetim | — |
| Tehlike bilgileri ve H/P ifadeleri | Malzemenin tehlike bilgisi | rolü olan herkes 🔒 | yönetim, laboratuvar | — |
| Depolama limitleri | | yönetim, depo | yönetim | — |
| Atık | | yönetim | yönetim | — |
| İSG özeti | Sayılar (isim yok) | yönetim | — | — |
| İSG ayarları | GBF en çok yaşı | yönetim | yönetim | — |

İSG ayarlarının değerlerini GBF arşivini gören herkes okuyabilir (bugünkü gibi). İSG'nin Olaylar
sekmesi Olay bildirimi ya da Olaylar ve kazalar: Görür ile görünür (bugünkü gibi); Olaylar ve
kazalar: Görür'ü olan bütün olayları, öteki kişi kendi bildirdiklerini görür.

### 3.14 Personel (yalnız yönetim rolündekilere verilebilir; KVKK)

| Bölüm | Kapsam | Görür | Değiştirir | Onaylar |
|---|---|---|---|---|
| Personel kartları ve özlük belgeleri | | yönetim | yönetim | — |
| Puantaj ve tatil takvimi | Değiştirir: gün ve aralık girişi, tatiller. Onaylar: ay onayı ve yeniden açma | yönetim | yönetim | yönetim |
| Ücretler | | yönetim | yönetim | — |
| Bordro | Ön bordro, pusulalar, PDF ve Excel. Değiştirir: kalemler, devirler, dış bordro tutarları, yeniden açılan ayda karta geçirme. Onaylar: onay, yeniden açma, onaylı bordronun ödeme tarihini düzeltme. Ön koşul: Ücretler: Görür (bordro brüt ücreti gösterir) | yönetim | yönetim | yönetim |
| Personel ayarları | Bordro parametreleri (asgari ücret, SGK oranları, vergi dilimleri), hafta tatili günleri | yönetim | yönetim | — |

### 3.15 Panolar ve raporlar (yalnız Görür)

| Bölüm | Görür |
|---|---|
| Yönetim panosu ve görev süreleri raporu | yönetim, planlama |
| Depo panosu | depo, planlama, yönetim |
| Stok raporları (stok durumu, stok hareketleri) | depo, planlama, yönetim, satın alma |
| Üretim panosu ve üretim raporu | üretim, planlama, yönetim |
| Dolum raporu | dolum, planlama, yönetim |
| Laboratuvar panosu ve kalite raporu | laboratuvar, planlama, yönetim |
| Sevkiyat panosu | sevkiyat, depo, planlama, yönetim |
| Sevkiyat raporu | sevkiyat, planlama, yönetim |

- Pano ve rapor yetkileri ayrıdır: bir modülün bölümünü kaldırmak o modülün panodaki özetini
  kaldırmaz.
- Panodaki stok değeri ve raporların maliyet sütunları ve TL özetleri Maliyetleri görür'e, onay
  bekleyen satın alma siparişlerinin TL toplamı Fiyatları görür'e bağlıdır.
- "Yönetim panosu" menü öğesi, `/pano` sayfası ve yönetimin açılış sayfası bugünkü gibi yönetim
  rolünü ister; ayrıca bu bölümün Görür'ünü ister. Biri yoksa açılış sayfası Görevlerim olur.
  Planlama panoyu bugünkü gibi Panolar ve raporlar'da açar.
- İndirmeler sekmesi ve adresi (`/raporlar/indirmeler`, kişinin kendi rapor dosyaları) herkese
  açıktır (§4); rapor hazır bildirimi oraya götürür. Dosya indirilirken raporun Görür'ü ve
  dosyadaki maliyet ya da fiyat sütunlarının hakkı yeniden denetlenir (§5.6).

### 3.16 Canlıya geçiş

| Bölüm | Kapsam | Görür | Değiştirir | Onaylar |
|---|---|---|---|---|
| Hazırlık listesi | Hazırlık kontrol listesi | yönetim, planlama, depo | — | — |
| Canlıya geçiş ayarları | Canlı başlangıç tarihi; Değiştirir: tarihi kaydeder ya da kaldırır (o günden açılış stoku yüklenemez) | yönetim, planlama, depo | yönetim | — |
| Stok karşılaştırma | Değiştirir: yeni karşılaştırma (Excel) | yönetim, planlama, depo | depo, yönetim | — |
| Sorun bildirimleri listesi | | yalnız admin | — | — |

### 3.17 Görevler ve sistem

| Bölüm | Kapsam | Görür | Değiştirir | Onaylar |
|---|---|---|---|---|
| Tüm birimlerin görevleri | Başka rollerin görevlerini de görür (§5.7) | yönetim | — | — |
| Denetim günlüğü | API'deki denetim günlüğü. Yalnız yönetim rolündekilere (KVKK) | yönetim | — | — |

### 3.18 Hassas veriler

| Hak | Kapsam | Varsayılan |
|---|---|---|
| Fiyatları görür | Mal kabul fiyat ve masrafları; satın alma birim fiyatları, tutarları ve sipariş PDF'i; panodaki onay bekleyen sipariş toplamı; kayıt geçmişindeki ve denetim günlüğündeki bu tutarlar (silinen satır ve ek masraf kayıtlarının içi dahil); raporların fiyat sütunları (bugün yok) | satın alma, yönetim |
| Maliyetleri görür | Lot maliyeti; stok değeri (lot sayfası, stok raporu, pano); raporların maliyet sütunları ve TL özetleri; Maliyet modülünün ön koşulu. Ön koşulu: Fiyatları görür | yönetim |

Satış fiyatları bu haklara bağlı değildir (karar 6).

## 4. Herkese açık olanlar, yalnız admin olanlar, satır kuralları

- **Herkese açık, yetki tablosunda yok:**
  - Görevlerim, Bildirimler, Arama (kaynaklar yetkiye göre süzülür), Güvenlik (şifre, iki
    aşamalı doğrulama), Yardım, Yetkilerim;
  - Sorun bildir ve kişinin kendi bildirdikleri;
  - İndirmeler (kişinin kendi rapor dosyaları);
  - ortak listeler (ülke ve dil kodları), arayüz hata kaydı;
  - @bahsetme önerisi: kayıt verilirse yalnız kaydı görebilenler, kayıt verilmezse bugünkü gibi
    etkin kullanıcılar.
- **Kilitli (🔒) açık bölümler:**
  - stok sorgu ve lotlar, palet listesi (herkes): lot ve stok her ekranda seçim için gerekir;
  - tehlike bilgileri, arıza bildirimi ve olay bildirimi (rolü olan herkes): kaza ve arıza
    bildirmek rolü olan herkesin hakkıdır.
- **Kişiden kapatılamayan okumalar** (ilk sürümde): ana veri kartları (müşteri ve tedarikçinin
  vergi, adres ve iletişim bilgileri hariç), birimler, yazıcılar, etiket ayarları ve firma
  bilgileri (herkes); duruş kayıtları (rolü olan herkes). Seçimler ve etiket basımı bunlara
  bağlıdır; kişisel veri içermezler.
- **Baskı ve dışa aktarım:** bölümün okumasına bağlıdır. Açık okumalı bölümlerin çıktıları açık
  okumayı izler. Lot, mal kabul ve lokasyon etiketi basma ile yazıcı denemesi herkese açıktır.
  Fiyatlı belgeler Fiyatları görür'ü de ister.
- **Yalnız admin:**
  - Kullanıcılar ve yetkiler;
  - Kodlama sistematiği (GS1, çıktı doküman kodları, kod değişikliği);
  - Sistem durumu, Saha tableti, Sorun bildirimleri listesi;
  - elle serbest bırakma (D-5);
  - birim, yazıcı ve etiket ayarlarını değiştirme;
  - kaldırılmış eki açma ve indirme;
  - Django yönetim paneli.
- **Satır kuralları sürer:**
  - kişi kendi satın alma talebini düzenler;
  - yorumu yalnız yazanı düzenler; yoruma eki yalnız yorumu yazan ekler;
  - eki yükleyen ya da admin kaldırır;
  - olayı bildiren kendi olayını, sorunu bildiren kendi bildirimini görür;
  - rapor dosyasını yalnız isteyen görür ve indirir (admin dahil);
  - bakım iş emrini sorumlu birim yürütür.

## 5. Teknik tasarım

### 5.1 Katalog kodda

- Her modülde `apps/<modül>/access.py` (yalnız veri) bulunur. Dosya şunları tanımlar:
  - bölümler: anahtar (`modül.bölüm`), Türkçe ad, düzeyler ve açıklamaları, okuma kapsamı, düzey
    bazında ön koşullar, KVKK kısıtı, kilit, yalnız admin düzeyleri;
  - rol paketleri;
  - kayıt türü → okuma bölümleri (API'deki `ReadRule` ile aynı liste; tablo aşağıda) ve denetim
    günlüğü için model → bölüm ve gizli alan eşlemesi;
  - açık kayıtlar kapatılınca etkilenen öteki ekranlar (modülün herkese açık ekranları dahil;
    kaydetme özetindeki uyarı için);
  - başka modülün kartında açtığı alanlar (ör. sales: Satış siparişleri: Görür müşteri kartının tam
    alanlarını açar; §5.6).
- `apps/core/access.py` kayıt defterini tutar ve hiçbir modülü import etmez. `CoreConfig.ready()`
  her uygulamanın `access` modülünü kendiliğinden yükler (web, Celery, yönetim komutları).
- Hassas haklar (`sensitive.*`) ve sistem bölümleri core'dadır; "Tüm birimlerin görevleri"
  workflow'dadır. Bir modül yalnız bağımlı olduğu modüllerin bölümlerine bakar (CLAUDE.md §3).
  Örnek: lot bloke etme `inventory`'dedir; core personel ya da maliyet bölümlerini bilmez, onları
  kayıt defterinden okur.
- Görev ve bildirim kurallarının gerektirdiği bölüm ve düzey `workflow/rules.py`'de kuralın bir
  alanıdır (`requires=`). workflow her modülü dinlediği için (CLAUDE.md §3) her modülün bölümüne
  bakabilir ve bağımlılık denetiminden muaftır. Diğer modüllerin `access.py`'si görev bilmez.
  workflow, `ready()`'de her kuralın rolünü ve gerektirdiği yetkiyi core'un kayıt defterine yazar.
  `set_user_access` uyarıları, canlıya geçiş hazırlık maddesi ve sistem durumu "kimse kalmıyor"
  denetimini bu kayıttan yapar; core, golive ve sistem durumu workflow'u import etmez.
- **Kayıt türlerinin okuma bölümleri.** Kayıt paneli ve @bahsetme bu listeyi kullanır; API'deki
  okuma kuralı aynıdır. Denetim günlüğü süzmesi bu listeyi değil §5.6'daki model eşlemesini
  kullanır.

  | Kayıt türü | Okuma bölümleri |
  |---|---|
  | Lot | Lotlar (herkes); maliyet alanları Maliyetleri görür ile |
  | Mal kabul | Mal kabul; fiyat alanları ve fiyat düzeltmesi notları Fiyatları görür ile |
  | Sayım düzeltme | Sayım düzeltme |
  | Üretim emri, şarj | Üretim emirleri, Malzeme hazırlama, Şarj ve tartım |
  | Dolum emri, dolum partisi | Dolum emirleri, Ambalaj hazırlama, Dolum hattı |
  | Ambalaj reçetesi | Ambalaj reçeteleri |
  | Numune | Numuneler ve kalite kararı, Şartlı kabul onayı |
  | Müşteri iadesi | İade kayıtları |
  | Satış siparişi | Satış siparişleri |
  | Sevkiyat | Sevkiyatlar ve irsaliye, Toplama ve yükleme |
  | Satın alma siparişi | Satın alma siparişleri; fiyat alanları Fiyatları görür ile |
  | Bakım iş emri | Bakım iş emirleri |
  | GBF | GBF arşivi |
  | Atık kaydı | Atık |
  | Olay | Olaylar ve kazalar (hepsi); Olay bildirimi (kişinin kendi bildirdikleri) |
  | Sorun bildirimi | Satır kuralı: bildiren ve admin |
  | Yorum | Yorumun bağlı olduğu kaydın kuralı |
- Riskli birleşimler (görev ayrılığı, §5.11) katalogda tek yerde tanımlıdır.
- **Tek kaynak:**
  - Ekran: `GET /api/v1/access/catalog/`.
  - Ön yüz: `python manage.py export_access --format=ts` komutu `frontend/src/auth/access.gen.ts`
    dosyasını yazar. CI'da `--check` adımı dosyanın güncel olduğunu denetler.
  - Belgeler: `--format=markdown` komutu belgelerdeki tabloları üretir.
- **Sistem denetimi** (`manage.py check` ve CI) şunları yakalar:
  - bilinmeyen anahtar, döngülü ön koşul, olmayan KVKK rolü;
  - geçersiz iş akışı kuralı;
  - yetki sınıfı ya da açık işaret (`SignedIn("neden")`) taşımayan API uç noktası (geçiş boyunca,
    2-7. adımlarda, yalnız geçen modüllerde; 7. adımın sonunda bütün uç noktalarda);
  - bağımlılık yönüne aykırı bölüm kullanımı;
  - ekran metinlerinde, iş akışı kurallarında ya da kayıt türlerinde kullanılan ama katalogda
    olmayan anahtar.

### 5.2 Saklama ve geçmiş

- **`core.AccessOverride`** her kişiye özel ayar dönemi için bir satır tutar: kişi, bölüm, düzey,
  etki (ekle ya da kaldır), gerekçe (zorunlu), başlangıç, değiştiren, bitiş, bitiren ve bitiş
  nedeni.
  - Düzeyler: Görür, Değiştirir ve Onaylar. Açık okumalı bölümü olan her modülde ayrıca bir
    **"Açık kayıtlar"** satırı vardır (anahtar `<modül>.open_records`). Tek düzeyi **Kayıtları
    okur**'dur; herkeste vardır ve yalnız "kaldır" satırı alır (§5.3).
  - Satır silinmez; bitmiş satır değişmez.
  - Kişi, bölüm ve düzey başına en çok bir etkin satır olur.
- **Denetim günlüğü:** her kaydetme, kullanıcı üzerinde tek bir `AuditLog` yazar. Kayıt roller ve
  yetkileri önce ve sonra hâliyle tutar; gerekçe nottadır. Kimin ne göreceği §5.6'dadır.
- **Hücreyi rol varsayılanına döndürmek** etkin satırı bitirir.
- **Etkisiz kalan ayar kendiliğinden bitmez.** Ör. sonradan verilen bir rol aynı yetkiyi veriyorsa
  kişiye eklenen yetki etkisiz kalır. Ekranda işaretlenir; "Etkisiz ayarları temizle" bu satırları
  bitirir (bitiş nedeni: etkisiz), silmez. Böylece bir kısıtlama sonraki rol değişikliklerinde
  görünür biçimde korunur.
- **Admin rolü verilince ya da süper kullanıcı yapılınca** kişinin etkin ayarları gerekçeyle biter.
- **Yönetim rolü alınınca** KVKK bölümlerindeki eklemeler gerekçeyle biter. Kaldırmalar kalır:
  kişi role dönerse kısıtı sürer.
- **`core.AccessCatalogSnapshot`:** paketler yeni bir sürümle değişince kataloğun bir kopyası
  saklanır.
  - Kopyayı `sync_access_catalog` komutu yazar. Komut, canlıdaki göç servisinde `seed_roles`'tan
    sonra kendiliğinden çalışır.
  - Kopya değişmez; denetim günlüğüne "Yetki paketleri değişti" kaydı düşer.
  - Geçmiş bir tarihteki yetkiler bu kopyadan, rol değişikliklerinden ve ayar dönemlerinden
    yeniden kurulabilir (ISO ve KVKK denetimi).

### 5.3 Geçerli yetki

```text
pasif ya da anonim                → hiçbir şey
admin ya da süper kullanıcı       → her şey
P = TEMEL ∪ rol paketleri ∪ etkin eklemeler
P = P − etkin kaldırmalar
    Görür kaldırılırsa o bölümün Değiştirir ve Onaylar'ı da düşer.
Değiştirir ya da Onaylar → Görür   (yalnız Görür düzeyi olan bölümlerde)
KVKK bölümleri: kişi yönetim rolünde değilse düşer
ön koşulu karşılanmayan düzey düşer (düzey bazında; sabit noktaya kadar)
bölüm okuması: Görür
       ya da  kapsam = ortak (seçim listeleri; herkes)
       ya da  kapsam = rolü olan  ve kişinin rolü var
       ya da  kapsam = açık okuma  ve kişiden modülün "Kayıtları okur"u kaldırılmamış
kayıt okuması: kayıt türünün okuma bölümlerinden (§5.1) birinde bölüm okuması
```

- Açık okumalı bölümde Görür'ü kaldırmak yalnız ekranı kapatır; kayıtlar başka ekranlardan
  okunmaya devam eder. Kayıtları da kapatmak için modülün "Açık kayıtlar" satırında Kayıtları okur
  kaldırılır: kişi o modülün kayıtlarını yalnız Görür'ü olan bölümlerden okur. Kayıtları okur
  Görür, Değiştirir ve Onaylar'ı değiştirmez. Bu, kişinin Görür'ü varsayılan olsun olmasın
  uygulanır.
- Kapatmada da açık kalanlar (Faz B'nin istisnaları):
  - lot sayfasının kalite bölümü: `GET /quality/samples/?lot=` lot verilince Lotlar okumasını
    izler; lotsuz liste ve numune sayfası kapanır;
  - üretim emri formundaki reçete seçimi: `GET /recipes/recipes/` Reçeteler'i okuyamayana yalnız
    kod, eski kodlar, ad, ürün ve onaylı sürümü döner; recipes modülü üretim bölümlerine bakmaz;
  - seçim listeleri (Ana veriler'de sade kart, §3.1 ve §5.6);
  - mal kabulün lot etiketleri (§3.3);
  - analiz sertifikası: `GET /quality/samples/{id}/coa.pdf` Lotlar okumasını izler (§3.3).
- Kapatma modülün herkese açık ekranlarını ve başka modüllerin ekranlarını da etkileyebilir (ör.
  Depo kapatılınca lot sayfasındaki, satın alma sipariş sayfasındaki ve izlenebilirlikteki mal kabul
  bağlantıları düz metin olur; Ana veriler kapatılınca Sevkiyat'taki müşteri kartı, Satış
  siparişleri: Görür'ü olmayan kişide sade kart olur). Kaydetme özetinde bu ekranlar uyarı olarak
  yazar (§5.1).
- Hesap her istekte veritabanından yapılır; istekler arası önbellek yoktur. Değişiklik bir sonraki
  istekte geçerlidir. Çok kişiyi birlikte hesaplayan yerler (görev alıcıları, @bahsetme önerileri,
  rapor) rolleri ve ayarları önceden yükler.

### 5.4 Denetim

- **API:**
  - `HasAccess(bölüm, düzey)`;
  - `ReadRule(*bölümler)`: bölümlerden herhangi birinde okuma yeter (ör. emir okuması Üretim
    emirleri, Malzeme hazırlama ya da Şarj ve tartım ile);
  - `AccessMixin(action_access={...})`: bilinmeyen yazma eylemi reddedilir.
  - 403 yanıtı `required` listesiyle eksik yetkiyi de söyler.
- **Servis:** `require_access(actor, bölüm, düzey)`. Mesajlar rol adı değil yetki söyler (ör.
  "Üretim emrini onaylama yetkiniz yok.").
- **Her modül geçişi bugünkü denetimleri birebir çevirir.** API ve servis denetimi aynı PR'da
  değişir. Bugün yalnız API'de olan denetim yalnız API'de kalır. `post_movement` denetim yapmaz.
  Örnek: satın almada onay uç noktası ve `approve_order` servisi bugün önce sipariş yazanları
  (`ORDER_ROLES`) denetler. İkisinde de yeni ilk denetim "Satın alma siparişleri: Onaylar ya da
  Limit üstü sipariş onayı: Onaylar"dır. Ardından D-13 (`can_approve`) aynen kalır: Limit üstü
  sipariş onayı her tutarı onaylar; Satın alma siparişleri: Onaylar yalnız limit girilmişse ve
  tutar limit içindeyse onaylar. Taslağa geri göndermede uç nokta aynı "ya da" denetimini,
  `return_to_draft` servisi Limit üstü sipariş onayı: Onaylar'ı ister.
- **Giriş noktası kuralı:** yalnız kişinin çağırdığı işlem denetlenir. Sistemin onun adına
  yürüttüğü ardıl adımlar denetlenmez; ardıl yetkisi olmayan bir kişiyle bunu test kanıtlar. Bu
  adımlar:
  - lot serbest kalınca emrin tamamlanması;
  - numune açılması;
  - maliyet hesabı;
  - iade sonucu;
  - rezervasyonun bırakılması;
  - tank temizliği kaydında açılan iş emrinin tamamlanması.
- **Modüller arası okumalar:**
  - Tartım ve şarj başlatma, kalibrasyon ve tank temizliği durumunu "Kalibrasyon: Görür" ya da
    "Şarj ve tartım: Değiştirir" ile okur.
  - İade formunun sevk edilmiş sevkiyat seçimi iadeler modülünün kendi uç noktasından gelir.
    Uç nokta "İade kayıtları: Değiştirir" ister ve yalnız müşterinin sevk edilmiş sevkiyatlarını
    numara, sipariş ve tarihle döner.
  - Maliyet, personel kaydını kendi bölümüyle denetler; personelin günlük yardımcısını denetimsiz
    çağırır.

### 5.5 Sözleşme testi: "kişiye özel ayar yoksa hiçbir şey değişmez"

Dört parçası da 1. adımda, bugünkü kod değişmeden üretilir:

1. **Uç nokta anlık görüntüsü.** Her API uç noktası 14 personayla denenir ve izin/401/403 kararı
   dondurulur. Personalar: anonim, pasif kullanıcı, rolsüz kullanıcı, 8 rolün her biri, admin,
   rolsüz süper kullanıcı, depo+sevkiyat.
2. **Sondalar.** Yetki kararının işlevin içinde verildiği yerler de dondurulur:
   - pano ve rapor listeleri, rapor sütunları;
   - fiyat ve maliyet görünürlüğü, gizli alanlar, geçmişteki notlar ve iç içe kayıtlar;
   - kayıt okuma, ek ekleme, kod önerisi;
   - her görev ve bildirim kuralının alıcıları, görev görünürlüğü ve üstlenme;
   - D-13 onay limiti;
   - bakımda sorumlu birim kuralı;
   - olay ve sorun bildirimi görünürlüğü;
   - yönetimin denetim günlüğünde gördüğü kayıtlar ve alanlar (her model);
   - iki aşamalı doğrulama zorunluluğu.
3. **Paket denkliği.** Bugünkü her rol sabiti için şu doğrulanır: o bölümü o düzeyde veren roller
   eski rollere eşittir. Ön yüzün rol sabitleri (`modules/*/config.ts` ve satır içi rol dizileri)
   de buna dahildir; böylece düğmeler de kanıtlanır.
4. **Ön yüz eşlik anlık görüntüsü.** Her persona için görünen menü, modül sekmeleri, rota
   korumaları, varsayılan sekme, arama kaynakları, pano kartlarındaki bağlantılar ve ortak kayıt
   bağlantısının kararı (persona × hedef rota) dondurulur.

Ayrıca **kural kapsama testi**: her görev ve bildirim kuralının rol paketi, kuralın gerektirdiği
yetkiyi verir. İki istisna listededir (§5.7).

**İzin listesi:** dört parçanın her biri §8'in maddelerine bağlı açık bir izin listesi taşır
(madde numarası → beklenen fark). Bu planın eklediği uç noktalar da listede adıyla yer alır:
katalog, `me/access`, `users/{id}/access` ve geçmişi, `access/report`, iadelerin sevkiyat seçimi.
Planın eklediği iki kayıt türü (kişiye özel yetki ve paket sürümü; denetim günlüğünde 1-5.
adımlarda bugünkü gibi yönetime de, 6. adımdan sonra yalnız admine görünür) ve Sistem > Rol
yetkileri sekmesi de listededir (sahibin onayıyla, 2026-11-11).
Liste 1. adımda sözleşme testiyle birlikte yazılır; her adım yalnız kendi maddelerini açar. §8'in
maddeleri bu planın onayıyla onaylanmış sayılır. Başka her fark ve anlık görüntü güncellemesi
sahibin onayını ve DECISIONS kaydını ister.

### 5.6 Hassas alanlar

- **Mal kabul:** fiyat alanları yanıtta Fiyatları görür'e, girişte "Mal kabul fiyat ve masrafları:
  Değiştirir"e bağlıdır. Fiyatı görebilen ama giremeyen kişinin gönderdiği fiyat yok sayılır.
- **Satın alma:** birim fiyatlar, tutarlar ve geçmişteki tutarlar Fiyatları görür'e bağlıdır.
  Sipariş PDF'i hem sipariş Görür hem Fiyatları görür ister.
- **Müşteri ve tedarikçi kartı (sade kart, §3.1):** `tax_office`, `tax_number`, `address`, `phone`,
  `email` ve `contact_person` yanıtta boş döner; öteki alanlar aynen kalır. Arama yalnız kod, eski
  kod ve adda yapılır; vergi numarasında ve yetkili kişide aranmaz. masterdata satış bölümüne
  bakmaz: sales, `access.py`'sinde "Satış siparişleri: Görür müşteri kartının tam alanlarını açar"
  kaydını kayıt defterine yazar; masterdata tam ya da sade kart kararını kayıt defterinden okur
  (CLAUDE.md §3).
- **Maliyet:** lot maliyeti, Maliyet modülü, stok değeri ve raporların maliyet sütunları
  Maliyetleri görür'e bağlıdır. Panodaki onay bekleyen sipariş toplamı Fiyatları görür'e bağlıdır.
- **Kayıt geçmişi ve denetim günlüğü:**
  - Gizli alanlar, iç içe kayıtların içi (silinen satır ve ek masraf) ve tutar içeren notlar
    (satın alma durum notları, mal kabul fiyat düzeltmesi) yetkisi olmayana gösterilmez.
  - Not araması kişiye gizlenen notları kapsamaz.
  - Yeni kayıtlarda tutar not yerine alan değişikliğinde tutulur.
- **Denetim günlüğü süzmesi** (yalnız yönetim) kayıt defteriyle yapılır: her modül kendi modelleri
  için gereken bölümü ve gizli alanları kaydeder (core.records gibi). Örnekler:
  - personel kayıtları ilgili personel bölümünü ister;
  - olay kayıtları "Olaylar ve kazalar: Görür" ister;
  - maliyet kayıtları Maliyetleri görür'ü ister;
  - fiyat alanları ve satın alma onayı görevinin açıklaması Fiyatları görür'ü ister.

  Süzme yalnız kaydında bölüm ya da gizli alan bildiren modellere uygulanır. Satır kuralları (ör.
  sorun bildirimini yalnız bildiren ve admin okur) ve yalnız admin bölümleri (ör. kodlama
  sistematiği) denetim günlüğünde süzme yapmaz. Kullanıcı kaydında yalnız kişiye özel yetki
  alanları ve gerekçe gizlenir. Böylece giriş, çıkış ve rol kayıtları, sorun bildirimleri ve
  onlara yazılan yorumlar yönetime bugünkü gibi görünür. Yorum ve ek kayıtları bağlı oldukları
  kaydı izler: bağlı kayıt süzülüyorsa (ör. olay) yorum ve ek de aynı bölümü ister.
- **Yetki kayıtları:** kullanıcı üzerindeki kaydetme kaydında rollerin önce ve sonra hâli bugünkü
  gibi yönetime de görünür. Kişiye özel yetkilerin önce ve sonra hâli ve gerekçe notu yalnız
  admine görünür. `AccessOverride` ve `AccessCatalogSnapshot` kayıtları yalnız admine görünür.
- **Rapor dosyaları:** iş kaydı, raporun bölümünü ve dosyada maliyet ya da fiyat sütunu bulunup
  bulunmadığını tutar. İndirmede bunlar yeniden denetlenir; yetki yoksa "Bu dosyayı indirme
  yetkiniz artık yok." döner (§8 madde 12).
- **Personel maliyetinden açılan gider oranı:** yeni oranın notunda yalnız bordro numarası yazar.
  Var olan oranların notundaki tutar, Personel maliyeti: Görür'ü olmayana gösterilmez (ekranda ve
  denetim günlüğünde).

### 5.7 Görevler ve bildirimler

- **Her görev kuralı gerektirdiği yetkiyi `workflow/rules.py`'de bildirir** (§5.1). Örnekler:
  - Malzeme hazırla → Malzeme hazırlama: Değiştirir;
  - Sevki onayla → Sevkiyatlar ve irsaliye: Onaylar;
  - Satın alma onayı → Limit üstü sipariş onayı: Onaylar.
- **Görev alıcıları:** kuralın rolünün üyelerinden yetkisi olanlar. Görevi görmek, üstlenmek ve
  tamamlamak da bu yetkiye bağlıdır (karar 5).
- **Üstlenen kişi** yetkisini ya da rolünü kaybederse görevi görmez ve tamamlayamaz; yetkili başka
  bir üye tamamlar.
- **Kişiye atanmış görev** atanan kişiye görünür; işi yapmak için yine gereken yetki gerekir.
- **"Tüm birimlerin görevleri"** (yönetim) başka rollerin görevlerini bugünkü gibi gösterir; bağlı
  kayda göre süzülmez (admin rolünün sorun bildirimi görevleri dahil). Kişinin kendi rollerinin
  görevlerinde karar 5 geçerlidir. Başka birimlerin görevlerini kişiden gizlemek için bu bölümün
  Görür'ü kaldırılır.
- **Bildirim alıcıları:** kuralın rollerinin üyelerinden kuralın bölümünde Görür'ü olanlar.
  - Yükten gelen kişiler (ör. siparişi açan) de aynı denetimden geçer (§8 madde 10); rapor
    isteyen süzülmez.
  - İptal bildirimleri ve görevlerin anlık (WebSocket) kitlesi aynı süzgeci kullanır.
  - Tartım sapması ve ara kontrol reddi §12'deki karara kadar süzülmez; bugünkü gibi gider.
- Satın alma onayı görevinin açıklamasındaki tutarlar, Fiyatları görür'ü olmayana boş görünür.
- **Kimse kalmıyor uyarısı:** bir kural için rolde yetkili kimse kalmıyorsa yetki ya da rol
  kaydedilirken uyarı çıkar. Canlıya geçiş hazırlık listesine ve sistem durumuna aynı denetim
  eklenir.
- "Kayda git" bağlantısı yalnız hedef sayfa açılabiliyorsa görünür; hedef rotanın korumasına göre
  belirlenir.

### 5.8 Kayıt paneli

- Yorum, geçmiş, ek ve @bahsetme kayıt okumasını izler: kayıt türünün okuma bölümlerinden (§5.1)
  birinde okuma yeter.
- Yalnız Görür'ü olan da yorum yazar, @bahseder ve dosya ekler (bugünkü gibi). Kayda bağlı yorum,
  birimler arası haberleşme kanalıdır (CLAUDE.md §1).
- Yorumu yalnız yazanı düzenler. Eki yükleyen ya da admin kaldırır. GBF, atık ve olay eklerinin
  kendi kuralları sürer.

### 5.9 Ön yüz

- **`me` yanıtı:** `access` (bölüm → harfler: `r` okur, `v` görür, `c` değiştirir, `a` onaylar) ve
  `is_admin` eklenir.
- **Yardımcılar:** `can()`, `canRead()`, `canAny()`, `useCan()`, `<RequireAccess>`.
- **Rota korumaları:**
  - Modül sayfaları ve birden çok bölümün kayıtlarını gösteren alt sayfalar (hazırlama, toplama,
    emir, parti ve numune sayfaları) bugünkü gibi modülün Görür'ü olan bölümlerinin birleşimiyle
    açılır. Rolsüz kullanıcıda İSG ve Panolar ve raporlar sayfaları kapanır (§8 madde 1).
  - Tek bölüme ait alt sayfalar o bölümün Görür'üyle açılır: `personel` ve personel kartı →
    Personel kartları; `personel/puantaj` ve `personel/tatiller` → Puantaj ve tatil takvimi;
    `personel/ucretler` → Ücretler; `personel/bordro` → Bordro; `maliyet/lotlar` → Lot
    maliyetleri; `kalite/spesifikasyonlar` → Spesifikasyonlar; `dolum/ambalaj-receteleri` →
    Ambalaj reçeteleri; `gecis/karsilastirma` → Stok karşılaştırma. Varsayılan paketlerde sonuç
    bugünkü korumayla aynıdır; eşlik testi bunu kanıtlar. Personel kartlarını göremeyen kişide
    Personel menü bağlantısı açabildiği ilk personel sayfasına gider.
  - Depo'nun belge sayfaları (mal kabul ve sayım düzeltme) kayıt okumasıyla (`r`) açılır;
    okuyamayana "Yetkiniz yok" çıkar, bağlantıları gizlenir. Varsayılanda herkes okur (bugünkü
    gibi).
  - `/raporlar/indirmeler` herkese açıktır.
  - Yeni emir sayfaları ve satın alma sipariş ayrıntısı §8'deki gibi daralır.
- **Pano kartlarındaki bağlantılar**, hedef rota ve hedef sekmenin korumasına göre görünür (ör.
  `/satin-alma/siparisler` → Satın alma siparişleri: Görür). Varsayılan sonuç bugünkü rol
  listeleriyle (`menuRoles`, `ORDER_READ_ROLES`, `APPROVAL_ROLES`) aynıdır.
- **Kayıt bağlantıları** (panolarda, kayıt sayfalarında, aramada ve "Kayda git") ortak bir
  bileşenle çizilir: hedef sayfa açılabiliyorsa bağlantı, açılamıyorsa düz metin olur. Bugün
  koşulsuz olan bu bağlantılardan yalnız §8 madde 2'dekiler değişir. Eşlik testi ikisini de
  kanıtlar.
- **Onay düğmesi:** Onaylar'ı olan ama Değiştirir'i olmayan kişi onay düğmesini görür. Düğme
  taslağı yeniden kaydetmeden yalnız onay adımını çağırır (satış siparişi onayı, satın alma onayı,
  sayım düzeltme kaydı).
- **Rol görünümü:** `hasAnyRole` yalnız rolün görünümünde kalır: üst bant rengi, açılış sayfası,
  rol kılavuzları, rozetler, varsayılan sekme tercih sırası.
- **Varsayılan sekme:** bugünkü seçim birebir korunur; görünür değilse ilk görünür sekme açılır,
  hiçbiri yoksa "Yetkiniz yok" sayfası. Çok rollü kişide sonuç eşlik testiyle kanıtlanır.
- **Yönetim panosu:** menü öğesi, `/pano` ve açılış sayfası yönetim rolü ile "Yönetim panosu:
  Görür"ün ikisini birlikte ister (§3.15).
- **Oturum tazeleme:** `access.changed` WebSocket iletisi gelince `me` yenilenir. Pencere odağında
  ve 403 yanıtında da yenilenir. Kullanıcı düzenleme penceresinden yapılan rol değişikliği de bu
  iletiyi yayınlar (§8 madde 11). Django panelindeki rol değişikliği yayınlamaz; panel 9. adımda
  salt okunur olur.
- **"Yetkiniz yok" sayfası:**
  - metin: "Bu sayfayı görme yetkiniz yok. Gerekiyorsa sistem yöneticinizden yetki isteyin.";
  - eksik yetki biliniyorsa: "Gerekli yetki: Üretim › Üretim emirleri (Görür)";
  - düğmeler: "Ana sayfaya dön" ve Paket B ile "Yetkilerimi gör".

### 5.10 Yönetim kuralları (`core.services.set_user_access`)

| Kural | Kod | Mesaj |
|---|---|---|
| Yetkileri yalnız admin değiştirir | 403 | "Yetkileri yalnızca sistem yöneticisi değiştirir." |
| Gerekçe zorunlu (en az 5 karakter) | `access_note_required` | "Değişikliğin gerekçesini yazın." |
| Kişi kendi kişiye özel yetkilerini değiştiremez | `cannot_edit_own_access` | "Kendi yetkilerinizi değiştiremezsiniz." |
| Admine kişiye özel yetki tanımlanmaz | `admin_has_all_access` | "Sistem yöneticisi bütün yetkilere sahiptir; kişiye özel yetki tanımlanmaz." |
| Bilinmeyen bölüm ya da düzey | `unknown_access` | "Tanımsız yetki: {bölüm} ({düzey})." |
| Yalnız admin düzeyi | `access_not_grantable` | "Bu yetki yalnızca sistem yöneticisine aittir." |
| KVKK bölümü, kişi yönetimde değil | `access_requires_role` | "Bu yetki yalnızca yönetim rolündeki kullanıcılara verilebilir (KVKK)." |
| Ön koşul eksik | `access_requires` | "Bu yetki için önce “Maliyetleri görür” yetkisi gerekir." |
| Görür kapalıyken Değiştirir ya da Onaylar açık | `access_conflict` | "Görmeyi kaldırdığınız bölümde değiştirme ya da onay yetkisi verilemez." |
| "Açık kayıtlar" satırına ekleme | `open_records_revoke_only` | "Açık kayıtları herkes okur; bu satır yalnız bir kişi için kapatılabilir." |
| Sayfa açıldıktan sonra başkası kaydetti | `access_changed` | "Yetkiler siz düzenlerken değişti; sayfayı yenileyin." |

- **Roller:**
  - Kişi kendi rollerini bugünkü gibi değiştirebilir, kendi admin rolünü kaldıramaz. Son admin
    kuralları değişmez.
  - Paket B'den sonra roller yalnız Yetkiler ekranında, gerekçeyle değişir (§8 madde 13).
    `PATCH /users/{id}/` rol alanını kabul etmez; yeni kullanıcının ilk rolleri açılış
    penceresinde `POST /users/` ile verilir.
- **Uyarılar** kaydı engellemez:
  - görevi alacak kimse kalmıyor;
  - eklenen yetkinin görevi kişinin rolüne gitmiyor (ör. Şartlı kabul onayı görevi yönetim rolüne
    gider);
  - rolü olmayan kişi görev almaz;
  - görev ayrılığı (§5.11);
  - yönetim rolü kaldırılıyor (KVKK yetkileri düşer);
  - admin rolü veriliyor;
  - kullanıcı pasif;
  - kişiye hassas yetki veriliyor ama iki aşamalı doğrulaması kurulu değil;
  - açık kayıtlar kapatılıyor: etkilenen başka ekranlar (§5.3).
- **Uç noktalar:**
  - `GET/PUT /api/v1/users/{id}/access/` (yalnız admin): matris; roller isteğe bağlıdır ve aynı
    işlemde kaydedilir. `dry_run: true` ile kaydetmeden değişiklik özetini ve uyarıları döner;
    Kaydet özet penceresi uyarıları buradan alır.
  - `GET /api/v1/users/{id}/access/history/` (yalnız admin).
  - `GET /api/v1/access/report/` ve Excel'i (yalnız admin).
  - `GET /api/v1/access/catalog/` (giriş yapan herkes).
  - `GET /api/v1/auth/me/access/` (giriş yapan herkes, Yetkilerim): kişinin bölümleri, düzeyleri,
    kendisi için kapatılan açık kayıtlar ve kaynakları. Gerekçe, değiştiren ve geçmiş dönmez.
  - Kullanıcı listesinde `personal_counts` ve `has_personal` süzgeci.
- **Django yönetim paneli:** yeni modeller, kullanıcının rolleri, süper kullanıcı ve panele giriş
  (`is_staff`) işaretleri salt okunurdur. Süper kullanıcı yalnız sunucuda `createsuperuser` ile
  açılır.
- **Kişiye bildirim:** yetkisi ya da rolü değişen kişiye "Yetkileriniz güncellendi" bildirimi
  gider. Gerekçe gösterilmez.

### 5.11 Görev ayrılığı

- **Şartlı kabul:** onaylayan kişi, öneriyi yapan (kararı veren) kişiden farklı olmalıdır; admin
  dahil (`conditional_same_person`: "Şartlı kabulü öneren kişi onaylayamaz; başka bir yönetici
  onaylamalı.").
- **Riskli çiftler** katalogda tek yerde tanımlıdır:
  - Şarj ve tartım: Değiştirir + Numuneler ve kalite kararı: Onaylar;
  - Dolum hattı: Değiştirir + Numuneler ve kalite kararı: Onaylar;
  - Mal kabul: Değiştirir + Numuneler ve kalite kararı: Onaylar;
  - Satın alma ayarları: Değiştirir + Satın alma siparişleri: Onaylar ya da Limit üstü sipariş
    onayı: Onaylar;
  - Numuneler ve kalite kararı: Onaylar + Şartlı kabul onayı: Onaylar.
- İki yetki aynı rol paketinden geliyorsa (bugünkü iş bölümü) uyarı çıkmaz. Farklı kaynaklardan
  geliyorsa (iki rol ya da rol ve kişiye ekleme) uyarı çıkar ve "Kim neyi görür" raporunda
  işaretlenir.

## 6. Ekranlar

### 6.1 Sistem > Kullanıcılar > Yetkiler

Adres `/sistem/kullanicilar/:id/yetkiler`. Bu bir tam sayfadır, açılır pencere değil; kullanıcı
listesindeki yeni "Yetkiler" düğmesinden ya da kişinin adından açılır.

- **Bölümler:**
  - Roller: rol değişikliği buraya taşınır.
  - Hassas veriler: Fiyatları görür, Maliyetleri görür ve KVKK notu.
  - Modül yetkileri: modül başına açılır kapanır; satırlar bölümler, sütunlar Görür, Değiştirir ve
    Onaylar.
  - Altta yapışkan kaydet çubuğu.
- **Hücre durumları:**
  - Rolden: mavi onay işareti; ipucu "Depo rolünden".
  - Eklendi: yeşil, artı işaretli.
  - Kaldırıldı: kırmızı, eksi işaretli.
  - Verilmedi: boş.
  - Kilitli 🔒: herkese açık, yalnız admin ya da KVKK.
  - Bu bölümde yok: —.

  Renk tek ipucu değildir: her durumun simgesi ve yazısı vardır. Kaydedilmemiş hücrede sarı nokta
  bulunur.
- **Tıklama** hücreyi tersine çevirir; ikinci tıklama rol varsayılanına döndürür.
- **Bağlı yetkiler:**
  - Değiştirir ya da Onaylar açılınca Görür de açılır.
  - Görür kapanınca öteki düzeyler de kapanır.
  - Eksik ön koşul önerilir ve satırın altında açıklanır, ör. "Satın alma › Siparişler:
    Değiştirir için Fiyatları görür de verildi."
  - Bir bölüm başka bir bölüm üzerinden okunmaya devam ediyorsa satırda yazar, ör. "Emirleri
    Malzeme hazırlama üzerinden görmeye devam eder."
- **Açık kayıtlar:** açık okumalı bölümün satır ayrıntısında "Bu bölümün kayıtlarını giriş yapan
  herkes okuyabilir." yazar. Modülün son satırı "Açık kayıtlar"dır: "Herkes okur" ya da "Bu kişi
  için kapalı". Kapatınca satırın altında kişinin bu kayıtları hangi bölümlerden okumaya devam
  ettiği ve etkilenebilecek başka ekranlar yazar (§5.3).
- **Toplu işlemler:**
  - modül satırındaki üç durumlu kutular;
  - "Rol varsayılanına dön", "Yalnız görsün", "Modüldeki bütün yetkileri kaldır";
  - "Tümünü rol varsayılanına döndür", "Etkisiz ayarları temizle".

  "Modüldeki bütün yetkileri kaldır" Görür, Değiştirir ve Onaylar'ı kaldırır; Açık kayıtlar
  satırını değiştirmez, o satır ayrıca kapatılır.
- **Arama ve süzgeç:** "Bölüm ara" ve "Yalnız kişiye özel ayarlar".
- **Kaydet** özet penceresini açar. Pencerede şunlar bulunur:
  - rol değişiklikleri;
  - verilecek ve kaldırılacak yetkiler;
  - menüye eklenecek ve menüden kalkacak modüller;
  - uyarılar;
  - zorunlu "Değişiklik notu".

  Kaydedince kişinin açık oturumu saniyeler içinde yenilenir. Kaydedilmemiş değişiklikle sayfadan
  çıkarken sorulur.
- **Admin olan kişi:** matris yerine "Sistem yöneticisi her ekranı görür ve her işlemi yapar;
  kişiye özel yetki uygulanmaz." yazar. Admin kendi sayfasında yalnız rollerini değiştirir.
- **Telefonda** bölümler kart olur, düzeyler üç düğme olur.
- **Geçmiş sekmesi:** tarih, değiştiren ve gerekçe; altında "Eklendi", "Kaldırıldı", "Rol
  varsayılanına döndü" ve "Roller: Depo → Depo, Planlama" satırları.

### 6.2 Sistem > Rol yetkileri (salt okunur)

- Rollerin paketleri tek tabloda gösterilir: Herkes ve 8 rol, hücrelerde "G D O" harfleri. İstenirse
  tek bir rol seçilir.
- **"Kimde var?":** bir hücre, o yetkiyi etkin olarak taşıyan kişileri kaynaklarıyla listeler (rolden,
  kişiye özel eklendi, rolde var ama kaldırıldı). "Kim neyi görür" raporu budur.
- **"Excel'e aktar":** paketleri ve kişilerin geçerli yetkilerini aktarır; paketlerin imzalanması
  ve denetim için.

### 6.3 Kullanıcı listesi ve düzenleme penceresi

- **Liste:**
  - "Kişiye özel: 3" rozeti; ipucu "2 yetki eklendi, 1 yetki kaldırıldı";
  - "Yetkiler" düğmesi;
  - Rol, Durum ve "Yalnız kişiye özel yetkisi olanlar" süzgeçleri (adreste saklanır).
- **Düzenleme penceresi:** roller rozet olarak görünür; değiştirmek için "Rolleri ve yetkileri
  değiştir" bağlantısı vardır. Yeni kullanıcıda rol seçimi pencerede kalır.

### 6.4 Yetkilerim (`/yetkilerim`, herkes)

Kişinin rolleri, hassas hakları ve yetkisi olan modüller kaynaklarıyla birlikte görünür ("Rolünüzden
(Depo)", "Size özel verildi", "Sizin için kaldırıldı"). Kişi için kapatılan açık kayıtlar,
modülde başka yetkisi olmasa da görünür (ör. "Sizin için kapalı: Kalite kayıtları"). Sayfa salt
okunurdur.

### 6.5 Yetkisi değişen kişi ne görür

- Menü, sekme ve düğmeler hemen yenilenir.
- Açık sayfa artık izinli değilse "Yetkiniz yok" sayfası çıkar.
- Zil bildirimi "Yetkileriniz güncellendi" gelir ve Yetkilerim'e götürür.

## 7. Belgeler

- **CLAUDE.md:** §11'deki metin plan onayıyla onaylanır; 1., 8. ve 9. adımların commit'lerinde
  yazılır (§11).
- **DECISIONS.md:** sahip kararları ve plan kuralları (bu planla birlikte yazıldı). Sonraki
  sorular ve Faz B onayı da buraya eklenir.
- **KVKK.md:**
  - Teknik tedbir satırı şöyle olur: "Erişim yetkisi modül bölümü ve düzey bazındadır; roller
    varsayılan pakettir, kişiye özel değişiklikler gerekçeli ve geçmişiyle saklanır; güncel liste
    Sistem > Rol yetkileri'ndedir."
  - "Kim görür" sütunu bölüm ve varsayılan bazında yeniden yazılır.
  - Seçim listelerindeki müşteri ve tedarikçi iletişim bilgileri, irsaliyedeki şoför kimlik numarası
    (§12), bulut taşınması ve iki aşamalı doğrulama durumu güncellenir.
- **Kılavuzlar:**
  - `admin.md`: yeni "Kullanıcı yetkileri" bölümü.
  - `genel.md`: "Bir ekranı göremiyorsanız yetkiniz yoktur; gerekiyorsa sistem yöneticinizden
    isteyin. Yetkileriniz değişince ekran kendiliğinden yenilenir."
  - `yonetim.md`: ana veriyi planlamanın değiştirdiği düzeltilir; personel ve bordronun yalnız
    yönetime verilebildiği eklenir.
  - `laboratuvar.md` ve `satin-alma.md`: Onaylar yetkisi.
  - `gecis.md`: ortak hesap notu.
- **PROGRESS.md** her adımda güncellenir. Ekran görüntüsü betiğine matrisin bir görüntüsü eklenir.

## 8. İlk gün değişiklikleri (tam liste)

Kişiye özel ayar yokken yalnız bunlar değişir; 6. ve 10-12. maddeler yalnız birinin rolü değişince
fark edilir. Sözleşme testi bu listeyi izin listesi olarak kullanır (§5.5).

**Paket A ile:**

1. Rolsüz kullanıcı "İSG ve çevre" ile "Panolar ve raporlar" menülerini ve sayfalarını (İndirmeler
   hariç; adresle açınca "Yetkiniz yok" çıkar) ve Görevlerim'deki "Arıza bildir" düğmesini görmez.
   Arkalarındaki çağrılar bugün de reddediliyor ya da boş liste dönüyor. Rolsüz kullanıcının üst
   bandı yönetici rengi yerine nötr olur.
2. Kişinin açamayacağı sayfaya giden kayıt bağlantıları düz metin olur, "Kayda git" gösterilmez.
   Bugün bunlar yalnız şuralarda var: lot sayfasındaki numune numaraları (laboratuvar ve yönetim
   dışındakiler), iade sayfasındaki numune bağlantısı (sevkiyat, depo), laboratuvar panosundaki
   numune numaraları (planlama) ve §12'deki iki bildirimin "Kayda git"i.
3. Sayfa korumaları:
   - Yeni üretim ve dolum emri sayfaları yalnız emir açabilenlere açılır (kaydetme bugün de
     reddediliyor).
   - Satın alma sipariş ayrıntısı yalnız siparişleri görebilenlere açılır.
4. Yetki hata mesajları ve "Yetkiniz yok" sayfası rol adı yerine gereken yetkiyi söyler.
5. Şartlı kabulü öneren kişi onaylayamaz, admin dahil (karar 10).
6. Görevi üstlenen kişi gereken yetkisini ya da rolünü kaybederse görevi görmez ve tamamlayamaz;
   yetkili başka bir üye tamamlar (karar 5'in sonucu).
7. Mal kabul ve satın alma siparişi geçmişinde tutar içeren notlar ve silinen satır ve ek masraf
   kayıtlarının içindeki fiyatlar, Fiyatları görür'ü olmayana gösterilmez. Denetim günlüğünde de
   aynı süzme uygulanır. Yeni onaya gönderme ve onay kayıtlarında tutar, kur ve limit notta değil
   ayrı alan satırlarında görünür (fiyatları görenlerde de).
8. Personel maliyetinden açılan yeni gider oranının notunda tutar yerine bordro numarası yazar.
9. Canlıya geçiş hazırlık listesine ve Sistem durumu ekranına "Her görevi alabilecek biri var"
   maddesi eklenir; sistem durumunda yalnız gösterilir, periyodik kontrollere girmez ve uyarı
   bildirimi göndermez. Kullanıcı düzenleme penceresinde rol kaydedilirken görevi alacak kimse
   kalmıyorsa uyarı çıkar; kaydı engellemez.
10. Yükten gelen bildirim alıcıları da yetkiyle süzülür: ör. siparişi açan kişi sonradan rolünü
    kaybettiyse "Sevk edildi" bildirimini almaz (pasif kullanıcı bugün de almıyor).
11. Kullanıcı düzenleme penceresinden rolü değişen kişinin (kendi rolünü değiştiren admin dahil)
    menüsü ve düğmeleri sayfa yenilenmeden saniyeler içinde güncellenir; pencereye dönünce ve ilk
    403'te de yenilenir. Bugün ancak sayfa yenilenince güncelleniyor.
12. Rapor dosyası indirilirken raporun yetkisi yeniden denetlenir: dosyayı istedikten sonra rolünü
    kaybeden kişi dosyayı indiremez.

Sahibin onayıyla eklendi (2026-11-11; 6. adımda): yönetim panosundaki onay bekleyen satın alma
siparişlerinin TL toplamını, panoyu açabilen ve Fiyatları görür'ü olan kişi de görür (ör. planlama
ve satın alma rollerini birlikte taşıyan, yönetimde olmayan kişi; bugün yalnız yönetim). Sözleşme
testinin personaları bu bileşimi içermez: katalogdaki kuralı reporting paket testi, kod
değişikliğini adıma bağlı `test_pending_purchase_total_for_planning_and_purchasing` denetler.

**Paket B ile:**

13. Var olan kullanıcının rolleri Yetkiler sayfasından ve gerekçeyle değişir. `PATCH /users/{id}/`
    rol almaz; yeni kullanıcının ilk rolleri açılış penceresinde verilir. Django panelinde roller,
    süper kullanıcı ve panele giriş işaretleri salt okunur olur.
14. Herkese Yetkilerim sayfası gelir; "Yetkiniz yok" sayfasına "Yetkilerimi gör" düğmesi eklenir.
15. Rolü ya da yetkisi değişen kişiye "Yetkileriniz güncellendi" bildirimi gider.
16. Canlıya almadan önce admin ve yönetim için iki aşamalı doğrulama yeniden zorunlu olur
    (karar 11).

## 9. Riskler

| Risk | Önlem |
|---|---|
| Paketler bugünkü listelerden sapar, ilk gün erişim değişir | Uç nokta anlık görüntüsü, sondalar, paket denkliği ve ön yüz eşlik testi her adımda; kişiye özel ayar ancak 9. adımda yazılabilir |
| API ve servis denetimleri ayrışır | İkisi aynı PR'da birebir çevrilir; geçen modülde rol denetimi kalmadığını test denetler |
| Modüller arası seçimler bozulur (seçim listeleri, barkod okutma, lot sayfası, tartım, hazırlama ve toplama sayfaları) | Ortak ve rolü olan okumalar kişiden kapatılamaz; açık kayıtlar kapatılınca da lot sayfasının kalite bölümü, reçete seçimi, mal kabulün lot etiketleri, analiz sertifikası ve seçim listeleri (sade kart) açık kalır, etkilenen ekranlar kaydederken uyarıda yazar; "herhangi biri" okuma kuralı; alt sayfalar modülün birleşik korumasıyla açılır; anlık görüntü her okumayı kapsar |
| Kaldırılan ekranın verisi başka yoldan sızar (kayıt paneli, @bahsetme, denetim günlüğü, arama, görev, bildirim, pano, dışa aktarım) | §5.6, §5.7 ve §5.8; açık kayıtlar kişiye özel kapatılabilir; rapor dosyası indirilirken yetki yeniden denetlenir; Faz B |
| Ardıl adımlar yetki yüzünden bozulur | Giriş noktası kuralı ve testleri |
| Açık oturumlar eski yetkiyle kalır | API her istekte taze denetler; `access.changed`, odakta ve 403'te yenileme |
| Yetki yükseltme ya da herkesin dışarıda kalması | Yalnız admin yönetir; kendi kişiye özel yetkisini değiştiremez; zorunlu gerekçe; silinmez geçmiş; rol yalnız Yetkiler ekranından; Django panelinde roller ve süper kullanıcı salt okunur; son admin kuralları; admin ve yönetimde iki aşamalı doğrulama |
| KVKK (personel, bordro, sağlık verisi) | Yalnız yönetim kısıtı üç yerde: servis, hesap ve rol kancası; ücret ve bordro ön koşulları; denetim günlüğü süzmesi; Kim neyi görür raporu |
| Görev ayrılığı kişiye özel yetkiyle zayıflar | Onaylar ayrı; şartlı kabulde zorunlu dört göz; riskli çift uyarısı ve raporu |
| Görev kimseye düşmez | Kaydederken uyarı, canlıya geçiş hazırlık maddesi, sistem durumu |
| Matris büyük (76 bölüm, 7 "Açık kayıtlar" satırı ve 2 hassas hak) | Modül başına açılır kapanır; varsayılanlar görünür; "Yalnız kişiye özel ayarlar" süzgeci; toplu işlemler |
| Ortak tablet ya da hat hesabı kişiye özel yetkiyi ve ISO kaydını boşa çıkarır | §12 |

## 10. Adımlar

Her adım testler, `ruff` ve `mypy` yeşilken commit'lenir. Her paketin sonunda bağımsız bir
inceleme yapılır; push ve PR size sorulur. Canlıya alma yalnız "canlıya al" deyince yapılır.

### Paket A: davranışı değiştirmeyen geçiş

Canlıya alınabilir; kişiye özel ayar yazılamaz. Fark edilen yalnız §8'in Paket A maddeleri olur.

1. **Sözleşme testi ve altyapı.**
   - CLAUDE.md değişikliğinin ilk kısmı (§11).
   - Bugünkü kodla: uç nokta anlık görüntüsü, sondalar, paket denkliği, ön yüz eşlik anlık
     görüntüsü ve izin listesi (§5.5). Kod değişmeden yeşil olmalıdır.
   - Katalog (`access.py`'ler), `AccessOverride` ve `AccessCatalogSnapshot` modelleri ve göçü,
     `sync_access_catalog` komutu.
   - Geçerli yetki hesabı ve denetim ilkelleri.
   - `me.access` ve `is_admin`; katalog API'si.
   - Sistem denetimleri, `export_access`, `access.gen.ts` ve CI adımı.
2. **Ana veriler, reçeteler, depo:** fiyat ve maliyet alanları, lot geçmişi, kod önerileri, depo
   kayıt türleri; müşteri ve tedarikçi sade kartı; açık kayıtlar kapatılınca reçete seçiminin
   açık kalması; geçmişteki tutarlar (§8 madde 7).
3. **Üretim ve dolum.**
4. **Kalite, iadeler, izlenebilirlik:** karar = Onaylar; şartlı kabulde dört göz (§8 madde 5);
   lot sayfasının kalite bölümünün açık kalması; iadelerin sevkiyat seçimi.
5. **Diğer modüller:**
   - sevkiyat;
   - satın alma: D-13, limit üstü onay, fiyat alanları;
   - maliyet: ön koşullar, personel maliyeti notu;
   - personel: KVKK, ön koşullar, ayarlar satırı;
   - bakım: sorumlu birim;
   - İSG: olaylar, ekler;
   - canlıya geçiş.
6. **Ortak parçalar:**
   - panolar ve raporlar; rapor dosyası indirmede yeniden denetim (§8 madde 12);
   - denetim günlüğü süzmesi (kayıt defteriyle);
   - kayıt paneli ve ekler;
   - kullanıcı, cihaz ve sistem durumu (yalnız admin);
   - `SignedIn` işaretleri.
7. **İş akışı:**
   - kural yetkileri, görev ve bildirim alıcılarının süzülmesi;
   - görev görünürlüğü ve üstlenme;
   - Tüm birimlerin görevleri;
   - hassas görev açıklaması;
   - "kimse kalmıyor" uyarısı (kullanıcı düzenleme penceresinde de), hazırlık maddesi ve sistem
     durumu satırı (§8 madde 9);
   - kural kapsama testi;
   - yükten gelen alıcıların süzülmesi (§8 madde 10);
   - `access.changed` olayı, rol değişikliğinde de (§8 madde 11).
8. **Ön yüz:**
   - `can()` geçişi: menü, rotalar, sekmeler, düğmeler, arama, pano kartları, varsayılan sekme;
   - ortak kayıt bağlantısı bileşeni (panolar, kayıt sayfaları, arama, "Kayda git"; §8 madde 2);
   - "Yetkiniz yok" sayfası;
   - oturum tazeleme (§8 madde 11);
   - test yardımcıları (`userWith` bugünkü gibi çalışır) ve eşlik anlık görüntüsü;
   - CLAUDE.md kural 12'deki geçiş cümlesinin silinmesi (§11).

İzin listesinde §8 maddelerinin açıldığı adımlar: 4 → 2-8 (her modül kendi mesajları, 8. adımda
"Yetkiniz yok" sayfası); 7 → 2 (mal kabul), 5 (satın alma), 6 (denetim günlüğü); 5 → 4; 8 → 5;
12 → 6; 6, 10 → 7; 9, 11 → 7 ve 8; 1, 2, 3 → 8; 13-15 → 9; 16 → Paket B canlıya alınmadan önce.

Adım 2-7'nin her biri şu koşullarda bitmiş sayılır:
- anlık görüntü yalnız izin listesindeki maddeler kadar değişmiştir (§5.5) ve var olan bütün
  testler yeşildir;
- modülde `HasRole`, `_require_role`, `user_has_role` ve `has_role` kalmamıştır (`apps.py`,
  raporlar, serializer'lar ve kayıt türleri dahil). İzin listesi: iki aşamalı doğrulama, bakımda
  sorumlu birim, görev yönlendirme ve yetki hesabının kendi rol denetimleri (KVKK yalnız yönetim
  kısıtı, "rolü olan" kapsamı). Bunu bir test denetler;
- kişiye özel ayarla çalışan yeni testler geçer. Örnek: depo kullanıcısından "Malzeme hazırlama:
  Değiştirir" kaldırılınca hazırlık başlatma, okutma ve hazır bildirme 403 olur, emir okuması açık
  kalır;
- mesajlar rol adı içermez.

Ön yüzde 8. adımın sonunda `hasAnyRole` ve `menuRoles` yalnız rol görünümünde kalır.

### Paket B: yetki ekranı

9. **Kullanıcı yönetimi:**
   - `set_user_access` ve rol değişikliği kancası; uç noktalar; `PATCH /users/{id}/` rol almaz;
   - Yetkiler ve Geçmiş sekmeleri, Rol yetkileri sekmesi ve "Kimde var?", Yetkilerim;
   - Excel raporu; kullanıcı listesinde rozet ve süzgeçler;
   - Django paneli salt okunur; görev ayrılığı uyarıları; kişiye bildirim;
   - CLAUDE.md §5'in rol değiştirme cümlesi (§11).

   Elle duman testi:
   - Admin, depo kullanıcısından "Malzeme hazırlama: Değiştirir"i kaldırır. Kişinin açık
     oturumunda düğmeler saniyeler içinde kaybolur; okutma 403 olur; "Malzeme hazırla" görevi ona
     gelmez; geçmişte gerekçe görünür.
   - Admin aynı kişide Üretim'in üç bölümünde Görür'ü kaldırır. Menüden Üretim kalkar; yazma uç
     noktaları 403 olur; kayıt okuması (lot sayfası, @bahsetme) açık kalır. Üretim'in "Açık
     kayıtlar" satırı bu kişi için kapatılınca emir ve şarj okuması da 403 olur.
   - Aynı kişide Kalite'nin "Açık kayıtlar" satırı kapatılınca numune okuması 403 olur; lot
     sayfasının kalite bölümü açık kalır.
   - Ana veriler'in "Açık kayıtlar" satırı kapatılınca mal kabulde tedarikçi seçimi çalışır;
     tedarikçi kartı vergi, adres ve iletişim bilgisi olmadan döner; kaydetme özetinde etkilenen
     ekran uyarısı görünür. Kişi depo rolüyle Satış siparişleri: Görür'ü taşıdığı için müşteri
     kartını tam görmeye devam eder.

   Duman testi betiğine bu durum eklenir.
10. **Belgeler:** DECISIONS, KVKK.md, kılavuzlar, PROGRESS, ekran görüntüleri.

**Paket B'yi canlıya almadan önce:**
- İki aşamalı doğrulama admin ve yönetim için yeniden zorunlu olur (`OTP_REQUIRED_ROLES`). Bu
  rollerdeki kullanıcıların doğrulamayı kurması gerekir.
- §12'deki ortak hesap sorusu yanıtlanır.

### Paket C (sonra, ayrı onayla): Faz B

Açık okumalar Görür'e bağlanır. İstisnalar (§5.3'tekilerle aynı):
- lot sayfasının kalite bölümü;
- üretim emri formundaki reçete seçimi;
- seçim listeleri (müşteri ve tedarikçi seçiminde iletişim bilgisi içermeyen sade kart);
- mal kabulün lot etiketleri;
- analiz sertifikası.

Anlık görüntü farkı onayınıza sunulur.

## 11. CLAUDE.md değişikliği (onayınız gerekir, CLAUDE.md §8 madde 6)

Plan onayıyla birlikte onaylanır. Kural 12, §3, §7 ve §5'in ilk kısmı 1. adımın commit'inde
yazılır; §5'in rol ve yetki değiştirme cümlesi, ekranı geldiği için 9. adımın commit'inde yazılır.
Kural 12'ye 1. adımda bir geçiş cümlesi eklenir ve 8. adımın commit'inde silinir: "Geçiş sürerken
(docs/plan/kisi-yetkileri.md, 2-8. adımlar) henüz geçmemiş modüller rol denetimini (`HasRole`,
`hasAnyRole`) korur; yeni ve geçen kod `HasAccess`, `require_access` ve `can()` kullanır." Metinler:

- **§4 kural 12:** "12. **Yetki her uç noktada kontrol edilir.** Yetkiler modül bölümü ve düzey
  (görür / değiştirir / onaylar) bazındadır. Bölümler ve rollerin varsayılan yetki paketleri her
  modülün `access.py` dosyasındadır; kullanıcının geçerli yetkisi rol paketleri ile kişiye özel
  eklenen ya da kaldırılan yetkilerden hesaplanır (`core.permissions`). API'de `HasAccess`,
  serviste `require_access` kullanılır; arayüz aynı kuralı `can()` ile gösterir, frontend'in butonu
  gizlemesi yetki sayılmaz. Onay ve karar adımları ayrı **onaylar** yetkisidir; değiştirir
  onaylamayı kapsamaz. Admin rolü ve superuser her yetkiye sahiptir."
- **§5 Roller**, "Görevler role ya da kişiye atanabilir." cümlesinin yerine (1. adım; öteki
  cümleler kalır): "Rol iki işe yarar: varsayılan yetki paketidir ve görev/bildirim adresidir. Rol paketleri kodda tutulur, yalnızca yeni sürümle ve DECISIONS
  kaydıyla değişir. Personel, bordro, personel maliyeti, olaylar ve kazalar ve denetim günlüğü
  yetkileri yalnızca yönetim rolündeki kullanıcılara verilebilir (KVKK). Görevler role ya da
  kişiye atanabilir; rolün üyelerinden görevin gerektirdiği yetkisi olmayanlar görevi ve
  bildirimini almaz."
  9. adımda eklenir: "Var olan kullanıcının rolleri ve kişiye özel yetkileri yalnızca admin
  tarafından, gerekçe yazılarak **Sistem > Kullanıcılar > Yetkiler** ekranında değiştirilir;
  geçmişi silinmez. Yeni kullanıcının ilk rolleri açılış penceresinde verilir."
- **§3:** katman listesine `access.py  # Yetki bölümleri ve rol varsayılan paketleri (yalnız veri)`
  eklenir; `core` satırı "Kullanıcı, rol, yetki kataloğu ve kişiye özel yetkiler, BaseModel, …"
  olur.
- **§7:** "Yetki sözleşme testi (`apps/core/tests/access_contract/`) her adımda yeşil olur:
  kişiye özel yetki yokken her uç nokta × rol kararı dondurulmuş anlık görüntüyle aynıdır. Bilinçli
  bir değişiklik sahibin onayı ve DECISIONS kaydıyla anlık görüntüye işlenir." Yol 1. adımda
  düzeltildi: test tek dosya değil, bir klasördür.

## 12. Sonra sorulacaklar (ilgili adımdan önce)

- **Bordrosu olmayan ayın işçilik oranı notu** (5. adımdan önce; §8 madde 8). Personel
  maliyetinden açılan gider oranının notunda tutar yerine bordro numarası yazar; canlı
  başlangıcından önceki aylarda onaylı bordro olmadığından numara yoktur. Not o zaman ne yazsın
  (ör. yalnız "Personel maliyetinden")?
- **İrsaliyedeki şoför kimlik numarası** (10. adımdan önce): irsaliye PDF'inde tam numarayı
  kimlerin göreceği KVKK.md ile birlikte netleşir; belge mi düzeltilsin, ayrı bir hak mı olsun?
  Bugünkü durum size ayrıca sunulur.
- **İki bildirimin hedefi** (7. adımdan önce). Alıcıları hedef sayfayı bugün açamıyor:
  - tartım sapması: laboratuvara gider, şarj sayfasına götürür;
  - ara kontrol reddi: üretim ve planlamaya gider, numune sayfasına götürür.

  İlgili rollere hedefte Görür mü verilsin, bildirimler lot sayfasına mı bağlansın? Karar
  verilene kadar bildirimler bugünkü gibi gider; bağlantı bu alıcılara gösterilmez.
- **Ortak tablet ya da hat hesabı** (Paket B canlıya alınmadan önce; GECIS-PLANI'nda açık).
  Kişiye özel yetki ve ISO kaydı herkesin kişisel hesabı olduğunu varsayar.
- **Faz B ayrıntıları** (Paket C'den önce). Lot sayfasından mal kabule ulaşma; müşteri ve
  tedarikçi iletişim bilgileri.

## 13. Kapsam dışı

- Rol paketlerini ekrandan değiştirme (karar 8).
- Satış fiyatlarını kişiden gizleme (karar 6).
- Süreli yetki (vekâlet bitiş tarihi); model ileride bitiş tarihi alabilir.
- Yetki yönetimini yönetime ya da başka birine devretme.
- Kayıt düzeyinde görev ayrılığı zorunluluğu (kaydeden ≠ karar veren); şimdilik uyarı ve rapor.
- Geçmiş bir tarihteki yetkileri gösteren ekran (veri tutulur, ekran sonra).
- Rolü olmayan kişiye görev yönlendirme.
