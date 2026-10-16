# Faz 4 — Satın alma, maliyet, bakım, İSG ve raporlama

**Amaç:** Ana zincir çalıştıktan sonra yönetimin ihtiyaç duyduğu destek modüllerini eklemek. Bu fazın
adımları birbirinden bağımsızdır; **öncelik sırasını kullanıcıya sor** (Karar D-12). Önerilen sıra:
maliyet → satın alma → raporlama → bakım → İSG.

Ön koşul: Faz 3 kabul kriterleri tamam.

---

## Adım 4.1 — `costing` (maliyet)

**Yaklaşım:** Fiili maliyet, lot bazında. Ayrı bir muhasebe değil; üretim maliyetinin izlenmesi.

- **Hammadde/ambalaj lot maliyeti**: mal kabul satırındaki `unit_price` (ve varsa nakliye/gümrük payı:
  `GoodsReceipt.extra_costs` → satırlara miktar ya da tutar oranında dağıtılır). `Lot.unit_cost` alanı.
  Fiyatı olmayan lot için malzemenin son bilinen maliyeti / standart maliyeti kullanılır ve "tahmini" işaretlenir.
- **Bulk lot maliyeti** = Σ(tüketilen lot miktarı × lot birim maliyeti) + (opsiyonel) genel gider payı
  (`CostRate`: şarj başı sabit veya kg başı — enerji, işçilik, amortisman) ÷ gerçek çıktı miktarı.
- **Dolum lot (mamul) maliyeti** = bulk tüketimi maliyeti + ambalaj tüketimi maliyeti + fire maliyeti + dolum gider payı ÷ iyi adet.
- Maliyet, lot oluşurken/şarj bittiğinde hesaplanır ve **saklanır** (`LotCost`: kalem kalem döküm), sonradan
  fiyat değişirse yeniden hesaplama ayrı bir işlemdir (sürüm notuyla).
- Raporlar: ürün bazında birim maliyet trendi, şarj bazında reçete (teorik) vs fiili maliyet, fire maliyeti,
  en pahalı hammadde kalemleri, stok değeri (lot maliyetiyle).
- Yetki: maliyet verilerini sadece `yonetim` ve `admin` görür (diğer roller miktarı görür, tutarı görmez).

## Adım 4.2 — `purchasing` (satın alma)

- **`PurchaseRequest`** (`ST-`): talep eden, malzeme, miktar, ihtiyaç tarihi, gerekçe. Kaynak: manuel veya
  otomatik (minimum stok altı / planlanan üretim emirlerinin ihtiyaçları — basit MRP: açık emir ihtiyaçları − serbest stok − açık siparişler).
- **`PurchaseOrder`** (`SA-`): tedarikçi, satırlar (malzeme, miktar, birim fiyat, para birimi, teslim tarihi), durumlar
  `DRAFT` → `APPROVED` → `SENT` → `PARTIALLY_RECEIVED` → `RECEIVED` / `CANCELLED`. Onay limiti tutara göre (Karar D-13).
- Mal kabul (`GoodsReceipt`) satın alma siparişine bağlanabilir; bekleyen miktar otomatik düşer, fiyat siparişten gelir.
- Tedarikçi performansı: zamanında teslim oranı, QC red oranı (Faz 2 verisinden).
- Satın alma siparişi PDF'i; e-posta ile gönderim (kullanıcı onaylı).
- İş akışı: `purchase_request.created` → satin_alma görevi; `purchase_order.approved` → depoya "beklenen teslimat" bilgisi;
  `lot.rejected` → satin_alma bildirimi (tedarikçi iadesi süreci).

## Adım 4.3 — `reporting` (panolar ve raporlar)

- **Yönetim panosu**: bugünkü/haftalık üretim (kg ve adet), açık emirler ve durumları, QC bekleyen lot sayısı ve
  bekleme süresi, fire oranı, kritik stoklar, SKT yaklaşan lotlar, gecikmiş görevler (birim bazında).
- **Birim panoları**: depo (bekleyen hazırlama/toplama), laboratuvar (numune kuyruğu), üretim (tank doluluk/durum), sevkiyat.
- **Raporlar** (filtreli, Excel ve PDF çıktılı): stok durumu, stok hareketleri, üretim raporu (verim, sapmalar),
  dolum raporu (teorik/gerçek), QC raporu (red oranları, spec dışı sonuçlar), sevkiyat raporu, görev süreleri
  (hangi adım ne kadar bekliyor — süreç darboğazı analizi).
- Ağır raporlar Celery ile arka planda üretilir; hazır olunca bildirim + indirme bağlantısı.

## Adım 4.4 — `maintenance` (bakım)

- `MaintenancePlan`: ekipman, tür (periyodik / temizlik / kalibrasyon), periyot (gün veya çalışma sayısı), kontrol listesi.
- `MaintenanceWorkOrder` (`BK-`): plan veya arıza kaynaklı, durumlar, yapılan iş, kullanılan yedek parça (opsiyonel stok), süre.
- `Downtime`: ekipman, başlangıç-bitiş, neden kodu. Duruşta ekipman üretim emrine atanamaz.
- **Ürün değişimi temizliği**: bir tankta farklı ürün (veya renk/parfüm) üretilecekse önce temizlik kaydı zorunlu
  (kural tanımı: hangi geçişte temizlik gerekir — Karar D-14).
- Kalibrasyon: terazilerin kalibrasyon tarihi geçmişse tartım ekranında uyarı/engel.
- Celery Beat: yaklaşan bakımlar için görev.

## Adım 4.5 — `hse` (İSG ve çevre)

- **GBF (Güvenlik Bilgi Formu) arşivi**: malzeme başına geçerli GBF dosyası, revizyon tarihi, geçerlilik; eksik/eskimiş GBF raporu.
- Tehlike sınıfları (H/P ifadeleri) malzeme kartında; tehlikeli malzeme lotlarında arayüzde uyarı simgesi.
- Lokasyon bazında tehlikeli madde **depolama limitleri** (ör. yanıcı max X kg); mal kabul/transferde limit aşımı uyarısı.
- **Atık kayıtları**: atık kodu, miktar, lisanslı firma, teslim tarihi, belge eki.
- Olay/kaza kayıtları (`Incident`) — basit form ve takip.

---

## Kabul kriterleri

- [ ] Bulk ve mamul lot maliyeti kalem kalem doğru hesaplanıyor (elle hesaplanmış örnekle test).
- [ ] Maliyet tutarları yetkisiz role API'de dönmüyor (test).
- [ ] Minimum stok ve açık emir ihtiyaçlarından satın alma talebi öneriliyor (test).
- [ ] Satın alma siparişine bağlı mal kabul bekleyen miktarı doğru düşüyor (test).
- [ ] Yönetim panosu 2 sn altında açılıyor (demo verisiyle).
- [ ] Kalibrasyonu geçmiş terazi / temizliği yapılmamış tank kuralları çalışıyor (test).
- [ ] Stok değişmezleri tüm yeni testlerde geçiyor.

## Bu fazda kullanıcıya sorulacak kararlar

- **D-12** Bu fazdaki modüllerin öncelik sırası.
- **D-13** Satın alma onay limitleri ve onaylayanlar.
- **D-14** Hangi ürün geçişlerinde tank temizliği zorunlu?
- **D-15** Genel gider (enerji, işçilik) maliyete dahil edilsin mi, nasıl dağıtılsın?
