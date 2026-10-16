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
5. Malzeme, tedarikçi, müşteri, lokasyon ve ekipman **Ana veriler** menüsündedir. Çok sayıda kaydı **Excel'den içe aktar** ile yükleyebilirsiniz.

> Kullanılmış kayıt silinmez. Artık kullanılmayan malzemeyi pasife alın.

## Size düşen görevler

- **Satış siparişinde eksik**: Onaylanan siparişin stoğu yetmiyorsa görev gelir. Üretim ya da dolum emri açın.
- **Yeniden işleme**: Laboratuvar bir bulk lot için yeniden işleme kararı verirse görev gelir. **Kayda git** ile bloke lotun sayfasını açın, **Kalite kontrol** bölümündeki **Yeniden işleme emri aç**'a basın. Reçete ya da düzeltme listesi girip emri onaylayın.
- **Satın alma talebi**: Malzeme gerekiyorsa **Satın alma > Talepler** sekmesinde **Yeni talep** açın. Satın alma birimi siparişe çevirir.

## Panolar

**Panolar ve raporlar > Panolar** üretim, depo ve sevkiyatın günlük durumunu gösterir. **Raporlar** sekmesinden Excel ya da PDF alabilirsiniz.

![Panolar](/kilavuz/planlama-raporlar.jpg)
