# Depo

Depo; gelen malı kabul eder, üretime ve dolum hattına malzeme hazırlar, sevkiyatı toplar ve stoğun doğru olmasından sorumludur. Hazırlama ve toplama ekranları tablette, el okuyucuyla kullanılmak için tasarlandı.

## Stok sorgu ve lot okutma

**Depo ve stok** menüsünde **Stok sorgu** sekmesi lot ve lokasyon bazında stoğu gösterir.

![Stok sorgu](/kilavuz/depo-stok.jpg)

1. Bir lotun her şeyini görmek için sağ üstteki **Lot okut** alanına lot etiketini okutun. Lot sayfası açılır.
2. Lot sayfasında durum (Karantina, Serbest, Bloke), lokasyondaki stok, kalite kontrol, soy ağacı ve hareketler görünür.
3. Lotu başka lokasyona taşımak için **Transfer**'e basın.
4. Etiketi yıpranmış ya da kaybolmuş lot için **Etiket yazdır** ile yeni etiket basın ve yapıştırın.

![Lot sayfası](/kilavuz/depo-lot.jpg)

> Yalnızca **Serbest** lotlar üretime, dolum hattına ve sevkiyata verilebilir. Karantinadaki lotu laboratuvar kararı serbest bırakır.

## Mal kabul

1. **Depo ve stok > Mal kabul** sekmesinde **Yeni mal kabul**'e basın. Satın alma siparişine bağlı gelen mal için **Siparişten mal kabul**'ü kullanın; satırlar siparişten gelir.
2. **Tedarikçi**, **Kabul tarihi** ve **İrsaliye no**'yu girin. Karantina ve depo lokasyonu genelde hazır gelir.
3. Her kalem için **Satır ekle**: **Malzeme**, **Miktar**, **Birim**, **Tedarikçi lot no** ve **SKT**.
4. **Taslağı kaydet**'e, kontrol edince **Kaydet ve stoka al**'a basın. Her satır için lot açılır.
5. **Lot etiketleri (PDF)** ile etiketleri basıp kaplara yapıştırın.
6. Tedarikçinin analiz sertifikasını ya da irsaliye fotoğrafını **Ekler** bölümüne yükleyin.

![Kaydedilmiş mal kabul](/kilavuz/depo-mal-kabul.jpg)

> Giriş kontrolü gereken malzeme karantinaya girer ve laboratuvara görev düşer. Kaydedilen mal kabul değiştirilemez; hata olursa sistem yöneticisine haber verin.

## Üretime malzeme hazırlama (tablet)

Planlama üretim emrini onaylayınca **Görevlerim**'e hazırlama görevi düşer.

1. **Üretim > Malzeme hazırlama** sekmesinde emre dokunun.
2. Üstteki kartlar her malzemenin kalan miktarını gösterir. Hazırlayacağınız kalemin kartına dokunun.
3. Rafta lotu bulun ve **Lot barkodu** alanına okutun. Önerilen lot ilk SKT'si dolacak olandır.
4. **Miktar** alanını kontrol edin ve büyük **Hazırla** düğmesine basın. Malzeme üretim lokasyonuna taşınır, kart yeşile döner.
5. Tüm kartlar **Hazır** olunca en alttaki **Malzeme hazır**'a basın. Üretime görev düşer.

![Malzeme hazırlama: kalan kalemler](/kilavuz/depo-hazirlama.jpg)

![Malzeme hazırlama: lot okutma](/kilavuz/depo-hazirlama-okut.jpg)

Dolum hattına ambalaj hazırlamak aynı şekildedir: **Dolum > Ambalaj hazırlama** sekmesinde emri açın, ambalaj lotlarını okutup **Hazırla**'ya, bitince **Ambalaj hazır**'a basın.

## Lot okutulamıyorsa

- Okuyucu okumuyorsa lot numarasını **Lot barkodu** alanına elle yazıp Enter'a basın.
- Ya da alttaki öneri tablosunda lotun satırına dokunun. Lot seçilir.
- Okutulan lot yanlış malzemeye aitse kırmızı uyarı çıkar ve uyarı sesi duyulur. Doğru lotu bulun.
- Karantinadaki, bloke ya da SKT'si geçmiş lot kabul edilmez. Laboratuvara sorun.
- Etiket okunmayacak kadar bozuksa lot sayfasından **Etiket yazdır** ile yenisini basın.

## Sevkiyat toplama (tablet)

Sevkiyat birimi sevkiyat planlayınca toplama görevi düşer.

1. **Sevkiyat > Toplama** sekmesinde sevkiyatın kartına dokunun. Toplama ekranı açılır.
2. Toplayacağınız satıra dokunun. Önce siparişe rezerve edilen lot, sonra SKT'si en yakın lot önerilir.
3. Paletin ya da kolinin etiketini **Lot okut** alanına okutun.
4. **Miktar** boş kalırsa satırın kalanı alınır. **Topla**'ya basın. Mal sevk alanına taşınır.
5. Rezerve olmayan bir lot okutursanız gerekçe sorulur. Uygun gerekçeyi seçip **Gerekçeyle topla**'ya basın.
6. Yanlış okuttuysanız okutulan lotlar listesinde **Geri al**'a basın.
7. Mal araca yüklenince **Yükleme tamam**'a basın. Sevkiyat birimine sevk onayı görevi düşer.

![Sevkiyat toplama](/kilavuz/depo-toplama.jpg)

> Müşterinin istediği raf ömrünü karşılamayan lot gri ve **Raf ömrü yetersiz** olarak görünür; seçilemez.

## Sayım düzeltme

1. **Depo ve stok > Sayım düzeltme** sekmesinde **Yeni sayım düzeltme**'ye basın.
2. **Sayım tarihi**'ni girin. Her fark için **Satır ekle**: **Lot**, **Lokasyon**, **Sayılan** miktar ve **Neden**.
3. **Taslağı kaydet**'e basın. Sistem miktarı ve fark hesaplanır.
4. Farkları kontrol edip **Kaydet ve stoka al**'a basın. Fark stoka yazılır.

## İadeler

Müşteriden dönen malı sevkiyat birimi **İadeler** ekranında açar. Mal gelince iade kaydında **Teslim al**'a basın; lot karantinaya girer, laboratuvara numune açılır. Laboratuvar ret verirse görevdeki iade satırında **İmha et** ile malı stoktan düşün.
