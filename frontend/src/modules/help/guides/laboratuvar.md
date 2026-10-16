# Laboratuvar

Laboratuvar; gelen hammaddeyi, üretilen bulk ürünü, dolan mamulü ve iadeleri analiz eder. Lotu serbest bırakma ya da reddetme kararı yalnızca laboratuvarın numune kararıyla verilir.

## Numune kuyruğu

Numuneler kendiliğinden açılır: mal kabul kaydedilince **Giriş kontrolü**, şarj bitince **Numune analizi**, dolum partisi bitince mamul kontrolü, iade teslim alınınca iade numunesi. Her biri **Görevlerim**'e görev olarak da düşer.

1. **Kalite kontrol > Numune kuyruğu** sekmesini açın. En uzun bekleyen numuneler üsttedir.
2. Numunenin satırına tıklayın. Numune sayfası açılır.

![Numune kuyruğu](/kilavuz/lab-kuyruk.jpg)

> Elle numune açmak için lot sayfasındaki **Kalite kontrol** bölümünde **Numune aç**'a basın.

## Sonuç girme

1. **Test sonuçları** tablosunda her test için sınırlar görünür. Üstte eksik zorunlu testler yazılıdır.
2. Ölçtüğünüz değeri yazın, isterseniz **Cihaz** alanını doldurun ve satırdaki **Kaydet**'e basın.
3. Uygun / uygun değil testlerinde doğru seçeneği işaretleyip kaydedin.
4. Sınır dışı değer yazarken alan kırmızıya döner. Kaydedilen sonuç "Spesifikasyon dışı" işaretlenir.
5. Yanlış girdiğiniz sonucu yeniden girip kaydedin. Eski değer geçmişte kalır, silinmez.
6. Analiz raporunu ya da cihaz çıktısını **Ekler** bölümüne yükleyin.

![Numune sayfası](/kilavuz/lab-numune.jpg)

## Karar verme

Karar seçenekleri:

- **Serbest bırak**: lot serbest olur, stok seçilen lokasyona taşınır.
- **Şartlı kabul**: sonuç sınır dışı ama kullanılabilir. **Gerekçe** zorunludur. Yönetim onaylayınca lot serbest olur.
- **Yeniden işleme** (yalnızca bulk ve iade): lot bloke olur, planlamaya yeniden işleme görevi düşer.
- **Ret**: lot reddedilir ve karantinada kalır. Geri alınamaz.

1. Zorunlu testlerin hepsi girilince üstteki **Karar ver**'e basın.
2. Kararı seçin. Gerekiyorsa **Gerekçe** yazın; şartlı kabulde zorunludur.
3. Serbest bırakmada **Serbest bırakılan stokun lokasyonu** varsayılan gelir; gerekirse değiştirin.
4. Penceredeki **Karar ver**'e basın. Görev kendiliğinden kapanır, ilgili birimlere bildirim gider.
5. Karar sonrası **Analiz sertifikası (PDF)** ile müşteri için analiz sertifikasını indirin.

![Karar penceresi](/kilavuz/lab-karar.jpg)

> Sınır dışı sonuç varken **Serbest bırak** seçilemez. Zorunlu test eksikken karar verilemez.

## Lotu bloke etme

Serbest bir lotta sorun fark ederseniz lot sayfasında **Bloke et**'e basın ve nedeni yazın. Bloke lot üretime ve sevkiyata verilemez; siparişlerdeki rezervasyonu bırakılır.

## Spesifikasyonlar

**Kalite kontrol > Spesifikasyonlar** sekmesinde her malzemenin ve aşamanın test sınırları vardır. Onaylı spesifikasyon değiştirilemez; kopyalayıp yeni sürüm açın, sınırları düzenleyin ve onaylayın. Test tanımları **Test tanımları** sekmesindedir.

## İzlenebilirlik ve geri çağırma

**İzlenebilirlik** menüsünde üç sekme vardır:

- **Geri izleme**: bir mamul ya da bulk lotun hangi hammadde lotlarından yapıldığını, tedarikçiyi ve mal kabulü gösterir.
- **İleri izleme**: bir hammadde lotunun hangi şarj ve dolum lotlarında kullanıldığını, stokta kalanı ve sevk edileni gösterir.
- **Geri çağırma simülasyonu**: bir ya da birkaç lot seçip **Simüle et**'e basın. Etkilenen lotlar, sevkiyatlar ve müşteriler listelenir. **Excel** ya da **PDF** olarak alın.

1. **Lot** alanına lot no ya da malzeme kodunun ilk harflerini yazın.
2. Listeden lotu seçin. Ağaç açılır; lot numarasına tıklayınca lot sayfasına gidersiniz.

![İleri izleme](/kilavuz/lab-izlenebilirlik.jpg)

## Terazi kalibrasyonu

**Bakım > Kalibrasyon** sekmesinde teraziler ve kalibrasyon planları vardır. Süresi geçen terazi tartımda seçilemez, süresi yaklaşan terazide üretim sarı uyarı görür. Kalibrasyon bir bakım iş emriyle yapılır; iş emrinde **Kalibrasyon sonucu**'nu girip kapatınca terazi yeniden kullanılabilir olur.
