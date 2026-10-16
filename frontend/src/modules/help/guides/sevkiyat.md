# Sevkiyat

Sevkiyat; müşteri siparişini girer ve onaylar, sevkiyatı (araç ve şoför) planlar, depo yükledikten sonra sevki onaylayıp irsaliyeyi basar ve müşteri iadelerini açar.

## Satış siparişi girme

1. **Sevkiyat > Satış siparişleri** sekmesinde **Yeni sipariş**'e basın.
2. **Müşteri**, **Sipariş tarihi**, **İstenen teslim** ve **Müşteri sipariş no**'yu girin. **Teslim adresi** boş kalırsa müşterinin adresi alınır.
3. Her ürün için satır doldurun: **Mamul**, **Miktar**, **Birim** (adet, koli ya da palet). **Birim fiyat** isteğe bağlıdır; fatura muhasebe programında kesilir.
4. Başka ürün için **Satır ekle**'ye basın. Bitince **Taslağı kaydet**.
5. Siparişi kontrol edip **Onayla ve rezerve et**'e basın. Stok SKT'si en yakın lottan başlayarak siparişe ayrılır.

![Yeni satış siparişi](/kilavuz/sevkiyat-siparis-yeni.jpg)

> Onaylanan siparişin satırları değiştirilemez. Vazgeçilen sipariş **Siparişi iptal et** ile iptal edilir; rezervasyonlar bırakılır.

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

> Şoförün TC kimlik no ekranda maskeli görünür; tam numara yalnızca irsaliyede yazılır.

## Sevk onayı ve irsaliye

Depo lotları okutup **Yükleme tamam** deyince size "sevk onayı" görevi gelir.

1. Görevde **Kayda git**'e basın ya da **Sevkiyatlar** sekmesinden sevkiyatı açın.
2. **Okutulan lotlar** tablosunu ve araç bilgisini kontrol edin.
3. **Sevki onayla**'ya basın. Stoktan çıkış yapılır, sipariş durumu güncellenir. Bu adım geri alınamaz.
4. **İrsaliye (PDF)** ile irsaliyeyi indirip basın ve şoföre verin.

![Sevk edilmiş sevkiyat](/kilavuz/sevkiyat-sevkiyat.jpg)

> Yükleme öncesi vazgeçilen sevkiyat **Sevkiyatı iptal et** ile iptal edilir; okutulan lotlar yerine döner.

## Müşteriler

**Müşteriler** sekmesinde müşteri kartı açılır: sipariş geçmişi ve müşteriye sevk edilen lotlar. Müşteri bilgileri, adres ve asgari kalan raf ömrü **Ana veriler** ekranından planlama ya da yönetim tarafından düzenlenir.

## Müşteri iadesi

1. **İadeler** menüsünde **Yeni iade**'ye basın.
2. **Müşteri**, **İade tarihi** ve **İade nedeni**'ni girin. Biliyorsanız **Sevkiyat**'ı seçin; iade sevk edilenden fazla olamaz.
3. Satırlara **Ürün**, **Lot** ve **Miktar** girin. **Taslağı kaydet**.
4. Mal fabrikaya gelince **Teslim al**'a basın (depo da yapabilir). Lot karantinaya girer, laboratuvara iade numunesi açılır.
5. Laboratuvar kararına göre mal yeniden sevke açılır, yeniden işlenir ya da depo tarafından imha edilir.
