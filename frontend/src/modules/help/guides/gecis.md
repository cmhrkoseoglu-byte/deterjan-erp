# Canlıya geçiş ve sayım günü

Excel'den sisteme tek seferde geçilir. Sayım gününde depo sayılır, sayım sonucu açılış stoku olarak yüklenir ve ertesi iş gününden itibaren mal kabul, üretim, dolum ve sevkiyat sistemden yapılır. İlk 2 ile 4 hafta Excel de tutulur ve her hafta iki taraf karşılaştırılır.

Hazırlığın nerede olduğunu **Canlıya geçiş > Hazırlık** ekranı gösterir. Kırmızı madde kalmadan sayım gününe geçmeyin; sarı maddeler başlamayı engellemez ama ilgili iş yapılamaz (ör. onaylı reçetesi olmayan ürün üretilemez).

![Canlıya geçiş: hazırlık listesi](/kilavuz/gecis-hazirlik.jpg)

## 1. Sayımdan önce (en az bir hafta önce)

1. **Kullanıcılar:** Sistem yöneticisi her çalışana kullanıcı açar ve rolünü verir (**Sistem > Kullanıcılar**; geçici şifreyi çalışana kendisi iletir). Tabletler için hat ya da vardiya kullanıcısı açılabilir.
2. **Ana veriler:** Planlama, Excel'deki listeleri şu sırayla yükler. Her ekranda **Excel'den içe aktar** düğmesi vardır; önce **Şablonu indir**, sonra dosyayı seçip **Önizle**, hata yoksa **Aktar**.
   - Malzemeler (Ana veriler > Malzemeler). Kategoriler varsa önce elle girilir.
   - Birim dönüşümleri (1 KOLI = 12 ADET gibi).
   - Tedarikçiler ve müşteriler.
   - Depolar, sonra lokasyonlar, sonra ekipmanlar (tank, dolum hattı, terazi). Tankın lokasyonu önce açılmış olmalı.
   - Reçeteler (Reçeteler > Excel'den içe aktar). Her reçete taslak sürüm olarak gelir; laboratuvar kontrol edip onaylar. Proses adımları reçete ekranından elle girilir.
3. **Kodlar:** Malzeme, tedarikçi ve müşteri kodları muhasebe programındaki kodlarla aynı olmalı. Kartlar bundan sonra bu sistemde açılır ve muhasebeye buradan aktarılır.
4. **Kalite ve dolum:** Laboratuvar spesifikasyonları, planlama ambalaj reçetelerini tamamlar.
5. **Cihazlar:** Etiket yazıcıları (Ana veriler > Yazıcılar) ve terazilerin kalibrasyon kayıtları (Bakım > Kalibrasyon) girilir. Yazıcıdan **deneme etiketi** basılır.
6. **Prova:** Mümkünse test ortamında sayım listesinin bir bölümüyle açılış stoku yüklemesi denenir.

> Aynı dosyayı tekrar yüklemek güvenlidir: kodu sistemde olan satır kaydı günceller, olmayan yeni kayıt açar. Hatalı satır varsa hiçbir satır yazılmaz.

## 2. Sayım günü

1. **İşlemleri durdurun.** Belirlenen saatte mal kabul, üretime çıkış, dolum ve sevkiyat durur. Bu saatten sonra gelen mal ertesi güne kadar sayılmadan bir kenarda bekler.
2. **Sayın.** Ekipler lokasyon lokasyon sayar. Her satıra malzeme kodu, lot no, lokasyon kodu, miktar ve varsa SKT yazılır. Lot no'su olmayan eski stok için ACILIS-LAS gibi bir lot no verilir.
3. **Sayım listesini hazırlayın.** Depo, **Depo ve stok > Stok sorgu > Açılış stoku içe aktar** ekranından şablonu indirir ve sayım sonucunu şablona geçirir. Laboratuvar onayı beklenen lotlar için **Durum** sütununa Karantina yazılır; diğerleri Serbest olur.
4. **Yükleyin.** Aynı ekranda dosyayı seçip **Önizle**. Hata listesindeki satırları düzeltip tekrar önizleyin. Hata kalmayınca **Aktar**.
5. **Kontrol edin.** Sayım listesini **Canlıya geçiş > Stok karşılaştırma > Yeni karşılaştırma** ile yükleyin. Sonuç "Fark yok" olmalı. Fark varsa yükleme ya da liste düzeltilir.
6. **Etiketleyin.** Rafta etiketi olmayan lotlar için lot sayfasındaki **Etiket yazdır** ile lot etiketi basılıp yapıştırılır.
7. **Canlı tarihini girin.** Yönetim, **Canlıya geçiş > Hazırlık > Canlı başlangıç tarihi** alanına ertesi iş gününü yazıp **Kaydet**'e basar. O günden itibaren açılış stoku yüklenemez; sonradan çıkan farklar **Sayım düzeltme** ile, gerekçesiyle girilir.

![Açılış stoku önizlemesi: hatalı satırlar kırmızı yazılır, hata kalmayınca Aktar açılır](/kilavuz/gecis-acilis.jpg)

## 3. İlk gün

- Mal kabul, üretim emri, tartım, dolum, sevkiyat ve iade sistemden yapılır. Kimin ne yapacağı rol kılavuzlarındadır.
- Görevler **Görevlerim** ekranına düşer; işi yapan görevi tamamlar.
- Takılan, hata veren ya da anlaşılmayan her şey için sağ üstteki **Sorun bildir** kullanılır. Bildirim ekran görüntüsüyle sistem yöneticisine görev olarak gider.

## 4. Paralel çalışma (ilk 2 ile 4 hafta)

1. Excel kayıtları eskisi gibi tutulmaya devam eder.
2. Her hafta aynı gün (ör. cuma akşamı) depo, Excel'deki stok listesini **Canlıya geçiş > Stok karşılaştırma > Yeni karşılaştırma** ile yükler. **Stok tarihi** listenin hazırlandığı gündür; sistem o günün sonundaki stokla karşılaştırır.
3. Lot no ve lokasyon listenin her satırında doluysa karşılaştırma lot ve lokasyon bazında, değilse malzeme toplamı bazında yapılır.
4. Farklı satırlar kırmızı görünür ve **Excel'e aktar** ile dosya alınır. Her farkın sebebi bulunur:
   - Sisteme girilmemiş bir hareket varsa ilgili belge (mal kabul, üretim, sevkiyat) girilir.
   - Excel'deki hata ise Excel düzeltilir.
   - Gerçek sayım farkıysa depo **Sayım düzeltme** açar.
5. Önerilen bitiş: iki hafta üst üste açıklanmamış fark kalmazsa yönetim Excel'i bırakma kararını verir.

![Stok karşılaştırması sonucu](/kilavuz/gecis-karsilastirma.jpg)
