# Sevkiyat

Sevkiyat; müşteri siparişini girer ve onaylar, sevkiyatı (araç ve şoför) planlar, depo yükledikten sonra sevki onaylayıp irsaliyeyi basar ve müşteri iadelerini açar.

## Satış siparişi girme

1. **Sevkiyat > Satış siparişleri** sekmesinde **Yeni sipariş**'e basın.
2. **Müşteri**, **Sipariş tarihi**, **İstenen teslim** ve **Müşteri sipariş no**'yu girin. **Teslim adresi** boş kalırsa müşterinin adresi alınır.
3. Her ürün için satır doldurun: **Mamul**, **Miktar**, **Birim** (adet, koli ya da palet). **Birim fiyat** isteğe bağlıdır; fatura muhasebe programında kesilir.
4. Başka ürün için **Satır ekle**'ye basın. Bitince **Taslağı kaydet**.
5. Siparişi kontrol edip **Onayla ve rezerve et**'e basın. Açılan pencerede **Termin**'i (müşteriye sözü verilen teslim tarihi) girin; termin zorunludur ve geçmiş tarih olamaz. Stok SKT'si en yakın lottan başlayarak siparişe ayrılır.

![Yeni satış siparişi](/kilavuz/sevkiyat-siparis-yeni.jpg)

> Onaylanan siparişin satırları değiştirilemez. Vazgeçilen sipariş **Siparişi iptal et** ile iptal edilir; rezervasyonlar bırakılır.

> Termin kayarsa sipariş sayfasında **Termini değiştir**'e basın, yeni tarihi ve gerekçeyi yazın. Gerekçe sipariş geçmişine yazılır. Termin onaylı ve kısmen sevk edilmiş siparişte değişir; sevk edilen, kapanan ya da iptal edilen siparişte değişmez.

## Rezervasyon ve eksik

Sipariş sayfasında her satırın **Rezerve**, **Sevkiyatta**, **Sevk edilen** ve **Eksik** miktarı görünür.

- Stok yetmezse satırda eksik görünür ve planlamaya görev düşer.
- Yeni mamul serbest kalınca **Eksikleri rezerve et**'e basın.
- Belirli bir lotu müşteriye ayırmak için satırda **Lot seç**'i, bir rezervasyonu geri almak için **Bırak**'ı kullanın.
- Müşteri en az kalan raf ömrü istiyorsa (müşteri kartında) bu şartı karşılamayan lot ayrılmaz.
- Eksikli siparişleri görmek için listede **Yalnızca eksikli**'yi açın.

![Satış siparişi sayfası](/kilavuz/sevkiyat-siparis.jpg)

## Sevkiyat planlama

1. Onaylı siparişin sayfasında **Sevkiyat planla**'ya basın.
2. **Planlanan tarih**, **Plaka**, **Şoför**, **Şoför TC kimlik no** ve **Taşıyıcı** bilgisini girin.
3. Her satırın **Bu sevkiyatta** miktarı kalan miktarla gelir. Araca sığmayan kısmı azaltın; kalan sonraki sevkiyata kalır.
4. **Planla**'ya basın. Depoya toplama görevi düşer.

> Şoförün TC kimlik no ekranlarda maskeli görünür; tam numara yalnızca irsaliye PDF'inde yazılır. PDF'i **Sevkiyatlar ve irsaliye: Görür** yetkisi olanlar açar (varsayılan: sevkiyat, yönetim, planlama ve depo; sistem yöneticisi her zaman). Numara girilmiş sevkiyatta irsaliyenin her açılışı kayda geçer.

## Sevk onayı ve irsaliye

Depo lotları okutup **Yükleme tamam** deyince size "sevk onayı" görevi gelir.

1. Görevde **Kayda git**'e basın ya da **Sevkiyatlar** sekmesinden sevkiyatı açın.
2. **Okutulan lotlar** tablosunu ve araç bilgisini kontrol edin.
3. **Sevki onayla**'ya basın. Stoktan çıkış yapılır, sipariş durumu güncellenir. Bu adım geri alınamaz.
4. **İrsaliye (PDF)** ile irsaliyeyi indirip basın ve şoföre verin.

![Sevk edilmiş sevkiyat](/kilavuz/sevkiyat-sevkiyat.jpg)

> Yükleme öncesi vazgeçilen sevkiyat **Sevkiyatı iptal et** ile iptal edilir; okutulan lotlar yerine döner.

> İrsaliyedeki koli sayısı lotun açıldığı (dolumun başladığı) günkü koli içi adetle hesaplanır. Koli düzeni sonradan değişse de (koli içi adet, koli GTIN'i, koli dönüşümünün pasife alınması) sevk edilmiş irsaliyenin yeniden basımı değişmez. Koli dönüşümü olmadan ya da dönüşüm pasifken açılmış lotun satırında koli sayısı boş kalır.

## Müşteriler

**Müşteriler** sekmesinde müşteri kartı açılır: açık siparişler (Sipariş takibi'ndeki gibi), sipariş geçmişi ve müşteriye sevk edilen lotlar. Müşteri bilgileri, adres ve asgari kalan raf ömrü **Ana veriler** ekranından planlama ya da yönetim tarafından düzenlenir.

## Sipariş takibi

**Sevkiyat > Sipariş takibi** sekmesi açık siparişleri vadesine göre gösterir. Vade siparişin terminidir; termin yoksa istenen teslim tarihidir.

1. Üstteki listede açık siparişi olan müşteriler, açık, geciken ve 7 gün içinde vadesi gelen sipariş sayısıyla görünür. Gecikeni çok olan müşteri üsttedir. **Yalnız gecikenler** ile süzün ya da müşteri arayın.
2. Müşteriye tıklayınca siparişleri altta açılır: sipariş no, vade, durum, sevk edilen / sipariş miktarı ve tutar. Geciken sipariş kırmızı satırda, **N gün gecikti** rozetiyle görünür.
3. **Satırları göster** ile ürün başına sipariş edilen, sevk edilen, sevke planlanan ve kalan miktarı, sevkiyat numaralarını görün.
4. **Yalnız gecikenler**, **Bu hafta vadesi gelenler** (gecikenler dahil) ve **Biten siparişleri de göster** (son 90 günde sevk edilen, kapanan ya da onaydan sonra iptal edilen) süzgeçlerini kullanın. Biten siparişte gecikme son sevk gününe göredir.

Seçilen müşterinin cari bakiyesi ve vadesi geçen tutarı yalnız **Müşteri carileri: Görür** ve **Fiyatları görür** yetkisi birlikte olana görünür; **Cari ekstresi** bağlantısı cariyi açar.

> Her sabah, vadesi önceki gün ya da daha önce dolmuş açık siparişler için size **Teslimi geciken siparişler** bildirimi gelir (sevkiyat ve yönetim). Her sipariş bir kez bildirilir; termin değiştirilip yeni tarih de geçerse yeniden bildirilir.

## Portal talepleri

Portal hesabı olan müşteriler **sipariş talebi** gönderebilir. Talep sipariş değildir; size **Portal talebi incele** görevi gelir.

1. **Sevkiyat > Portal talepleri** sekmesinde karar bekleyen talepleri görürsünüz; talebe tıklayın.
2. Ürünleri, miktarları, istenen teslim tarihini ve müşterinin notunu kontrol edin.
3. **Siparişe çevir**: taslak satış siparişi açılır ve sipariş sayfasına gidilir. Fiyatı ve termini girip siparişi bugünkü gibi onaylayın. Sipariş onaylanınca müşteri portalda görür.
4. **Reddet**: gerekçeyi yazın (müşteri portalda görür).

> Müşteri karar verilmemiş talebini geri çekebilir; görev kendiliğinden kapanır. Karar vermek **Satış siparişleri: Değiştirir** ister; yalnız Görür'ü olan talepleri okur.

## Müşteri carileri

**Cari hesaplar > Müşteriler** sekmesinde müşterilerin hareketlerini ve ekstresini görürsünüz. Tutarlar, PDF ekstre ile birlikte, yalnız **Fiyatları görür** yetkisi olanlara görünür (varsayılan: yönetim ve satın alma; sevkiyatta yoktur). Tahsilat ve dekont girmek **Müşteri carileri: Değiştirir** ister (varsayılan: yönetim).

## Müşteri iadesi

1. **İadeler** menüsünde **Yeni iade**'ye basın.
2. **Müşteri**, **İade tarihi** ve **İade nedeni**'ni girin. Biliyorsanız **Sevkiyat**'ı seçin; iade sevk edilenden fazla olamaz.
3. Satırlara **Ürün**, **Lot** ve **Miktar** girin. **Taslağı kaydet**.
4. Mal fabrikaya gelince **Teslim al**'a basın (depo da yapabilir). Lot karantinaya girer, laboratuvara iade numunesi açılır.
5. Laboratuvar kararına göre mal yeniden sevke açılır, yeniden işlenir ya da depo tarafından imha edilir.
