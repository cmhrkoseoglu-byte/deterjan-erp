# Planlama

Planlama; ana verileri ve reçeteleri tutar, üretim ve dolum emirlerini açıp onaylar, eksikleri ve yeniden işleme kararlarını takip eder.

## Üretim emri açma

1. **Üretim > Üretim emirleri** sekmesinde **Yeni üretim emri**'ne basın.
2. **Reçete**'yi seçin. Reçetenin onaylı sürümü kullanılır.
3. **Planlanan miktar**, **Birim**, **Planlanan tarih** ve **Karıştırma tankı**'nı girin. **Öncelik** varsayılan olarak Normal'dir.
4. **Taslağı kaydet**'e basın. Taslak emir henüz kimseye görev açmaz.
5. Emri kontrol edip **Onayla**'ya basın. Reçete planlanan miktara ölçeklenir ve depoya malzeme hazırlama görevi düşer.

![Yeni üretim emri](/kilavuz/planlama-emir-yeni.jpg)

> Tank kapasitesinden büyük emir, üretimde birden çok şarja bölünür. Emirde "Şarja dağıtılmamış" miktar görünür.

## Emri takip etme

Emir sayfası emrin durumunu baştan sona gösterir.

- **İhtiyaç listesi**: her malzemenin ihtiyacı, hazırlanan ve tüketilen miktarı.
- **Hazırlanan lotlar**: depo hangi lotu nereden nereye taşıdı.
- **Şarjlar**: üretimdeki ve biten şarjlar, çıktı lotları.
- Durum sırası: Taslak, Onaylandı, Malzeme hazırlanıyor, Malzeme hazır, Üretimde, Analiz bekliyor, Tamamlandı. Çıktı lotu laboratuvarca serbest bırakılınca emir kendiliğinden tamamlanır.
- Emri durdurmak için **Emri iptal et**'e basın ve nedeni yazın. Hazırlanmış malzeme geldiği yere geri döner.

![Üretim emri sayfası](/kilavuz/planlama-emir.jpg)

## Dolum emri açma

1. **Dolum > Dolum emirleri** sekmesinde **Yeni dolum emri**'ne basın.
2. **Mamul**, **Planlanan adet**, **Planlanan tarih**, **Dolum hattı** ve **Mamul deposu**'nu girin.
3. **Taslağı kaydet**, sonra **Onayla**'ya basın. Ambalaj ihtiyacı fire payıyla hesaplanır ve depoya ambalaj hazırlama görevi düşer.

![Dolum emri sayfası](/kilavuz/planlama-dolum-emri.jpg)

> Dolum emri için mamulün onaylı ambalaj reçetesi olmalıdır. Ambalaj reçeteleri **Dolum > Ambalaj reçeteleri** sekmesindedir.

## Reçete ve ana veriler

1. **Reçeteler** menüsünde reçeteyi açın. Onaylı sürüm değiştirilemez.
2. Değişiklik için onaylı sürümde **Kopyala (yeni taslak)**'a basın ve neyin değişeceğini yazın.
3. Taslakta satırları düzenleyin. **Karşılaştır** ile eski sürümle farkı, **Ölçekle** ile hedef miktara göre ihtiyacı görün.
4. **Onayla**'ya basın. Yeni sürüm geçerli olur, eski sürüm "Geçersiz" olur.
5. Malzeme, tedarikçi, müşteri, lokasyon ve ekipman **Ana veriler** menüsündedir. Çok sayıda kaydı **Excel'den içe aktar** ile yükleyebilirsiniz; kod sütununu boş bırakırsanız sistem sıradaki kodu verir.
6. Yeni kayıtta kod önerilir (sistem yöneticisi o türün biçimini etkinleştirdiyse). Kodu değiştirebilirsiniz ama biçime uymalıdır. Kayıt açıldıktan sonra kodu yalnızca sistem yöneticisi değiştirir; eski kod aramada ve okutmada tanınır.
7. Tedarikçi ve müşteri kartında **Ülke** listeden seçilir; yeni kayıtta Türkiye gelir.

> Kullanılmış kayıt silinmez. Artık kullanılmayan malzemeyi pasife alın.

## GTIN ve koli GTIN'i

- **Mamul GTIN'i**: malzeme kartında **Tür** Mamul ise **GTIN öner** düğmesi sıradaki boş GTIN'i yazar (sistem yöneticisi GS1 ayarlarını girdiyse). GTIN'i elle de girebilirsiniz; kontrol hanesi denetlenir, aynı GTIN iki kayıtta olamaz.
- Lotu olan mamulün GTIN'i değiştirilemez: basılmış koli ve palet etiketleri bu GTIN'i taşır. Hammadde, ambalaj ve yarı mamulde tedarikçinin GTIN'i lot olsa da düzeltilebilir.
- **Koli GTIN'i**: **Birim dönüşümleri** sekmesinde mamulün KOLI dönüşümüne girilir; **Koli GTIN'i öner** ürün GTIN'inden türetir. Koli ve palet etiketine koli GTIN'i basılır, koli okutulunca bir koli miktarı gelir. Koli GTIN'i yoksa etikete ürün GTIN'i basılır.
- **Koli içi adet değişirse** (ör. 12'li koli 24'lü olursa) KOLI dönüşümünde **Temel birim karşılığı**'na yeni adedi yazın: **Koli GTIN'i** alanı açılır, boşalır ve zorunlu olur. Yeni koli GTIN'ini yazın ya da **Koli GTIN'i öner**'e basın, sonra **Kaydet**'e basın. Eski GTIN eski adediyle arşivlenir ve bir daha verilmez; alanın altındaki **Eski koli GTIN'leri** listesinde görünür. Depodaki eski koliler okutulunca eski adet önerilir; eski lotların etiketi yeniden basılırsa o lotun yapıldığı günkü koli GTIN'i basılır, irsaliyede de koli sayısı o günkü adetle hesaplanır.
- Lotu olan malzemenin türü Mamul'den başka türe ya da başka türden Mamul'e değiştirilemez. Yanlış türde açılmış kart için yeni kart açın.

## Size düşen görevler

- **Satış siparişinde eksik**: Onaylanan siparişin stoğu yetmiyorsa görev gelir. Üretim ya da dolum emri açın.
- **Yeniden işleme**: Laboratuvar bir bulk lot için yeniden işleme kararı verirse görev gelir. **Kayda git** ile bloke lotun sayfasını açın, **Kalite kontrol** bölümündeki **Yeniden işleme emri aç**'a basın. Reçete ya da düzeltme listesi girip emri onaylayın.
- **Satın alma talebi**: Malzeme gerekiyorsa **Satın alma > Talepler** sekmesinde **Yeni talep** açın. Satın alma birimi siparişe çevirir.

## Panolar

**Panolar ve raporlar > Panolar** üretim, depo ve sevkiyatın günlük durumunu gösterir. **Raporlar** sekmesinden Excel ya da PDF alabilirsiniz.

![Panolar](/kilavuz/planlama-raporlar.jpg)
