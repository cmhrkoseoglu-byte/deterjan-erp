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
- **Personel maliyeti**: brüt ücret ve puantajdan ayın işveren maliyeti; üretim ve dolumda gerçekleşen işçilik (TL/kg).
- **Personel ücretleri**: çalışanların brüt aylık ücreti, birimlerin maliyet aşaması ve işveren payı.

![Gider oranları](/kilavuz/yonetim-maliyet.jpg)

> **Tahmini** işaretli maliyet gerçek alış fiyatından değil, son alıştan ya da standart maliyetten gelir. Mal kabulde fiyat girilmesini satın almadan isteyin.

### Personel maliyeti

Personel maliyeti brüt ücretten ve puantajdan hesaplanır. Bordro değildir; vergi ve kesintiler hesaplanmaz.

1. **Maliyet > Personel ücretleri**'nde çalışanın satırında **Ücret ekle**'ye basın. **Brüt aylık (TL)** ve **Geçerlilik başlangıcı**'nı girin, **Kaydet**'e basın. Tutarı 45.000 ya da 45000 diye yazabilirsiniz; kutunun altında kaydedilecek tutar görünür. İlk ücretin başlangıcı varsayılan olarak işe giriş tarihidir (kartta yoksa geçen ayın 1'i). Daha geç bir tarih seçerseniz aradaki günler raporda **Ücret eksik** görünür.
2. Aynı sekmede **Birimlerin maliyet aşaması** bölümünde üretim birimine **Üretim (bulk)**, dolum birimine **Dolum (mamul)** seçin. Eşleştirilmeyen birim genel giderdir.
3. **İşveren payı**'nı kontrol edin (teşvikli varsayılan %17,75).
4. Ay bitip puantaj onaylanınca **Maliyet > Personel maliyeti**'nde ayı seçin. Toplamlar, aşamalar ve kişiler görünür; **Excel** tabloyu indirir.
5. Üretim ya da dolum satırında **Oran olarak ekle**'ye basın. Başlangıç tarihini (varsayılan: ertesi ayın ilk günü) kontrol edip onaylayın. Gerçekleşen işçilik **Gider oranları**'na yeni işçilik oranı olarak eklenir. Lot maliyetinde şarjın ya da partinin bittiği gün geçerli oran kullanılır: oran, başlangıç tarihinde ya da sonra biten lotlara uygulanır. Bunlardan maliyeti önceden hesaplanmış olanlar için lot sayfasında **Yeniden hesapla**'ya basın; daha önce biten lotlar eski oranla kalır.

![Personel maliyeti](/kilavuz/yonetim-personel-maliyeti.jpg)

- Tam ay 30 gün sayılır. Ücretsiz izin, devamsızlık ve rapor günleri günlük ücretle (brüt / 30) düşülür; yıllık izin ve mazeret izni ücretlidir. Ay içinde giren ya da ayrılan, işte olduğu takvim günü kadar alır. Ayın hiç ücretli günü yoksa ücret sıfırdır.
- Fazla mesai saat ücreti brüt / 225'tir: iş günü ve hafta tatilinde 1,5 kat, resmi tatilde ayrıca 1 kat.
- Gerçekleşen işçilik, aşamanın personel maliyetinin o ay üretilen kg'a bölümüdür: üretimde biten şarjların çıktısı, dolumda dolan bulk (fire hariç).
- Zam yeni geçerlilik tarihiyle eklenir; eski ücret geçmişte kalır. Yanlış kaydı **Geçmiş**'ten gerekçeyle kaldırın.
- Ücreti girilmemiş kişi raporda **Ücret eksik** diye işaretlenir; o günler sıfır sayılır. Ayrılan bir kişinin ücretini girmek ya da düzeltmek için ücretler sekmesinde **Ayrılanları da göster**'i açın.
- Oran penceresi, aşamada ücreti eksik kişi ya da kg'a çevrilemeyen malzeme varsa uyarır; önce eksikleri tamamlayın.
- Puantaj onaylanmadan tutarlar taslaktır ve oran eklenemez.

> Ücretler kişisel veridir; yalnızca yönetim ve sistem yöneticisi görür. Rapor saklanmaz: ücret, kişinin birimi ya da işe giriş ve çıkış tarihi, birim eşleştirmesi ya da işveren payı değişirse geçmiş aylar (onaylılar dahil) yeniden hesaplanır. Yeniden işe alımda işe giriş tarihini ileri alırsanız önceki dönem geçmiş aylardan düşer; böyle bir değişiklikten önce geçmiş ayların Excel'ini indirin. Daha önce eklenen işçilik oranları değişmez.

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
- Kart silinmez. Ayrılan çalışanın kartında **İşten ayrıldı**'ya basıp çıkış tarihini girin; çıkış tarihi son çalışma günüdür ve o gün dahildir. Kart **Ayrılanlar**'a geçer. Yeniden işe başlarsa **Yeniden işe başladı**'ya basın.
- Puantajda çıkış tarihinden sonra kayıtlı gün varsa (ör. önceden girilmiş izin), pencere bu günleri listeler. **Kaydet ve günleri kaldır**'a basınca ayrılış kaydedilir ve günler puantajdan kaldırılır. Kaldırılan günler tarihi, durumu ve fazla mesaisiyle kartın **Geçmiş** bölümüne yazılır; **Yeniden işe başladı** onları geri getirmez.
- Bu günlerden biri onaylı bir aydaysa ayrılış kaydedilmez, çünkü bordroya giden rakam değişir. Mesajda adı geçen her ayı Puantaj'da açın (**Puantajı aç** bağlantısı ilkini açar, diğerlerine ay oklarıyla geçin), **Yeniden aç**'a basıp gerekçeyi yazın, sonra ayrılışı kaydedin. Ardından bu ayları yeniden onaylayıp yeni Excel'i bordroya verin.
- Çıkış tarihini düzeltmek için önce **Yeniden işe başladı**'ya, sonra doğru tarihle **İşten ayrıldı**'ya basın. Doğru tarih daha ileriyse ve arada onaylanmış ay varsa, o ayda iki tarih arasındaki günler boş kalır: ayı **Yeniden aç** ile gerekçeyle açıp yeniden onaylayın ve yeni Excel'i bordroya verin.

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

## Puantaj

**Personel > Puantaj** sekmesinde her ayın puantajı tutulur. Ay takvimden dolu açılır: iş günleri **Ç** (çalıştı), hafta tatilleri **HT**, resmi tatiller **RT**. Yalnızca istisnaları girersiniz.

1. Ayı oklarla seçin; gerekirse birim süzgecini kullanın.
2. Bir güne basın. **Durum**'u seçin, varsa **Fazla mesai (saat)** ve not girin, **Kaydet**'e basın.
3. Birkaç günlük izin ya da rapor için **Aralık gir**'e basın: kişiyi, birimi ya da herkesi seçin; başlangıç, bitiş ve durumu girin.
4. Ay bitince **Ayı onayla**'ya basın. Değiştirilmemiş günler takvimdeki haliyle yazılır ve ay kilitlenir. Bu ay işten ayrılan varsa önce kartında çıkışını kaydedin.
5. **Excel** aylık tabloyu, toplamları ve günlük fazla mesaiyi indirir; bordroya bu dosyayı verin.

![Puantaj](/kilavuz/yonetim-puantaj.jpg)

- Kodlar: **Ç** çalıştı, **HT** hafta tatili, **RT** resmi tatil, **Yİ** yıllık izin, **Mİ** mazeret izni (ücretli), **Üİ** ücretsiz izin, **R** raporlu, **D** devamsız. Kalın kod elle değiştirilmiş gündür.
- Aralıkla girişte yıllık izin, mazeret izni ve devamsızlık hafta tatili ve resmi tatil günlerine yazılmaz; rapor ve ücretsiz izin her güne yazılır.
- Fazla mesai yalnızca çalışılan, hafta tatili ve resmi tatil günlerine girilir. Tatilde çalışan kişinin günü HT ya da RT kalır; çalıştığı saat fazla mesai olarak girilir.
- Devamsızlık ve fazla mesai ileri bir güne girilemez; izin ve rapor önceden girilebilir.
- Toplamlarda **Eksik**, ücretsiz izin, rapor ve devamsızlık günlerinin toplamıdır; **FM** fazla mesai saatidir. Excel'de fazla mesai iş günü, hafta tatili ve resmi tatil olarak ayrı sütunlardadır.
- Onaylı ayda düzeltme gerekirse **Yeniden aç**'a basıp gerekçeyi yazın. Günler onaydaki haliyle kalır. Çıkış tarihinden sonraki kayıtlı günlerden biri onaylı bir aydaysa ayrılış da ancak o ay yeniden açılınca kaydedilir.
- Kişinin işe girişinden önceki ve çıkışından sonraki günleri takvimden doldurulmaz ve değiştirilemez; ayrılışta çıkıştan sonraki kayıtlı günler kaldırılır. İşe giriş tarihi sonradan ileri alınırsa önceden kayıtlı günler tabloda ve Excel'de kalır.

### Tatil takvimi

1. **Personel > Tatil takvimi**'nde yılı seçin.
2. **Yılın sabit tatillerini ekle**'ye basın: 1 Ocak, 23 Nisan, 1 Mayıs, 19 Mayıs, 15 Temmuz, 30 Ağustos, 28 Ekim (yarım gün) ve 29 Ekim eklenir.
3. Ramazan ve Kurban Bayramı günlerini **Tatil ekle** ile girin; arifelerde **Yarım gün**'ü işaretleyin.
4. **Varsayılan hafta tatili günleri**'nde hafta tatilini seçin (başlangıçta pazar) ve **Kaydet**'e basın.

![Tatil takvimi](/kilavuz/yonetim-tatil-takvimi.jpg)

> Rapor bilgisi sağlık verisidir; puantajı yalnızca yönetim ve sistem yöneticisi görür. Onaylı aya düşen tatil değiştirilemez; önce ay yeniden açılır.

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
