# Sistem yöneticisi

Sistem yöneticisi; kullanıcıları, rollerini ve kişiye özel yetkilerini yönetir, kullanıcıların gönderdiği sorun bildirimlerini çözer, kodlama sistematiğini (kod, belge ve lot numarası biçimleri, çıktıların doküman kodu, GS1), etiket yazıcılarını ve etiket ayarlarını tutar. Yönetici her menüyü görür.

## Kullanıcı açma ve rol verme

Kullanıcılar **Sistem > Kullanıcılar** ekranında yönetilir. Bu ekranı yalnızca sistem yöneticisi görür.

1. **Yeni kullanıcı**'ya basın.
2. **Ad soyad**'ı yazın. **Kullanıcı adı** ad soyaddan önerilir (Ahmet Yılmaz → ahmet.yilmaz); isterseniz değiştirin. Kullanıcı adı küçük harf, rakam, nokta, alt çizgi ve tireden oluşur, Türkçe karakter içermez ve sonradan değiştirilemez.
3. Varsa telefonu ve e-postayı girin, kişinin **Roller**ini işaretleyin. Bir kişiye birden fazla rol verilebilir. İlk roller burada verilir; sonraki değişiklikler kişinin **Yetkiler** sayfasından yapılır.
4. **Hesabı aç**'a basın. Sistem bir **geçici şifre** üretir ve **yalnızca bir kez** gösterir. **Kopyala** ile alın ya da not edin ve kişiye yüz yüze ya da güvenli bir yoldan iletin.
5. Kişi geçici şifreyle girince önce kendi şifresini belirler; o zamana kadar başka ekran açılmaz. Rolü gerektiriyorsa (sistem yöneticisi, yönetim) ardından iki aşamalı doğrulamayı kurar.

![Kullanıcılar ekranı](/kilavuz/admin-kullanicilar.jpg)

> Kullanıcı silinmez. İşten ayrılan kişiyi satırdaki **⋯ > Pasife al** ile pasife alın: giriş yapamaz, açık oturumu kapanır, geçmiş kayıtlarda adı kalır. Gerekirse **⋯ > Etkinleştir** ile geri açın.

- **Düzenle**: ad soyad, telefon ve e-postayı değiştirir. Roller pencerede yalnızca görünür; değiştirmek için **Rolleri ve yetkileri değiştir**'e basın (kişinin Yetkiler sayfası açılır, aşağıda). Kendi sistem yöneticisi rolünüzü kaldıramazsınız; sistemde her zaman en az bir aktif yönetici kalır.
- **⋯ > Şifre sıfırla**: şifresini unutan kişiye yeni geçici şifre üretir (bir kez gösterilir). Kişinin açık oturumu kapanır, hesabı kilitliyse kilit açılır; kişi girişte yeniden kendi şifresini belirler. Kendi şifrenizi **Güvenlik** sayfasından değiştirirsiniz.
- **Kilidi aç**: çok sayıda hatalı deneme yüzünden kilitlenen hesabı hemen açar.
- **2FA sıfırla**: telefonunu kaybeden kişinin iki aşamalı doğrulamasını sıfırlar; kişi sonraki girişte yeniden kurar.
- **Geçici şifre** rozeti kişinin henüz kendi şifresini belirlemediğini gösterir.
- **Personel kartı**: çalışanın sicil no, birim, görev, kimlik, iletişim ve mezuniyet bilgileri ile özlük belgeleri **Personel** ekranındaki kartındadır; aylık puantaj, ücretler, bordro ve tatil takvimi aynı bölümün sekmelerindedir (Yönetim kılavuzu, "Personel", "Puantaj", "Bordro" ve "Personel maliyeti"). Hesabı açtıktan sonra kişinin kartında **Sistem kullanıcısı** olarak bu hesabı seçin. İşten ayrılan kişinin hesabını pasife alırken kartına da **İşten ayrıldı**'yı kaydedin.
- Rollerin kendisi sabittir ve `seed_roles` komutuyla oluşur; eklenmez ya da silinmez. Rollerin varsayılan yetki paketleri de sabittir: **Sistem > Rol yetkileri**'nde salt okunur görünür ve yalnızca yeni sürümle değişir.
- Bu ekrandaki her değişiklik denetim günlüğüne yazılır; şifreler günlüğe yazılmaz.
- Yönetim paneli (/admin/) yalnızca sunucunun kendisinden ve VPN'den açılır; kullanıcı işleri için gerekmez. Panelde kullanıcının rolleri, süper kullanıcı ve panele giriş işaretleri salt okunurdur; roller uygulamadaki Yetkiler sayfasından değişir. Panelde GTIN'ler, ülke kodu, birimin UN/ECE kodu ve sembolü salt okunurdur; bunları uygulamadan girin. Biçimi kodlama sistematiğinden ayarlanan ana veri türlerinde (malzeme, malzeme kategorisi, depo, lokasyon, ekipman, tedarikçi, müşteri) kod salt okunurdur ve panelden yeni kayıt açılmaz. Kullanılan birimin türü ve katsayısı panelden de uygulamadan da değiştirilemez.

## Kullanıcı yetkileri

Her rolün varsayılan bir yetki paketi vardır. Bir kişiye paketin dışında yetki ekleyebilir ya da paketteki bir yetkiyi o kişi için kaldırabilirsiniz. Kişinin yetkileri, **Sistem > Kullanıcılar** listesinde satırdaki **Yetkiler** düğmesiyle ya da kişinin adına basınca açılan sayfadadır.

![Kullanıcının yetkiler sayfası](/kilavuz/admin-yetkiler.jpg)

Sayfanın bölümleri:

- **Roller**: kişinin rolleri. Rol değişikliği yetkilerle birlikte, aynı kayıtta ve gerekçeyle kaydedilir.
- **Hassas veriler**: **Fiyatları görür** ve **Maliyetleri görür**.
- **Modül yetkileri**: her modül açılıp kapanan bir kutudur. Satırlar modülün bölümleri, sütunlar **Görür**, **Değiştirir** ve **Onaylar**'dır. Modülün başlığında modülün kişinin menüsünde olup olmadığı (**Menüde** ya da **Menüde değil**) ve varsa kaç kişiye özel ayar olduğu yazar.

Hücrenin durumu simgesinden ve yazısından anlaşılır; üzerine gelince ayrıntısı çıkar:

- **Rolden** (mavi onay işareti): yetki kişinin rolünden gelir; ipucunda hangi rol olduğu yazar.
- **Eklendi** (yeşil artı): bu kişiye özel verildi.
- **Kaldırıldı** (kırmızı eksi): rolde var ama bu kişi için kaldırıldı.
- **Verilmedi** (boş): kişide yok.
- **Kilitli** (kilit): buradan değişmez. Nedeni ipucunda yazar: herkese ya da rolü olan herkese açıktır, yalnızca sistem yöneticisindedir ya da KVKK yüzünden yalnızca yönetim rolündekilere verilebilir.
- **—**: bölümde bu düzey yok.

Hücreye basınca durumu tersine döner; ayarı olan hücreye yeniden basınca rol varsayılanına döner. Kaydedilmemiş hücrenin köşesinde sarı nokta görünür. Turuncu uyarı işareti ayarın etkisiz olduğunu gösterir (ör. rol zaten veriyor).

- **Değiştirir** ya da **Onaylar** açılınca **Görür** de açılır; **Görür** kapanınca öteki düzeyler de kapanır.
- Bir yetkinin ön koşulu eksikse o da verilir ve satırın altında yazar, ör. "Satın alma › Satın alma siparişleri: Değiştirir için Fiyatları görür de verildi."
- **Onaylar**, **Değiştirir**'den ayrıdır: kaydı giren ile onaylayan ayrı kişiler olabilir.
- Personel modülünün yetkileri (kartlar, puantaj, ücretler, bordro, ayarlar), personel maliyeti, olaylar ve kazalar ile denetim günlüğü yalnızca yönetim rolündeki kullanıcılara verilebilir (KVKK). Yönetim rolü kaldırılınca bu eklemeler biter.
- Bazı modüllerin kayıtlarını giriş yapan herkes okuyabilir. Bu modüllerin son satırı **Açık kayıtlar**'dır: **Herkes okur** ya da **Bu kişi için kapalı**. Bu satır bir kişi için yalnızca kapatılır ya da yeniden açılır. Kapatınca satırın altında kişinin bu kayıtları hangi bölümlerden okumaya devam ettiği yazar.

Toplu işlemler:

- Modül başlığındaki **Görür**, **Değiştirir** ve **Onaylar** kutuları o sütunu modülün bütün bölümlerinde açar ya da kapatır.
- Başlıktaki **⋯** menüsünde **Rol varsayılanına dön**, **Yalnız görsün** ve **Modüldeki bütün yetkileri kaldır** vardır. **Yalnız görsün**, kişinin yetkisi olan bölümlerde Görür'ü bırakır, Değiştirir ve Onaylar'ı kapatır. **Modüldeki bütün yetkileri kaldır** Açık kayıtlar satırını değiştirmez; o satır ayrıca kapatılır.
- Sayfanın üstünde **Bölüm ara** kutusu, **Yalnız kişiye özel ayarlar** anahtarı ve **Tümünü rol varsayılanına döndür** ile **Etkisiz ayarları temizle** düğmeleri vardır.

**Kaydetme**

1. Değişiklik yaptıkça altta kaydedilmemiş değişiklik sayısı çıkar. **Kaydet…**'e basın.
2. **Değişikliklerin özeti** penceresinde rol değişikliklerini, verilecek ve kaldırılacak yetkileri, menüye eklenecek ve menüden kalkacak modülleri, biten kişiye özel ayarları ve **Uyarılar**'ı okuyun. Uyarılar örneğin bir işin görevini alacak kimsenin kalmadığını, görev ayrılığını ya da hassas yetki verilen kişinin iki aşamalı doğrulamasının kurulu olmadığını söyler. Uyarılar kaydı engellemez.
3. **Değişiklik notu**'na gerekçeyi yazın (zorunlu) ve **Kaydet**'e basın.

![Kaydetmeden önceki özet](/kilavuz/admin-yetkiler-ozet.jpg)

Kaydedince kişinin açık ekranı saniyeler içinde yenilenir ve kişiye "Yetkileriniz güncellendi" bildirimi gider. Kaydetmeden sayfadan çıkmak isterseniz sorulur.

- **Geçmiş** sekmesi her kaydın tarihini, değiştireni ve gerekçesini; altında rol değişikliklerini, eklenen ve kaldırılan yetkileri ve biten kişiye özel ayarları (ör. rol varsayılanına dönen) gösterir.
- Sistem yöneticisi her ekranı görür ve her işlemi yapar; ona kişiye özel yetki uygulanmaz. Sayfasında matris yerine bu yazar.
- Kendi sayfanızda yalnızca rollerinizi değiştirebilirsiniz.

**Rol yetkileri ve Kimde var?**

**Sistem > Rol yetkileri** sekmesi rollerin varsayılan paketlerini salt okunur gösterir. Hücrelerde G (Görür), D (Değiştirir) ve O (Onaylar) harfleri, Açık kayıtlar satırında Okur yazar; **Rol** alanından tek bir rol seçebilirsiniz.

![Rol yetkileri](/kilavuz/admin-rol-yetkileri.jpg)

- Bir harfe basınca **Kimde var?** penceresi açılır: o yetkiyi taşıyan etkin kullanıcılar ve yetkinin kaynağı (ör. rolden, kişiye özel eklendi) listelenir. Rolünde olduğu hâlde kendisinden kaldırılan kişiler en sonda "Rolde var ama kaldırıldı" ile görünür.
- **Excel'e aktar** rol paketlerini, kişilerin yetkilerini, kişiye özel ayarları ve görev ayrılığını bir dosyaya aktarır; paketlerin imzalanması ve denetim için kullanılır.

![Kimde var? penceresi](/kilavuz/admin-kimde-var.jpg)

> Kullanıcı listesinde kişiye özel ayarı olan kişinin satırında **Kişiye özel: n** rozeti görünür; üzerine gelince kaç yetkinin eklendiği ve kaldırıldığı yazar. Listeyi **Rol**, **Durum** ve **Yalnız kişiye özel yetkisi olanlar** ile süzebilirsiniz.

## Sorun bildirimleri

Kullanıcı sağ üstteki **Sorun bildir** simgesiyle bildirim gönderince **Görevlerim**'e "Sorun bildirimi: SB-..." görevi düşer.

1. Görevde **Kayda git**'e basın ya da **Canlıya geçiş > Sorun bildirimleri** sekmesini açın.
2. Bildirimin sayfasında kullanıcının açıklaması, sorunun yaşandığı sayfa, tarayıcı ve ekran boyutu ile ekran görüntüsü vardır.
3. Sayfadaki bağlantıyla sorunlu ekranı açıp sorunu kendiniz deneyin.
4. Kullanıcıya kaydın altındaki yorumdan yanıt verin. `@` ile kullanıcıdan bahsederseniz bildirim alır.
5. Sorun çözülünce ya da yazılım ekibine iletilince görevde **Tamamla**'ya basın ve kısa not yazın.

![Sorun bildirimleri listesi](/kilavuz/admin-sorunlar.jpg)

![Sorun bildirimi sayfası](/kilavuz/admin-sorun.jpg)

> **Sorun bildirimleri** sekmesini yalnızca sistem yöneticisi görür. Bildiren kullanıcı yalnızca kendi bildirimini açabilir.

## Kodlama sistematiği

Ana veri kodlarının, belge ve lot numaralarının biçimi, çıktıların doküman kodu ve GS1 ayarları **Sistem > Kodlama sistematiği** ekranındadır. Bu ekranı yalnızca sistem yöneticisi görür. Biçim değişiklikleri ve kod göçleri notuyla **Geçmiş** bölümünde görünür; GS1 ve çıktı ayarlarındaki değişikliklerin notu denetim günlüğüne yazılır (GS1 bölümünde son değişiklik, çıktı penceresinde revizyonlar görünür). Değişiklik yalnızca bundan sonra verilecek kod ve numaraları etkiler; verilmiş olanlar değişmez.

![Kodlama sistematiği](/kilavuz/admin-kodlama.jpg)

**Ana veri kodları**

1. Türün satırında **Düzenle**'ye basın.
2. **Önek**'i ve **Sıra hanesi**'ni girin (ör. MLZ ve 7 hane: MLZ-0000001). Ekipmanda her ekipman türünün kendi öneki vardır.
3. **Biçimi etkinleştir**'i işaretleyin. Etkin türde yeni kayıtta kod önerilir ve biçime uymayan yeni kod kabul edilmez. Kapalı türde kod serbesttir.
4. Gerekirse **Sıradaki numara**'yı düzeltin. Dolu ya da başka kaydın eski kodu olan numara atlanır.
5. **Değişiklik notu**'nu yazın, önizlemeyi kontrol edip **Kaydet**'e basın ve onaylayın.

> Kayıt açıldıktan sonra kodu yalnızca sistem yöneticisi değiştirir. Eski kod kayıtta kalır; aramada, barkod okutmada ve Excel içe aktarmada tanınır, başka kayda verilmez. Birim ve H/P/EUH gibi uluslararası standart kodlar bu ekrandan değiştirilmez.

**Belge ve lot numaraları**

**Belge numaraları** ve **Lot numaraları** bölümlerinde önek ile yıl ya da tarih biçimi seçilir (ör. `UE-2026-00001`, `D-20261105-001`). Önek değişince sayaç yeni önekte 1'den başlar. İrsaliye numarası yasal belge numarasıdır; biçimi değiştirilemez.

**Kod göçü**

Mevcut kodları yeni biçime taşır. Önce yedek alın; ekran son yedeğin zamanını gösterir.

1. **Kod göçü** bölümünde **Kod türü**'nü seçip **Önizle**'ye basın. Biçime uyan kodlar kalır, uymayanlar oluşturulma sırasıyla sıradaki boş kodu alır.
2. Listeyi kontrol edin, **Göç notu**'nu yazın, taşı düğmesine basıp onaylayın.
3. Göç geri alınabilir: **Uygulanan göçler** listesinde **Geri al**'a basın. Kodu hâlâ göçteki yeni kod olan kayıtlar eski koduna döner.

> Göç stok miktarlarını, lot ve belge numaralarını değiştirmez. Eski kodlar aranmaya ve okutulmaya devam eder.

**Çıktılar (doküman kodu)**

Basılı çıktılara (PDF ve Excel) kalite yönetim sisteminizin doküman numarası, yayın tarihi ve revizyonu basılır.

1. **Çıktılar** bölümünde çıktıyı açın. **Doküman no**'yu ve **İlk yayın tarihi**'ni girin.
2. **Revizyonlar** altında ilk revizyonu ekleyin: revizyon no, yürürlük tarihi, değişiklik açıklaması, onaylayan ve onay tarihi. Doküman no ve ilk yayın tarihi ilk revizyonla birlikte kaydedilir; ikisi girilmeden **Revizyonu ekle** açılmaz. Eklemeden önce ikisini kontrol edin: sonra yalnız yeni revizyonla değişir, revizyona yazılan numara da başka çıktıya verilmez.
3. **Çıktıya basılsın**'ı işaretleyin, **Değişiklik notu**'nu yazıp **Kaydet**'e basın. Bant PDF'in her sayfasının altına, Excel'de yazdırma alt bilgisine basılır.

- Belge kendi tarihindeki bantla basılır; yeniden basımda da ilk basımdaki gibi: o gün yürürlükte olan revizyon ve onunla kaydedilen doküman no ve ilk yayın tarihi. Bant açılmadan önceki tarihli belge bantsız basılır; bandı sonradan kapatmak, önceki günlerde açıkken tarihlenen belgelerin yeniden basımını değiştirmez. Bant ve revizyon değişikliği o günün tamamına uygulanır: bandı açtığınız ya da kapattığınız, revizyon girdiğiniz gün tarihli belge, değişiklikten önce basılmış olsa da yeniden basımda yeni durumla basılır. Bu yüzden bandı gün başında, o gün belge basılmadan açın.
- İlk revizyondan sonra doküman no ve ilk yayın tarihi yalnız yeni revizyonla değişir: revizyon formunda kayıttakilerle gelir, değiştirdiğiniz değer o revizyonla yürürlüğe girer. Yanlış numarayı da böyle düzeltin. Yanlış numara o çıktının revizyonunda kalır: bir çıktının revizyonuna yazılmış numara, bant hiç açılmamış olsa da, başka çıktıya verilmez.
- Geriye tarihli girdiğiniz revizyon, girdiğiniz günden önceki tarihli belgelere basılmaz.
- Revizyonlar değiştirilemez ve silinemez. Tarihler 01.01.2000'den önce olamaz.

> **Şablon değişti** uyarısı görürseniz değişikliği kalite sisteminizde onaylayıp yeni revizyon girin. İrsaliyede bandı açmadan önce mali müşavirinize danışın.

**GS1**

GS1 firma öneki palet etiketindeki SSCC numarasında ve mamullerin GTIN önerisinde kullanılır.

1. **GS1** bölümünde **Düzenle**'ye basın.
2. GS1 Türkiye'nin verdiği **Firma öneki**'ni girin. Önek girilince palet etiketi (SSCC) açılır.
3. GTIN önerisi için **Sıradaki ürün referansı**'nı girin: önekten sonraki ilk boş ürün numarası. Kullanılmış GTIN'ler atlanır.
4. **SSCC uzantı hanesi** genelde 0 kalır.
5. **Değişiklik notu**'nu yazıp kaydedin. Önek değişirse onay sorulur.

![GS1 ayarları](/kilavuz/admin-kodlama-gs1.jpg)

> Basılmış bir SSCC hiçbir zaman yeniden verilmez; eski öneke dönülse de SSCC çakışmaz. Önek değişince ürün referansı silinir; yeni önekteki ilk boş referansı girin.

## Etiket yazıcıları

1. **Ana veriler > Yazıcılar** sekmesinde **Yeni**'ye basın.
2. **Kod**, **Ad**, **IP adresi**, **Port** (Zebra yazıcılarda genelde 9100), **Çözünürlük (dpi)** ve yazıcının durduğu **Lokasyon**'u girip kaydedin.
3. Satırdaki **Deneme etiketi** simgesine basın. Yazıcıdan deneme etiketi çıkmalıdır.
4. Çalışmayan ya da kaldırılan yazıcıyı pasife alın.

**Ana veriler > Etiket ayarları** sekmesinde **Etikette firma adı** ve **Varsayılan yazıcı** girilir. GS1 firma öneki ve SSCC bilgisi burada yalnızca görünür; **Sistem > Kodlama sistematiği > GS1**'de değiştirilir.

![Etiket ayarları](/kilavuz/admin-etiket-ayarlari.jpg)

> Yazıcı tanımlı değilse etiketler PDF olarak basılır. Lokasyon etiketleri **Ana veriler > Lokasyonlar** sekmesindeki yazıcı simgesiyle basılır. Lot ya da lokasyon kodunda Türkçe harf ya da > varsa etikete çizgi barkod basılmaz, etiketteki QR kodu okutulur. Fabrikadaki Zebra yazıcıda bunu bir kez deneyin: deneme baskısı KURULUM belgesinin 3. bölümündedir.

## Diğer yönetici işleri

- **Elle serbest bırak**: Lot sayfasında yalnızca yöneticiye görünür. Olağan serbest bırakma laboratuvar kararıyla yapılır; bu düğme istisnai durumlar içindir ve gerekçe denetim günlüğüne yazılır. Dolum partisi ya da üretim şarjı bitmemiş (ya da iptal edilmiş) lot elle de serbest bırakılamaz.
- **Dolumu geri al**: Dolum emri sayfasında size ve **Dolum emrini geri alma** yetkisi olanlara (varsayılan: yönetim) görünür. Fabrikada fiilen yapılmamış dolumu geri alır: emrin stok hareketleri ters kayıtla geri alınır, partiler ve açık numuneler iptal edilir, emir iptal olur. Dolum lotu serbest bırakılmış ya da başka işlemde kullanılmışsa reddedilir. Ayrıntısı yönetim kılavuzunun "Dolumu geri alma" bölümündedir.
- **Canlıya geçiş > Hazırlık** listesindeki "Kullanıcılar" ve "Etiket yazıcıları" maddeleri sizin sorumluluğunuzdadır.
- **Birimler**: **Ana veriler > Birimler** sekmesini yalnızca sistem yöneticisi yazar. Her birimin uluslararası **UN/ECE kodu** (KGM, LTR, C62; koli XCT, palet XPX) ve **Sembol**'ü vardır.
- Kullanıcı bir ekranı göremediğini söylerse kişinin **Yetkiler** sayfasına bakın: rolleri ve kişiye özel eklenen ya da kaldırılan yetkiler orada görünür. Kişinin gördüğü **Yetkiniz yok** sayfası gereken yetkiyi yazar; **Sistem > Rol yetkileri**'nde o yetkinin harfine basınca **Kimde var?** onu kimlerin taşıdığını listeler.
