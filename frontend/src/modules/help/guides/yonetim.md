# Yönetim

Yönetim; panolardan fabrikanın durumunu izler, kendi onayını gerektiren kararları (şartlı kabul, limit üstü satın alma) verir, maliyet oranlarını tutar ve canlıya geçiş tarihini belirler.

## Panolar ve raporlar

1. **Panolar ve raporlar > Panolar** sekmesinde **Yönetim panosu** açılır: bugünkü ve haftalık üretim, QC bekleyen lotlar, fire oranı, kritik stok, gecikmiş görevler, bakım, İSG olayları ve stok değeri.
2. Birim panoları için **Depo**, **Laboratuvar**, **Üretim** ve **Sevkiyat** düğmelerine basın.
3. Güncel rakamlar için **Yenile**'ye basın.
4. **Raporlar** sekmesinde raporu seçin, süzgeçleri doldurun ve **Excel** ya da **PDF** alın.
5. Büyük raporlar arka planda hazırlanır. Hazır olunca bildirim gelir; dosyayı **İndirmeler** sekmesinden alın. Dosyalar 7 gün saklanır.

![Yönetim panosu](/kilavuz/yonetim-pano.jpg)

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

## Canlı başlangıç tarihi

1. **Canlıya geçiş > Hazırlık** sekmesinde kontrol kartlarını gözden geçirin. Kırmızı maddeler kapanmadan başlanmaz.
2. Sayım günü açılış stoku yüklenip kontrol edilince **Canlı başlangıç tarihi** alanına ilk canlı iş gününü yazın.
3. **Kaydet**'e basın. O tarihten sonra açılış stoku yüklenemez; farklar **Sayım düzeltme** ile girilir.

![Canlıya geçiş hazırlık listesi](/kilavuz/gecis-hazirlik.jpg)

Ayrıntılı plan **Canlıya geçiş ve sayım günü** kılavuzundadır.

## Diğer görevler

- **İSG olayı**: Bildirilen kaza ve ramak kala olayları size görev olarak gelir. **İSG ve çevre** menüsünde olayı inceleyip kapatın.
- **Siparişler ve ana veriler**: Yönetim satış siparişi açabilir, ana verileri düzenleyebilir ve tüm ekranları okuyabilir.
