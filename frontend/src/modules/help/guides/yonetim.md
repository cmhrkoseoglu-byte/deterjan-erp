# Yönetim

Yönetim; panolardan fabrikanın durumunu izler, kendi onayını gerektiren kararları (şartlı kabul, limit üstü satın alma) verir, maliyet oranlarını tutar ve canlıya geçiş tarihini belirler.

## Yönetim panosu

Giriş yapınca **Yönetim panosu** açılır; menünün en üstündedir. Görevleriniz **Görevlerim**'dedir. Pano dakikada bir kendini yeniler; hemen güncellemek için **Yenile**'ye basın.

1. **Onayınızı bekleyenler**: şartlı kabul kararları, limit üstü satın alma siparişleri (TL toplamıyla) ve açık İSG olayları. Bekleyen varsa kartın çerçevesi mavi olur; **Kararları aç**, **Siparişleri aç** ya da **Olayları aç** ile listeye gidin.
2. **Dikkat gerektirenler**: önce **Kritik** satırlar (minimum stokun altındaki malzeme, son kullanma tarihi geçmiş lot, yaralanmalı İSG olayı), sonra **Uyarı** satırları (gecikmiş görev, istenen teslim tarihi geçmiş sipariş, duruştaki ekipman, zamanı geçmiş bakım planı, QC'de 24 saatten uzun bekleyen numune). Satıra basınca ilgili liste açılır. Sorun yoksa **Yolunda** yazar.
3. **Bugün**: dökme üretim, mamul adedi, sevk edilen sevkiyat ve QC bekleyen lotlar; altlarında bu haftanın toplamı ve geciken sipariş sayısı.
4. **Son 14 gün üretim**: günlük dökme üretim ya da mamul adedi; seriyi grafiğin üstündeki düğmeden seçin. Çubuğun üzerine gelince (tablette dokununca) günün değeri görünür. **Tablo** rakamları gün gün listeler.
5. Aşağıda stok değeri (malzeme türüne göre), son 7 günün fire oranı ve duruş süresi, birimlerin açık ve gecikmiş görevleri, açık emirler, kritik stok ve son kullanma tarihi yaklaşan lotlar yer alır.

![Yönetim panosu](/kilavuz/yonetim-pano.jpg)

## Panolar ve raporlar

1. **Panolar ve raporlar > Panolar** sekmesinde yönetim panosunun yanında birim panoları da vardır: **Depo**, **Laboratuvar**, **Üretim** ve **Sevkiyat** düğmelerine basın.
2. Güncel rakamlar için **Yenile**'ye basın.
3. **Raporlar** sekmesinde raporu seçin, süzgeçleri doldurun ve **Excel** ya da **PDF** alın.
4. Büyük raporlar arka planda hazırlanır. Hazır olunca bildirim gelir; dosyayı **İndirmeler** sekmesinden alın. Dosyalar 7 gün saklanır.

## Şartlı kabul onayı

Laboratuvar spesifikasyon dışı sonuçla **Şartlı kabul** verirse size görev düşer. Lot onayınıza kadar karantinada bekler.

1. Görevde **Kayda git**'e basın ya da **Kalite kontrol > Şartlı kabul onayı** sekmesini açın.
2. Satırda laboratuvarın **Gerekçe**'sini okuyun. Gerekirse numune numarasına tıklayıp sonuçlara bakın.
3. Kabul ediyorsanız **Onayla**'ya basın. Lot serbest bırakılır.
4. Kabul etmiyorsanız **Reddet**'e basın ve nedeni yazın. Numune laboratuvara geri döner.

![Şartlı kabul onayı](/kilavuz/yonetim-sartli-kabul.jpg)

## Satın alma onayı

Onay limitini aşan satın alma siparişi size görev olarak gelir.

1. Görevde **Kayda git**'e basın. Sipariş **Yönetim onayında** durumundadır.
2. Tedarikçiyi, satırları, fiyatı ve toplamı kontrol edin.
3. Uygunsa **Onayla**'ya basın. Satın alma siparişi tedarikçiye gönderir.
4. Düzeltme gerekiyorsa **Taslağa geri gönder**'e basın ve notunuzu yazın.

![Onay bekleyen satın alma siparişi](/kilavuz/yonetim-siparis-onay.jpg)

> Onay limiti ve fazla teslim toleransı **Satın alma > Ayarlar** sekmesindedir. Limit boş bırakılırsa her sipariş yönetim onayına gelir.

## Maliyet

**Maliyet** menüsünü yalnızca yönetim görür.

- **Lot maliyetleri**: her lotun toplam ve birim maliyeti. Lota tıklayınca malzeme, genel gider ve fire kalemleri görünür. Fiyat sonradan değiştiyse lotun maliyet sayfasında **Yeniden hesapla**'ya basın ve **Sürüm notu** yazın; yeni sürüm hesaplanır.
- **Raporlar**: şarj maliyeti, fire ve stok değeri raporları (Excel).
- **Gider oranları**: üretim (bulk) ve dolum (mamul) için kg başına enerji, işçilik ve amortisman oranı. Oran değişince **Oran ekle** ile yeni geçerlilik tarihiyle girin; eski oranı değiştirmeyin.
- **Standart maliyetler**: fiyatı ve son alış maliyeti bilinmeyen lotlar için TL / temel birim tahmini maliyet. **Standart maliyet ekle** ile girin.

![Gider oranları](/kilavuz/yonetim-maliyet.jpg)

> **Tahmini** işaretli maliyet gerçek alış fiyatından değil, son alıştan ya da standart maliyetten gelir. Mal kabulde fiyat girilmesini satın almadan isteyin.

## Personel

**Personel** menüsünü yalnızca yönetim ve sistem yöneticisi görür. Sahadaki ve ofisteki bütün çalışanların kartları buradadır; sistemi kullanmayan çalışanlar (ör. forklift ve dolum operatörleri) da kaydedilir.

1. **Yeni personel**'e basın.
2. **Ad soyad** ve **Birim** zorunludur. Birimi listeden seçin ya da yeni birimi yazın; aynı birim farklı yazılırsa (depo / Depo) var olan yazım kullanılır.
3. Varsa **Sicil no**, **Görev**, **İşe giriş tarihi**, **Telefon** ve acil durumda aranacak kişiyi girin. Aynı sicil no iki kişide olamaz.
4. **Kimlik bilgileri** bölümüne TC kimlik no, doğum tarihi ve doğum yerini girin. TC kimlik no kontrol haneleriyle denetlenir; yanlış yazılırsa kaydedilmez. Aynı numara iki kartta olamaz.
5. **Mezuniyet** bölümüne en son mezuniyeti girin: öğrenim durumu, okul, bölüm ve mezuniyet yılı. Diplomayı kart açıldıktan sonra belge olarak ekleyin.
6. Kişinin sisteme giriş hesabı varsa **Sistem kullanıcısı** alanında seçin. Hesabı sistem yöneticisi **Sistem > Kullanıcılar**'dan açar.
7. **Kartı aç**'a basın.

![Personel listesi](/kilavuz/yonetim-personel.jpg)

- Arama kutusu ad, sicil no, birim ve görevde arar; birim ve **Çalışanlar / Ayrılanlar / Tümü** süzgeçleri vardır. Satıra basınca kart açılır.
- Kartta **Düzenle** bilgileri değiştirir. **Geçmiş** bölümünde her değişiklik kimin yaptığı, tarihi, eski ve yeni değeriyle yazılıdır. TC kimlik no kartta açık görünür, geçmişte yalnızca son dört hanesiyle yazılır.
- Kart silinmez. Ayrılan çalışanın kartında **İşten ayrıldı**'ya basıp çıkış tarihini girin; kart **Ayrılanlar**'a geçer. Yeniden işe başlarsa **Yeniden işe başladı**'ya basın.

> Personel kartı kişisel veridir; diğer roller göremez. Kişinin sistem hesabı ayrılışla kendiliğinden kapanmaz: kartta uyarı çıkar, hesabı sistem yöneticisi **Sistem > Kullanıcılar**'dan pasife alır.

### Özlük belgeleri

Kimlik fotokopisi, bordro, sözleşme ve diploma kartın **Belgeler** bölümündedir.

1. Kartta **Belge ekle**'ye basın.
2. **Belge türü**'nü ve dosyayı seçin: PDF, JPG ya da PNG, en çok 20 MB.
3. Bordroda **Dönem**'i (ay ve yıl), sözleşmede **Başlangıç tarihi**'ni girin. Belirsiz süreli sözleşmede **Bitiş tarihi**'ni boş bırakın.
4. **Yükle**'ye basın.

![Personel kartında mezuniyet ve belgeler](/kilavuz/yonetim-personel-belgeler.jpg)

- Belgeler türüne göre gruplanır; bordrolar en yeni dönem başta sıralanır. Bitiş tarihi geçmiş sözleşmede **Sona erdi** yazar.
- Dosya adına basınca belge yeni sekmede açılır. Her açılış kartın **Geçmiş** bölümüne yazılır.
- Yanlış belgeyi çöp kutusu simgesiyle kaldırın ve nedenini yazın. Belge silinmez ama artık açılamaz.
- Ayrılan çalışanın kartına da belge eklenebilir, ör. son bordro.

> Eski tip nüfus cüzdanında din hanesi bulunur; din özel nitelikli kişisel veridir. Fotokopiyi taramadan önce bu haneyi kapatmanız önerilir. Belgeleri de yalnızca yönetim ve sistem yöneticisi görür.

## Firma bilgileri

Firmanın ticari bilgileri **Ana veriler > Firma bilgileri** sekmesindedir. Sevk irsaliyesinde satıcı, satın alma siparişinde alıcı olarak bu bilgiler basılır; tedarikçiye giden sipariş e-postası da ticari unvanla imzalanır.

1. **Ticari unvan**'ı (zorunlu) ve **Adres**'i yazın.
2. **Vergi dairesi** ve **Vergi no / TCKN**'yi girin: şirkette 10 haneli VKN, şahıs firmasında 11 haneli TCKN. Numara kontrol hanesiyle denetlenir; yanlış yazılırsa kaydedilmez.
3. Varsa **Ticaret sicil no** ve 16 haneli **MERSİS no**'yu girin; belgelerde unvanın altında görünür.
4. **Kaydet**'e basın. Sonraki irsaliye ve siparişler yeni bilgilerle basılır.

![Firma bilgileri](/kilavuz/yonetim-firma-bilgileri.jpg)

> Bilgileri yönetim ve sistem yöneticisi değiştirir; planlama yalnızca görür. Her değişiklik denetim günlüğüne yazılır.

## Canlı başlangıç tarihi

1. **Canlıya geçiş > Hazırlık** sekmesinde kontrol kartlarını gözden geçirin. Kırmızı maddeler kapanmadan başlanmaz.
2. Sayım günü açılış stoku yüklenip kontrol edilince **Canlı başlangıç tarihi** alanına ilk canlı iş gününü yazın.
3. **Kaydet**'e basın. O tarihten sonra açılış stoku yüklenemez; farklar **Sayım düzeltme** ile girilir.

![Canlıya geçiş hazırlık listesi](/kilavuz/gecis-hazirlik.jpg)

Ayrıntılı plan **Canlıya geçiş ve sayım günü** kılavuzundadır.

## Diğer görevler

- **İSG olayı**: Bildirilen kaza ve ramak kala olayları size görev olarak gelir. **İSG ve çevre** menüsünde olayı inceleyip kapatın.
- **Siparişler ve ana veriler**: Yönetim satış siparişi açabilir, ana verileri düzenleyebilir ve tüm ekranları okuyabilir.
