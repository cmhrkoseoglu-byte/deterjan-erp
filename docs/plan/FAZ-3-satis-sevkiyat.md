# Faz 3 — Satış siparişi, sevkiyat ve izlenebilirlik

**Amaç:** "Üretimden sevkiyata" zincirini tamamlamak: müşteri siparişi, stok rezervasyonu, lot okutarak
yükleme, irsaliye, iade ve tam izlenebilirlik (geri çağırma) raporu.

Ön koşul: Faz 2 kabul kriterleri tamam.

---

## Adım 3.1 — `sales`: müşteri siparişi

**`SalesOrder`** (`DocumentModel`, numara `SS-`)
- `customer`, `order_date`, `requested_delivery_date`, `delivery_address`, `customer_po_no` (müşteri sipariş no), `notes`
- Durumlar: `DRAFT` → `CONFIRMED` → `PARTIALLY_SHIPPED` → `SHIPPED` → `CLOSED` (+ `CANCELLED`)

**`SalesOrderLine`**: `order`, `product` (FINISHED), `quantity` + `unit` (ADET / KOLI / PALET → temel birime çevrilir),
`shipped_quantity` (hesaplanır), `unit_price` + `currency` (opsiyonel; fiyatlandırma muhasebede ise boş kalabilir — Karar D-9).

**`StockReservation`**: `order_line`, `lot`, `location`, `quantity`, `status` (`ACTIVE` | `CONSUMED` | `RELEASED`).
- Rezervasyon stok hareketi değildir; `available = balance − aktif rezervasyonlar`.
- `inventory.selectors.available_lots` rezervasyonları düşecek şekilde güncellenir.
- Sipariş onayında (`CONFIRMED`) FEFO ile otomatik rezervasyon önerisi; yetersizse olay `sales_order.shortage` → planlamaya görev "Üretim/dolum planla".

## Adım 3.2 — Sevkiyat

**`Shipment`** (`DocumentModel`, numara `SV-`)
- `sales_order` (bir sevkiyat bir siparişe bağlı; ileride çoklu sipariş — Karar D-10), `planned_date`,
  `vehicle_plate`, `driver_name`, `driver_id_no` (KVKK: maskeli gösterim), `carrier`
- Durumlar: `PLANNED` → `PICKING` → `LOADED` → `DISPATCHED` (+ `CANCELLED`)

**`ShipmentLine`**: `shipment`, `order_line`, `lot`, `quantity`, `picked_by`, `picked_at`.
- Toplama **lot okutarak** yapılır; sadece `RELEASED` ve SKT'si geçmemiş lot; rezervasyondan farklı lot okutulursa uyarı + gerekçe.
- Asgari kalan raf ömrü kuralı: müşteri bazında `Customer.min_remaining_shelf_life_days` (ör. 180 gün) — altındaki lot engellenir.
- `DISPATCHED` olduğunda: `SHIPMENT` hareketleri (sevk lokasyonundan çıkış), rezervasyonlar `CONSUMED`,
  sipariş durumu güncellenir, olay `shipment.dispatched`.

**İrsaliye**: `GET /api/v1/sales/shipments/{id}/waybill.pdf` — firma bilgileri, müşteri, araç/şoför, satırlar
(ürün, lot, SKT, miktar, koli). e-İrsaliye entegrasyonu Faz 5'te; bu fazda PDF ve dışa aktarım verisi hazır olsun.

**İş akışı kuralları**

| Olay | Aksiyon | Hedef |
|---|---|---|
| `sales_order.confirmed` | Görev: "Sevkiyat planla: {SS no}" | sevkiyat |
| `sales_order.shortage` | Görev: "Eksik ürün için üretim/dolum planla" | planlama |
| `shipment.planned` | Görev: "Toplama yap: {SV no}" | depo |
| `shipment.loaded` | Görev: "Sevki onayla / irsaliye kes" | sevkiyat |
| `shipment.dispatched` | Bildirim: "Sevk edildi" | siparişi oluşturan kullanıcı, yonetim |
| `lot.expiring` (rezerve lotta) | Bildirim (WARNING) | sevkiyat, planlama |

## Adım 3.3 — İade

**`CustomerReturn`** (`DocumentModel`, numara `IA-`): `customer`, `shipment` (opsiyonel), `reason`, satırlar (ürün, lot, miktar).
- İade edilen ürün `RETURN` hareketiyle **karantina** lokasyonuna girer; laboratuvara `INCOMING`-benzeri numune
  (`stage=RETURN`) açılır. Karar: yeniden sevke uygun (RELEASED) / yeniden işleme (REWORK) / imha (SCRAP).
- Aynı lot numarası korunur (lot bazında "iade edildi" izi hareketlerden okunur).

## Adım 3.4 — İzlenebilirlik ve geri çağırma

- **Geri izleme raporu** (mamul lot → dolum → bulk lot → hammadde lotları → tedarikçi + tedarikçi lot no + mal kabul belgesi).
- **İleri izleme raporu** (hammadde lotu → kullanıldığı şarjlar → bulk lotlar → dolum lotları → sevkiyatlar → müşteriler, miktarlarıyla).
- **Geri çağırma simülasyonu**: bir veya birden fazla lot seç → etkilenen müşteriler, sevk edilen miktarlar,
  hâlâ stokta olan miktarlar, Excel/PDF çıktı. Hedef: 1 dakikanın altında sonuç.
- Raporlar `inventory.selectors.lot_trace_*` üzerine kurulur; derin ağaçlarda performans testi (≥ 5 seviye, ≥ 10.000 hareket).

## Adım 3.5 — Ekranlar

| Ekran | Kullanıcı |
|---|---|
| Satış siparişleri (liste, oluştur, onay, rezervasyon görünümü) | sevkiyat, yonetim |
| Sevkiyat planlama | sevkiyat |
| **Toplama tablet ekranı** (lot okut, kalan miktar, FEFO önerisi, raf ömrü uyarısı) | depo |
| Yükleme onayı ve irsaliye | sevkiyat |
| İadeler | sevkiyat, laboratuvar |
| İzlenebilirlik / geri çağırma | laboratuvar, yonetim |
| Müşteri kartında: sipariş geçmişi, sevk edilen lotlar | sevkiyat, yonetim |

---

## Kabul kriterleri

- [ ] Uçtan uca test: mal kabul → … → mamul lot serbest → sipariş → rezervasyon → toplama → sevk → irsaliye PDF.
- [ ] Rezerve stok başka siparişe ayrılamıyor; `available` hesabı doğru (test).
- [ ] Karantina / SKT geçmiş / raf ömrü yetersiz lot sevk edilemiyor (test).
- [ ] İade karantinaya giriyor ve QC kararıyla yönleniyor (test).
- [ ] Bir hammadde lotunun ileri izlemesi doğru müşterileri ve miktarları veriyor; geri izleme tedarikçiye kadar iniyor (test).
- [ ] Geri çağırma simülasyonu 10.000 hareketlik demo veride 1 sn altında (performans testi).
- [ ] Stok değişmezleri tüm yeni testlerde geçiyor.

## Bu fazda kullanıcıya sorulacak kararlar

- **D-9** Satış fiyatı / fatura bu sistemde mi tutulacak, yoksa sadece muhasebe programında mı?
- **D-10** Bir araca birden fazla müşterinin siparişi yükleniyor mu?
- **D-11** Müşteri bazında asgari raf ömrü şartı var mı (zincir marketler genelde ister)?
