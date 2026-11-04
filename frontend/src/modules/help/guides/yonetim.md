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
- **Personel maliyeti**: brüt ücret, puantaj ve ek ödemelerden ayın işveren maliyeti; üretim ve dolumda gerçekleşen işçilik (TL/kg). Birimlerin maliyet aşaması bu sekmenin altındadır; işveren payı **Personel > Bordro > Parametreler**'deki bordro parametrelerinden gelir. Ücretler **Personel > Ücretler**'de girilir.

![Gider oranları](/kilavuz/yonetim-maliyet.jpg)

> **Tahmini** işaretli maliyet gerçek alış fiyatından değil, son alıştan ya da standart maliyetten gelir. Mal kabulde fiyat girilmesini satın almadan isteyin.

### Personel maliyeti

Personel maliyeti **Personel > Bordro**'daki ön bordro hesabından gelir: brüt ücret, puantaj, ek ödemeler (**Personel > Bordro > Ek ödeme ve kesintiler**) ve bordro parametreleri. Kesintiler (avans, icra) ve gelir vergisi maliyeti değiştirmez.

1. **Personel > Ücretler**'de çalışanın satırında **Ücret ekle**'ye basın. **Brüt aylık (TL)** ve **Geçerlilik başlangıcı**'nı girin, **Kaydet**'e basın. Tutarı 45.000 ya da 45000 diye yazabilirsiniz; kutunun altında kaydedilecek tutar görünür. İlk ücretin başlangıcı varsayılan olarak işe giriş tarihidir (kartta yoksa geçen ayın 1'i). Daha geç bir tarih seçerseniz aradaki günler raporda **Ücret eksik** görünür.
2. **Maliyet > Personel maliyeti** sekmesinin altındaki **Birimlerin maliyet aşaması** bölümünde üretim birimine **Üretim (bulk)**, dolum birimine **Dolum (mamul)** seçin. Eşleştirilmeyen birim genel giderdir.
3. İşveren payı **Personel > Bordro > Parametreler**'deki bordro parametrelerinden gelir (2026'da imalat işyerinde %18,75). Parametreleri mali müşavirle kontrol edip kaydedin.
4. Ay bitip puantaj onaylanınca **Maliyet > Personel maliyeti**'nde ayı seçin. Toplamlar, aşamalar ve kişiler görünür; **Excel** tabloyu indirir. Ekim 2026'dan rozet bordronun durumunu gösterir: **Bordro onaylı** (rakamlar onayda saklanan satırlardır, sonradan değişmez) ya da **Bordro onaylanmadı (tahmin)**.
5. Üretim ya da dolum satırında **Oran olarak ekle**'ye basın. Ekim 2026'dan oran yalnızca bordrosu onaylı aydan eklenir (önce **Personel > Bordro**'da bordroyu onaylayın); oranın notuna bordro numarası yazılır. Başlangıç tarihini (varsayılan: ertesi ayın ilk günü) kontrol edip onaylayın. Gerçekleşen işçilik **Gider oranları**'na yeni işçilik oranı olarak eklenir. Lot maliyetinde şarjın ya da partinin bittiği gün geçerli oran kullanılır: oran, başlangıç tarihinde ya da sonra biten lotlara uygulanır. Bunlardan maliyeti önceden hesaplanmış olanlar için lot sayfasında **Yeniden hesapla**'ya basın; daha önce biten lotlar eski oranla kalır.

![Personel maliyeti](/kilavuz/yonetim-personel-maliyeti.jpg)

- Tam ay 30 gün sayılır. Ücretsiz izin, devamsızlık ve rapor günleri günlük ücretle (brüt / 30) düşülür; yıllık izin ve mazeret izni ücretlidir. Ay içinde giren ya da ayrılan, işte olduğu takvim günü kadar alır. Ayın hiç ücretli günü yoksa ücret sıfırdır.
- Fazla mesai saat ücreti brüt / 225'tir: iş günü ve hafta tatilinde 1,5 kat. Resmi tatilde çalışana bir günlük ilave ücret ödenir, 7,5 saati aşan saatler 1,5 kat; yarım gün tatilde öğleden sonra çalışana yarım gün.
- İşveren payı SGK matrahı üzerinden hesaplanır: SGK işveren payı − teşvik + işsizlik işveren payı. Matrah günlük alt sınır (asgari ücret) ile üst sınır arasındadır; ücret alt sınırın altındaysa farkın primini işçi payı dahil işveren öder.
- Gerçekleşen işçilik, aşamanın personel maliyetinin o ay üretilen kg'a bölümüdür: üretimde biten şarjların çıktısı, dolumda dolan bulk (fire hariç).
- Ek ödemeler (prim, ikramiye, nakit yol ve yemek) SGK işveren payıyla birlikte maliyete girer; özette ve kişi tablosunda **Ek ödeme** olarak ayrı görünür. Aralık ikramiyesi gibi tek seferlik bir ödeme o ayın gerçekleşen işçiliğini yükseltir; böyle bir ayı **Oran olarak ekle** ile sonraki lotlara uygulamadan önce kontrol edin.
- Zam yeni geçerlilik tarihiyle eklenir; eski ücret geçmişte kalır. Yanlış kaydı **Geçmiş**'ten gerekçeyle kaldırın.
- Ücreti girilmemiş kişi raporda **Ücret eksik** diye işaretlenir; o günler sıfır sayılır. Ayrılan bir kişinin ücretini girmek ya da düzeltmek için **Personel > Ücretler**'de **Ayrılanları da göster**'i açın.
- Oran penceresi, aşamada ücreti ya da mali müşavir rakamı eksik kişi ya da kg'a çevrilemeyen malzeme varsa uyarır; önce eksikleri tamamlayın.
- Puantaj onaylanmadan tutarlar taslaktır ve oran eklenemez. Ekim 2026'dan bordro onaylanmadan da oran eklenemez: onaysız ayın maliyeti bugünkü ücret, kart ve parametrelerle hesaplanan tahmindir.

> Ücretler kişisel veridir; yalnızca yönetim ve sistem yöneticisi görür. Bordrosu onaylı ayın (Ekim 2026'dan) kişi satırları ve birimleri onayda saklanır, sonradan değişmez; o ayın parametreleri ve kişinin onaylı satırını değiştiren ücret ya da işe giriş tarihi değişikliği bordro yeniden açılmadan kaydedilmez. Diğer aylar saklanmaz: ücret, ek ödeme, kişinin birimi ya da işe giriş ve çıkış tarihi ya da bordro parametreleri değişirse yeniden hesaplanır (tahmin). Birim eşleştirmesi her ayda bugünkü haliyledir. Yeniden işe alımda işe giriş tarihini ileri alırsanız önceki dönem bordrosu onaylanmamış geçmiş aylardan düşer; böyle bir değişiklikten önce o ayların Excel'ini indirin. Daha önce eklenen işçilik oranları değişmez. Excel kişi başına rakam içerir: tarayıcı önbelleğine alınmaz, her indirme denetim günlüğüne yazılır; dosyayı yalnızca yönetim içinde paylaşın.

## Personel

**Personel** menüsünü yalnızca yönetim ve sistem yöneticisi görür. Sahadaki ve ofisteki bütün çalışanların kartları buradadır; sistemi kullanmayan çalışanlar (ör. forklift ve dolum operatörleri) da kaydedilir. Brüt aylık ücretler **Personel > Ücretler** sekmesinde girilir (bkz. "Personel maliyeti").

1. **Yeni personel**'e basın.
2. **Ad soyad** ve **Birim** zorunludur. Birimi listeden seçin ya da yeni birimi yazın; aynı birim farklı yazılırsa (depo / Depo) var olan yazım kullanılır.
3. Varsa **Sicil no**, **Görev**, **İşe giriş tarihi**, **Telefon** ve acil durumda aranacak kişiyi girin. Aynı sicil no iki kişide olamaz.
4. **Kimlik bilgileri** bölümüne TC kimlik no, doğum tarihi ve doğum yerini girin. TC kimlik no kontrol haneleriyle denetlenir; yanlış yazılırsa kaydedilmez. Aynı numara iki kartta olamaz.
5. **Mezuniyet** bölümüne en son mezuniyeti girin: öğrenim durumu, okul, bölüm ve mezuniyet yılı. Diplomayı kart açıldıktan sonra belge olarak ekleyin.
6. Kişinin sisteme giriş hesabı varsa **Sistem kullanıcısı** alanında seçin. Hesabı sistem yöneticisi **Sistem > Kullanıcılar**'dan açar.
7. **Bordro** bölümünde, bordrosu ERP'de hesaplanmayacak kişide (emekli, engelli, kısmi süreli, net ücretle anlaşılmış ya da başka işyerinde de çalışan) **Bordrosu mali müşavirde**'yi işaretleyin; nedenini yazmayın. BES otomatik katılımındaki kişide **BES'e dahil**'i işaretleyin: her ay SGK matrahının %3'ü netten kesilir. Cayma olursa işareti kaldırın.
8. **Kartı aç**'a basın.

![Personel listesi](/kilavuz/yonetim-personel.jpg)

- Arama kutusu ad, sicil no, birim ve görevde arar; birim ve **Çalışanlar / Ayrılanlar / Tümü** süzgeçleri vardır. Satıra basınca kart açılır.
- Kartta **Düzenle** bilgileri değiştirir. **Geçmiş** bölümünde her değişiklik kimin yaptığı, tarihi, eski ve yeni değeriyle yazılıdır. TC kimlik no kartta açık görünür, geçmişte yalnızca son dört hanesiyle yazılır.
- Kart silinmez. Ayrılan çalışanın kartında **İşten ayrıldı**'ya basıp çıkış tarihini girin; çıkış tarihi son çalışma günüdür ve o gün dahildir. Kart **Ayrılanlar**'a geçer. Yeniden işe başlarsa **Yeniden işe başladı**'ya basın.
- Puantajda çıkış tarihinden sonra kayıtlı gün varsa (ör. önceden girilmiş izin), pencere bu günleri listeler. **Kaydet ve günleri kaldır**'a basınca ayrılış kaydedilir ve günler puantajdan kaldırılır. Kaldırılan günler tarihi, durumu ve fazla mesaisiyle kartın **Geçmiş** bölümüne yazılır; **Yeniden işe başladı** onları geri getirmez.
- Bu günlerden biri onaylı bir aydaysa ayrılış kaydedilmez, çünkü bordroya giden rakam değişir. O ayın bordrosu da onaylıysa önce **Personel > Bordro**'da bordroyu gerekçeyle yeniden açın (aylar sondan başa açılır; mesaj ayları söyler). Sonra mesajda adı geçen her ayı Puantaj'da açın (**Puantajı aç** bağlantısı ilkini açar, diğerlerine ay oklarıyla geçin), **Yeniden aç**'a basıp gerekçeyi yazın ve ayrılışı kaydedin. Ardından önce puantajı, sonra bordroyu (eskiden yeniye) yeniden onaylayıp yeni Excel'i bordroya verin.
- Çıkış tarihini düzeltmek için önce **Yeniden işe başladı**'ya, sonra doğru tarihle **İşten ayrıldı**'ya basın. Doğru tarih daha ileriyse ve arada onaylanmış ay varsa, o ayda iki tarih arasındaki günler boş kalır: ayın bordrosu onaylıysa önce **Personel > Bordro**'da bordroyu gerekçeyle yeniden açın; sonra puantajı **Yeniden aç** ile gerekçeyle açıp yeniden onaylayın, ardından bordroyu yeniden onaylayıp yeni Excel'i bordroya verin.

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
2. Bir güne basın. **Durum**'u seçin, varsa **Fazla mesai (saat)** ve not girin, **Kaydet**'e basın. Yarım gün tatilde (28 Ekim, arifeler) öğleden sonra da çalışıldıysa gün **Ç** kalır; **Öğleden sonra da çalıştı (yarım gün tatil)**'ı işaretleyin.
3. Birkaç günlük izin ya da rapor için **Aralık gir**'e basın: kişiyi, birimi ya da herkesi seçin; başlangıç, bitiş ve durumu girin.
4. Ay bitince **Ayı onayla**'ya basın. Değiştirilmemiş günler takvimdeki haliyle yazılır ve ay kilitlenir. Bu ay işten ayrılan varsa önce kartında çıkışını kaydedin.
5. **Excel** aylık tabloyu, toplamları ve günlük fazla mesaiyi indirir; bordroya bu dosyayı verin.

![Puantaj](/kilavuz/yonetim-puantaj.jpg)

- Kodlar: **Ç** çalıştı, **HT** hafta tatili, **RT** resmi tatil, **Yİ** yıllık izin, **Mİ** mazeret izni (ücretli), **Üİ** ücretsiz izin, **R** raporlu, **D** devamsız, **Ç½** yarım gün tatilde öğleden sonra da çalıştı. Kalın kod elle değiştirilmiş gündür.
- Aralıkla girişte yıllık izin, mazeret izni ve devamsızlık hafta tatili ve resmi tatil günlerine yazılmaz; rapor ve ücretsiz izin her güne yazılır.
- Fazla mesai yalnızca çalışılan, hafta tatili ve resmi tatil günlerine girilir. Tatilde çalışan kişinin günü HT ya da RT kalır; çalıştığı saat fazla mesai olarak girilir. Yarım gün tatilde öğleden sonraki çalışma fazla mesai olarak değil, **Öğleden sonra da çalıştı** işaretiyle girilir; tatil sonradan kaldırılır ya da tam güne çevrilirse işaret sayılmaz ve tabloda **Ç** görünür.
- Devamsızlık ve fazla mesai ileri bir güne girilemez; izin ve rapor önceden girilebilir.
- Toplamlarda **Eksik**, ücretsiz izin, rapor ve devamsızlık günlerinin toplamıdır; **FM** fazla mesai saatidir. Excel'de fazla mesai iş günü, hafta tatili ve resmi tatil olarak ayrı sütunlardadır.
- Onaylı ayda düzeltme gerekirse **Yeniden aç**'a basıp gerekçeyi yazın. Günler onaydaki haliyle kalır. Çıkış tarihinden sonraki kayıtlı günlerden biri onaylı bir aydaysa ayrılış da ancak o ay yeniden açılınca kaydedilir. Ayın bordrosu onaylıysa **Yeniden aç** kapalıdır: önce **Personel > Bordro**'da bordroyu yeniden açın.
- Kişinin işe girişinden önceki ve çıkışından sonraki günleri takvimden doldurulmaz ve değiştirilemez; ayrılışta çıkıştan sonraki kayıtlı günler kaldırılır. İşe giriş tarihi sonradan ileri alınırsa önceden kayıtlı günler tabloda ve Excel'de kalır.

### Tatil takvimi

1. **Personel > Tatil takvimi**'nde yılı seçin.
2. **Yılın sabit tatillerini ekle**'ye basın: 1 Ocak, 23 Nisan, 1 Mayıs, 19 Mayıs, 15 Temmuz, 30 Ağustos, 28 Ekim (yarım gün) ve 29 Ekim eklenir.
3. Ramazan ve Kurban Bayramı günlerini **Tatil ekle** ile girin; arifelerde **Yarım gün**'ü işaretleyin.
4. **Varsayılan hafta tatili günleri**'nde hafta tatilini seçin (başlangıçta pazar) ve **Kaydet**'e basın.

![Tatil takvimi](/kilavuz/yonetim-tatil-takvimi.jpg)

> Rapor bilgisi sağlık verisidir; puantajı yalnızca yönetim ve sistem yöneticisi görür. Onaylı aya düşen tatil değiştirilemez; önce ay yeniden açılır (ayın bordrosu onaylıysa önce bordro).

## Bordro

**Personel > Bordro** sekmesi ayın ön bordrosunu puantajdan, ücretlerden, ek ödeme ve kesintilerden hesaplar. Ön bordrodur: SGK (e-Bildirge) ve vergi (MUHSGK) bildirimini mali müşavir yapmaya devam eder. İlk aylarda rakamları mali müşavirin bordrosuyla karşılaştırın.

Brütten nete bordro Ekim 2026'dan başlar; önceki aylarda yalnızca işveren maliyeti hesaplanır. Sayfada üç görünüm vardır: **Bordro** (brütten nete), **İşveren maliyeti** ve **Ek ödeme ve kesintiler**.

1. Ayı oklarla seçin. Rozetler bordronun, puantajın ve parametrelerin durumunu gösterir: **Bordro onaylı** (numarası ve ödeme tarihiyle) ya da **Bordro taslak**; **Puantaj onaylı** ya da **Puantaj açık (taslak)**; **Parametreler kayıtlı**, **Parametreler kaydedilmedi** (o yılın yasal değerleriyle hesaplandı) ya da kırmızı **Parametreler yok (tahmin)** (yeni yılın değerleri girilmedi; başka yılın değerleriyle tahmin edildi).
2. **Ay hazırlığı** kutusu ayın eksiklerini sıralar: puantaj, parametreler, devirler (giriş ayına göre ayrı satırlarda), ücreti eksik kişiler, mali müşavir rakamları, netten fazla kesinti, hesaba girmeyen kalemler, bir önceki ayın bordrosu onaylanmadıysa o ay. Son satır bordronun onaya hazır olup olmadığını söyler. Satırın yanındaki bağlantı eksiği tamamlayacağınız yeri açar.
3. **Parametreler**'e basın. Yeni set o yılın yasal değerleriyle dolu gelir. **SGK işveren teşviki**'ni (imalat işyerinde 5 puan) ve diğer değerleri mali müşavirle kontrol edip **Mali müşavirle kontrol ettim, kaydet**'e basın. **Nakit yemek SGK istisnası (günlük TL)**'yi mali müşavirden alıp girin; girilene kadar 0'dır. Yıl içinde değişen değer için (ör. Temmuz'da asgari ücret) **Yeni set** seçip **Geçerlilik (ay)**'ı o ay yapın. Yanlış seti **Seti kaldır** ile gerekçeyle kaldırın.
4. Ekim 2026'da **Devirler**'e basın (ya da Ay hazırlığındaki **Devir gir**'e). Her satıra mali müşavirin Eylül bordrosundaki **kümülatif gelir vergisi matrahını** (Eylül dahil) girin. **İstisna ay**, asgari ücret istisnasının bu işyerinde uygulandığı ay sayısıdır; işe giriş tarihinden önerilir. Tutarları Excel'den yapıştırabilirsiniz: yalnızca tutar sütununu (isterseniz yanındaki istisna ay sütunuyla) kopyalayıp bir kutuya yapıştırınca aşağıdaki satırlar ekrandaki sırayla dolar (Excel'deki boş hücre o kişiyi atlar). Sicil no sütunuyla birlikte kopyalarsanız (araya ad soyad sütunu girebilir) satırlar sicil no ile eşleşir, sıra önemli olmaz; eşleşmeyen sicil numaraları pencerede yazılır, hiçbiri eşleşmezse hiçbir kutu dolmaz. TC kimlik no ya da gün sütununu kopyalamayın: sicil no'dan sonra birden çok sayı sütunu olunca tutar sütunu belirlenemez ve hiçbir kutu dolmaz. Tutarın sağındaki sütun istisna ay sayısı olarak alınır. Boş bıraktığınız satır kaydedilmez; okunamayan bir tutar varken kaydedilmez. **Kaydet** hepsini birlikte kaydeder; bir satır hatalıysa hiçbiri kaydedilmez ve hata o satırın altında yazar.
5. **Ek ödeme ve kesintiler** görünümünde **Kalem ekle**'ye basın. Kişiyi, kalemi ve tutarı girin. Ek ödemeler (prim, ikramiye, yol, yemek, diğer ek ödeme) brüte eklenir; SGK'ya ve vergiye tabidir. Kesintiler (avans, icra / nafaka, diğer kesinti) netten düşülür. Kalemi, birlikte ödendiği ücretin ayına girin: Ekim ücretiyle ödenen prim Ekim bordrosuna girer. Gelecek aya kalem girilmez; ay gelince girin. Bordrosu mali müşavirde olan kişiye kalem girilmez.
6. Aynı kalemi birkaç kişiye eklemek için **Toplu ekle**'ye basın; kişileri seçin ya da **Hepsini seç**'e basın. Her ay tekrarlanan kalemler için **Geçen aydan kopyala**'ya basın: geçen ayın kalemleri işaretli gelir, bu ayda zaten olanlar (aynı kişi, kalem, tutar ve açıklama) işaretsiz gelir; gözden geçirip ekleyin.
7. **Bordro** görünümünde kişinin adına basın; **döküm** açılır: günler, kazançlar, SGK, gelir ve damga vergisi, kesintiler, işveren payları ve kümülatifin nasıl kurulduğu. Mali müşavirin bordrosuyla satır satır karşılaştırın. **Önceki kişi** / **Sonraki kişi** ya da klavyedeki sol ve sağ ok tuşları tablodaki kişiler arasında geçer (**Yalnızca uyarılı kişiler** açıksa yalnızca onlar arasında). Dökümün **Ek ödeme ve kesinti** ve **Devir** sekmelerinden de kalem ve devir girilir.
8. Kartında **Bordrosu mali müşavirde** işaretli kişinin rakamlarını **İşveren maliyeti** görünümünde satırdaki **Rakamları gir** ile girin: mali müşavirin bordrosundaki **Brüt toplam** ve **İşverene maliyet**. Ayın tamamını raporlu ya da ücretsiz izinli geçiren kişide 0 yazılabilir. **Rakamları düzelt** aynı ayın rakamlarını değiştirir; yanlış girilen rakamı **Rakamları kaldır** ile gerekçeyle kaldırın. O aya ERP'de girilmiş ek ödeme ya da kesinti varsa rakam yine girilir: kalemler hesaplanmaz, bordro listesinde mali müşavir bölümünde kalem toplamlarıyla yazılır; mali müşavire bildirin.
9. **Bordro listesi (PDF)** ayın bordrosunu yazdırılabilir açar; **İşveren maliyeti (PDF)** işveren maliyeti tablosunu açar. **Excel** şu sayfaları indirir: **Bordro**, **İşveren maliyeti**, **Karşılaştırma** (mali müşavirin rakamlarını yapıştırınca fark kendiliğinden hesaplanır; kuruştan büyük fark kırmızı), **Eksik gün** (eksik gün bildirimi için) ve **Parametreler**.
10. Rakamlar mali müşavirin bordrosuyla tutunca **Bordroyu onayla**'ya basın. Pencere toplamları ve onayı engelleyenleri kişi adlarıyla yazar (puantaj onaylanmadı, bir önceki ayın bordrosu onaylanmadı, parametreler kaydedilmedi, devir eksik, zincir eksik, ücret eksik, mali müşavir rakamı girilmedi, kesinti netten fazla, asgari ücretin altında, SGK günü yok, o ay işte olmayan kişiye girilmiş kalem). **Ay içinde çıkış** ve **Tavanı aşan prim** varsa kişileri okuyup **Okudum**'u işaretleyin. **Ödeme tarihi**'ni girin (ayın başından üç ay sonrasının sonuna kadar; ay sonundan 20 günden sonrası uyarılır) ve **Onayla ve kilitle**'ye basın. Bordro **BR-** numarası alır. Aylar sırayla onaylanır: Kasım, Ekim onaylanmadan onaylanmaz.
11. Onaylı ayın satırları onay anındaki haliyle saklanır: kişinin kartı, ücreti ya da parametreler sonradan değişse de ekran, PDF, Excel ve personel maliyeti onaydaki rakamları gösterir. Ay kilitlidir: o aya kalem, devir ve mali müşavir rakamı girilmez, düzeltilmez; o ayın günlerine düşen ücret, o ayın parametreleri, ayın puantajı ve ayı değiştiren işe giriş tarihi değiştirilemez. Çıktılarda **TASLAK** yazmaz; başlıkta bordro numarası, onay ve ödeme tarihi yazar.
12. **Ücret pusulaları (PDF)** onaylı ayın ücret hesap pusulalarını kişi başına bir sayfa açar; tek kişinin pusulası dökümdeki **Ücret pusulası (PDF)** ile açılır. Pusula bilgi amaçlı iç belgedir (imza satırı yoktur); resmî pusula mali müşavirin bordrosudur. Bordrosu mali müşavirde olan kişilerin adları son sayfada yazar.
13. Onaydan sonra düzeltme gerekirse **Yeniden aç**'a basıp gerekçeyi yazın. Yalnızca en son onaylı ay açılır (aylar sondan başa). Eski onay saklanır ve **Onay geçmişi**'nden çıktıları (**GEÇERSİZ** damgalı) açılır; düzeltip yeniden onaylayınca bordro aynı numarayla **2. onay** olur. Yeniden açılan ayda onaydaki kişiler onaydaki **Bordrosu mali müşavirde** ve **BES'e dahil** işaretleriyle hesaplanır; kartı sonradan değişen kişiler Ay hazırlığında ve onay penceresinde yazar (onay penceresi her kişinin onayda hangi işaretlerle saklanacağını da yazar); kartın bugünkü işaretleriyle hesaplamak için onaydan önce Ay hazırlığında **Kartı izle**'ye basın. O aya mali müşavir rakamı girilmiş kişi, rakam kaldırılana kadar mali müşavirde kalır. Yalnızca ödeme tarihi yanlışsa ayı açmadan **Ödeme tarihini düzelt** ile gerekçeyle düzeltin; tutarlar değişmez.

- Bordro tablosunda kişi başına SGK günü, normal ücret, fazla mesai ve tatil, ek ödeme, brüt toplam, SGK ve işsizlik işçi payları, gelir vergisi, damga vergisi, net ücret, BES, diğer kesintiler ve **Ödenecek (ele geçen)** bulunur. **Yalnızca uyarılı kişiler** süzgeci eksikleri öne çıkarır. Bordrosu mali müşavirde olan kişiler tabloda yoktur; rakamları tablonun altında ayrı yazılır, toplamlara katılmaz.
- Gelir vergisi yıl içinde kümülatiftir: her ayın matrahı önceki ayların toplamına eklenir ve dilim buna göre belirlenir. ERP kümülatifi Ekim 2026 devrinden kurar. Bir ayı mali müşavirde hesaplanan kişi için sonraki ilk ERP ayında yeniden devir istenir.
- Mali müşavirle kümülatif ayrışırsa o ayın devrini girin: dökümün **Devir** sekmesinde **Bu aydan devir gir (mali müşavirle eşitleme)**'ye basın, mali müşavirin bir önceki ay bordrosundaki kümülatifi yazın. Devir önceki ayların ERP hesabının yerine geçtiği için onay kutusu işaretlenmeden kaydedilmez. Gelecek aya devir girilmez; o ayın devir düğmeleri ay gelince açılır. Yanlış devri **Devri kaldır** ile gerekçeyle kaldırın.
- **Diğer ek ödeme** ve **Diğer kesinti**'de açıklama zorunludur. İcra / nafakada açıklamaya dosya numarası yazılabilir; alacaklının ya da nafaka alanın adını yazmayın (açıklama denetim günlüğünden silinmez). Kalem silinmez: **Kaldır** ile gerekçeyle kaldırılır; **Kaldırılanları göster** onları da listeler. Geçmiş bir ayda yapılan değişiklik sonraki ayların kümülatifini ve gelir vergisini de değiştirir.
- Nakit yemek ödemesinin fiilen çalışılan gün × günlük sınıra kadarki kısmı SGK matrahına girmez; gelir ve damga vergisine tabidir.
- **Alt sınır**: brüt SGK alt sınırının altında kaldığı için matrah alt sınıra çıkarıldı; farkın primini işçi payı dahil işveren öder. **Tavan**: matrah üst sınırla kesildi.
- Uyarılar: **Devir eksik** (gelir vergisi kümülatifsiz, yani düşük; net yüksek hesaplandı), **Zincir eksik** (önceki bir ayda ücret eksik, parametre tahmini ya da devir kaydedildikten sonra parametreler değişti; dökümün zincir tablosu nedenini yazar, parametreleri değişen devri Ay hazırlığındaki **Devri yeniden kaydet** bağlantısıyla ya da dökümün **Devir** sekmesinde **Devri düzelt** ile değiştirmeden yeniden kaydedin; tahmini parametrede önce o yılın parametrelerini kaydedin), **Kesinti netten fazla** (ödenecek negatif: kesintiyi azaltın, kalanını sonraki aya girin; bordro bu haliyle onaylanmaz), **Tavanı aşan prim** (tavanı aşan kısmın sonraki iki aya devrini ERP hesaplamaz; mali müşavirle kontrol edin), **Ücret eksik** (ücreti girilmemiş günler sıfır sayıldı; **Ücretleri aç**), **Asgari ücretin altında**, **Ay içinde çıkış** (kıdem, ihbar ve kullanılmamış izin ücreti hesaplanmaz; mali müşavire bildirin), **SGK günü yok**, **Rakam girilmedi**. Bordro listesinde uyarılar harfle gösterilir; harflerin anlamı listenin altında yazar.
- Kişinin işe giriş tarihini ileri alacaksanız ya da ayrılışını kaydedecekseniz ve işte olmayacağı bir aya kalem ya da devir girilmişse, önce onları gerekçeyle kaldırın; kalem başka bir aya aitse o aya yeniden girin (kalemin ayı değiştirilemez). Devrin istisna ay sayısı yeni işe giriş tarihine göre fazla kalacaksa önce devri düzeltin. İşte olmadığı aya ya da bordrosu mali müşavirde olan kişiye girilmiş kalem hesaba girmez; Ay hazırlığında ve **Ek ödeme ve kesintiler** görünümünde ayrıca yazılır, kalem toplamlarına katılmaz.
- Puantaj onaylanana kadar girilmemiş günler takvimden sayılır. Onaylanmamış bordronun çıktıları taslaktır: PDF'te çapraz **TASLAK** damgası, Excel'de başlıkta **TASLAK** yazar. Her PDF, Excel ve pusula açılışı denetim günlüğüne yazılır; tek kişinin pusulası kartın geçmişine de.
- Kartı bordro onaylandıktan sonra açılan ya da işe giriş tarihi sonradan onaylı bir aya çekilen kişinin o ayda bordro satırı yoktur; o ayın kümülatifi bilinmediği için ilk açık ayda **Devir eksik** uyarısı çıkar (kişinin sonraki bir ayına girilmiş devir o ayı kapsıyorsa çıkmaz): mali müşavirin bir önceki ay bordrosundaki kümülatifi o aya devir olarak girin. İşe giriş tarihini kişinin satırı olmayan önceki bir aya (Ekim 2026'dan önceki aylar dahil) çekmek, aynı yıl sonraki ilk onaylı satırı ERP'deyse ve o satırın zinciri çekilen aydan sonraki bir devirle başlamıyorsa o satırın kümülatifini değiştirir: kaydedilmez, önce o ayın bordrosunu yeniden açın. Aynı yıl içinde ayrılıp **Yeniden işe başladı** ile dönen kişide de kart aradaki boşluğu tutmaz: aradaki onaylı ayda satırı olmadığından ilk açık ayda devir istenir.
- Çıktıların dosya adı durumu söyler: taslakta **…-taslak**, onaylıda bordro numarası ve onay sırası (**…-BR-2026-00001-onay1**), eski onayda ayrıca **…-gecersiz**.
- Kartta **Bordrosu mali müşavirde** sonradan işaretlenirse onaylı aylar onaydaki haliyle kalır; onaylanmamış aylardaki ek ödeme, kesinti ve devirleri kartın geçmişine yazılır ve kaydedince ekranda uyarılır: mali müşavire bildirin, gerekmiyorsa gerekçeyle kaldırın. Yeniden açılan ayda kişi son onaydaki haliyle ERP'de kalır (o aya mali müşavir rakamı girilmediyse; o ayın kaydı bunu yazar); o ayı kartın işaretiyle hesaplamak için Ay hazırlığında **Kartı izle**'ye basın.

> Bordro kişisel veridir; yalnızca yönetim ve sistem yöneticisi görür. **Bordrosu mali müşavirde** işaretinin nedenini (emeklilik, engellilik gibi) hiçbir alana ve nota yazmayın: engellilik sağlık verisidir ve not denetim günlüğünden silinmez. Kalem açıklamaları bordro listesine, Excel'e ve kartın geçmişine yazılmaz, ama denetim günlüğünde kalır; kaldırma nedeni kartın geçmişine de yazılır. İkisine de dosya numarasından başka kişisel bilgi yazmayın. Excel'in **Eksik gün** sayfası rapor tarihlerini içerir (sağlık verisi); dosyayı yalnızca mali müşavirle paylaşın.

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
