# Faz 1 — Ana veriler, reçete, stok/lot, üretim ve iş akışı (MVP)

**Amaç:** Hammaddenin fabrikaya girişinden bulk (dökme) ürünün üretilmesine kadar olan zinciri sistemde
çalıştırmak. Bu fazın sonunda: mal kabul yapılır, lotlar oluşur, üretim emri açılır, depo malzeme hazırlar,
operatör tartarak şarjı üretir, stok ve lot soy ağacı doğru tutulur, her adımda ilgili birime görev düşer.

Ön koşul: Faz 0 kabul kriterleri tamam. `CLAUDE.md` §4 değişmez kurallarını tekrar oku.

---

## Adım 1.1 — `masterdata`

Tüm modeller `MasterDataModel`'den türer, `code` alanı benzersizdir ve büyük harfe çevrilir.

**`UnitOfMeasure`**: `code` (KG, G, LT, ML, ADET, KOLI, PALET), `name`, `kind` (`MASS` | `VOLUME` | `COUNT`),
`factor_to_kind_base` (aynı tür içinde: G→KG = 0.001, ML→LT = 0.001).

**`Material`**
- `code`, `name`, `material_type`: `RAW` (hammadde), `PACKAGING` (ambalaj), `BULK` (yarı mamul / dökme deterjan), `FINISHED` (mamul)
- `base_unit` (FK UoM) — stok bu birimde tutulur
- `density` (Decimal, g/ml, opsiyonel; kg↔lt dönüşümü için)
- `shelf_life_days` (opsiyonel; lot SKT'si için varsayılan)
- `min_stock` (temel birimde, opsiyonel)
- `requires_incoming_qc` (bool, varsayılan True — RAW ve BULK için; PACKAGING için False olabilir)
- `is_hazardous` (bool), `storage_notes` (metin)
- `category` (FK `MaterialCategory`, opsiyonel: ör. "Yüzey aktif", "Parfüm", "Boya", "Şişe")

**`MaterialUnitConversion`**: `material`, `unit`, `factor_to_base` (1 KOLI = 12 ADET gibi malzemeye özel).

**`Warehouse`**: `code`, `name`.
**`Location`**: `warehouse`, `code`, `name`, `location_type`: `STORAGE` | `QUARANTINE` | `PRODUCTION` | `SHIPPING` | `TANK`.
Tanklar aynı zamanda lokasyondur (üretilen bulk ürün tankta durur).

**`Equipment`**: `code`, `name`, `equipment_type`: `MIXING_TANK` | `STORAGE_TANK` | `FILLING_LINE` | `SCALE` | `OTHER`,
`capacity` + `capacity_unit`, `location` (FK Location, tanklar için zorunlu).

**`Supplier`** / **`Customer`**: `code`, `name`, `tax_office`, `tax_number`, `address`, `phone`, `email`, `contact_person`.

**Servisler**
- `convert_quantity(material, qty, from_unit, to_unit) -> Decimal` — malzemeye özel dönüşüm, aynı tür
  içi faktör, MASS↔VOLUME için `density`. Dönüşüm yoksa `BusinessRuleError("no_conversion")`.
- Oluştur/güncelle/pasifleştir servisleri (denetim günlüklü).

**İçe aktarma (Excel'den geçiş)**
- `POST /api/v1/masterdata/import/materials/` — `.xlsx` / `.csv` yükle, önce **önizleme** (satır bazlı
  hata listesi), sonra onayla. Aynı yapı tedarikçi ve müşteri için.
- İndirilebilir şablon dosyaları: `GET /api/v1/masterdata/import/templates/<tür>/`.

## Adım 1.2 — `recipes` (sürümlü formülasyon)

**`Recipe`**: `code`, `name`, `product` (FK Material, `BULK` olmalı), `notes`.

**`RecipeVersion`**
- `recipe`, `version_no` (1, 2, 3…), `status`: `DRAFT` → `APPROVED` → `OBSOLETE`
- `batch_size` (Decimal) + `batch_unit` (reçetenin hangi miktar için yazıldığı, ör. 1000 KG)
- `approved_by`, `approved_at`, `change_note` (bu sürümde ne değişti)
- Kural: Bir reçetenin aynı anda **tek** `APPROVED` sürümü olur. Yeni sürüm onaylanınca eskisi `OBSOLETE`.
- Kural: `APPROVED` ya da `OBSOLETE` sürüm ve satırları değiştirilemez. Değişiklik = "sürümü kopyala" → yeni `DRAFT`.

**`RecipeLine`**
- `version`, `sequence` (ekleme sırası), `material` (RAW veya BULK), `quantity` + `unit`
- `tolerance_pct` (tartım toleransı, varsayılan 2.0)
- `instruction` (ör. "Karıştırıcı 300 devirde, yavaşça ekle")
- `is_water` (bool — şebeke suyu stoktan düşülmeyebilir; bkz. Karar D-1)

**`RecipeStep`** (opsiyonel proses adımları): `version`, `sequence`, `description`, `duration_min`, `temperature_c`, `mixer_rpm`.

**Servisler**: `create_version`, `copy_version`, `approve_version(actor)` (rol: `planlama` veya `laboratuvar`),
`scale_requirements(version, target_qty, target_unit) -> list[(material, qty_in_base_unit, tolerance)]`.

## Adım 1.3 — `inventory` (lot + hareket defteri)

**`Lot`**
- `lot_no` (unique per material), `material`
- `status`: `QUARANTINE` | `RELEASED` | `REJECTED` | `BLOCKED`
- `source`: `PURCHASE` | `PRODUCTION` | `FILLING` | `OPENING` | `RETURN`
- `supplier`, `supplier_lot_no` (satın almada), `manufactured_at`, `expiry_date`
- `released_by`, `released_at`, `status_note`
- Lot numarası kuralı (Karar D-2'ye bakılacak, varsayılan): satın alma `H-YYMMDD-NNN`, üretim `B-YYMMDD-NNN`, dolum `D-YYMMDD-NNN`.

**`StockMovement`** (değiştirilemez)
- `movement_type`: `OPENING` | `RECEIPT` | `ISSUE_PRODUCTION` | `PRODUCTION_OUTPUT` | `TRANSFER_OUT` | `TRANSFER_IN` | `ADJUSTMENT` | `SCRAP` | `SHIPMENT` | `RETURN` | `REVERSAL`
- `material`, `lot`, `location`, `quantity` (işaretli, temel birimde: giriş +, çıkış −)
- `source_content_type` + `source_object_id` (hangi belge), `document_number` (okunabilirlik için)
- `reversal_of` (FK self, null), `transfer_group` (UUID, null), `note`, `created_by`, `created_at`
- Model `save()` güncellemeyi, `delete()` silmeyi engeller.

**`StockBalance`**: `material`, `lot`, `location`, `quantity`; `unique(material, lot, location)`; `quantity >= 0` CHECK kısıtı.

**`LotLink`** (soy ağacı): `parent_lot` (girdi), `child_lot` (çıktı), `quantity` (girdi lottan kullanılan, temel birim),
`source_content_type/object_id`. 

**`GoodsReceipt`** (`DocumentModel`, numara `MK-`): `supplier`, `receipt_date`, `delivery_note_no` (irsaliye no),
`status`: `DRAFT` → `POSTED` | `CANCELLED`. Satırlar **`GoodsReceiptLine`**: `material`, `quantity` + `unit`,
`supplier_lot_no`, `expiry_date`, `manufactured_at`, `unit_price` (opsiyonel, Faz 4 maliyet için), `created_lot` (FK Lot).

**`StockAdjustment`** (`DocumentModel`, numara `SD-`): sayım farkı / düzeltme. Satırlar: lot, lokasyon, sistem miktarı,
sayılan miktar, fark, `reason` (zorunlu). Onay rolü: `depo` + `yonetim` (Karar D-3).

**Servisler** (hepsi `transaction.atomic`)
- `post_movement(actor, material, lot, location, quantity, movement_type, source, note="") -> StockMovement`
  — bakiyeyi `select_for_update` ile günceller, negatife düşmeyi engeller. **Stoka dokunmanın tek yolu.**
- `transfer(actor, lot, from_location, to_location, quantity, source)` — iki hareket + ortak `transfer_group`.
- `reverse_movement(actor, movement, reason)`.
- `post_goods_receipt(actor, receipt)` — her satır için lot oluşturur (`requires_incoming_qc` ise `QUARANTINE`,
  değilse `RELEASED`), `RECEIPT` hareketi ile karantina (veya depo) lokasyonuna alır. Olay: `goods_receipt.posted`.
- `release_lot(actor, lot, note)` / `reject_lot(actor, lot, note)` / `block_lot(...)` — rol: `laboratuvar`.
  Serbest bırakılan lot karantinadan depoya transfer edilir (hedef lokasyon parametre). Olaylar: `lot.released`, `lot.rejected`.
- `post_stock_adjustment(actor, adjustment)`.
- `post_opening_balance(...)` + Excel içe aktarma (açılış stoku; lot no, SKT, lokasyon, miktar).

**Selectors**
- `stock_by_material(material)`, `stock_by_location(location)`, `available_lots(material, fefo=True)` (sadece RELEASED, SKT'ye göre sıralı)
- `lot_trace_backward(lot) -> ağaç`, `lot_trace_forward(lot) -> ağaç` (özyinelemeli CTE ile)
- `expiring_lots(days)`, `below_min_stock()`

## Adım 1.4 — `production`

**`ProductionOrder`** (`DocumentModel`, numara `UE-`)
- `product` (BULK), `recipe_version` (APPROVED olmalı — oluşturma anında sabitlenir), `planned_quantity` + `unit`,
  `planned_date`, `equipment` (MIXING_TANK), `priority`, `notes`
- Durumlar ve geçişler (`state.py`):
  ```
  DRAFT ─► APPROVED ─► MATERIAL_PREP ─► MATERIAL_READY ─► IN_PRODUCTION ─► QC_PENDING ─► COMPLETED
    │          │              │
    └──────────┴──────────────┴──► CANCELLED   (MATERIAL_PREP'ten iptalde hazırlanan malzeme geri transfer edilir)
  ```
  Olay her geçişte: `production_order.<durum>` (ör. `production_order.approved`).

**`ProductionRequirement`** (emir onaylanınca reçeteden ölçeklenerek oluşur): `order`, `recipe_line`, `material`,
`required_quantity` (temel birim), `tolerance_pct`, `sequence`.

**`MaterialPick`** (depo hazırlığı): `order`, `requirement`, `lot`, `quantity`, `from_location`, `picked_by`, `picked_at`.
Depo lot okutarak hazırlar; sistem FEFO önerir; sadece RELEASED lot seçilebilir. Hazırlanan malzeme
`transfer` ile üretim lokasyonuna (ör. tank başı) taşınır. Tüm ihtiyaçlar karşılanınca `MATERIAL_READY`.

**`ProductionBatch`** (şarj) — bir emir bir veya daha fazla şarjdan oluşabilir
- `order`, `batch_no` (= çıktı lot numarası), `equipment`, `status`: `IN_PROGRESS` | `COMPLETED` | `CANCELLED`
- `started_at`, `started_by`, `finished_at`, `finished_by`, `actual_output_quantity`, `output_lot` (FK Lot)

**`BatchConsumption`** (tartım kaydı)
- `batch`, `requirement`, `lot`, `planned_quantity`, `actual_quantity`, `weighed_by`, `weighed_at`
- `deviation_pct` (hesaplanır), `deviation_note` (tolerans dışıysa **zorunlu**)
- Kayıt anında: `ISSUE_PRODUCTION` hareketi + `LotLink(parent=girdi lot, child=output_lot)`.

**Servisler**
- `create_order`, `approve_order` (rol: `planlama`) → ihtiyaçları oluşturur.
- `start_material_prep`, `pick_material(actor, requirement, lot, qty)` (rol: `depo`), `mark_material_ready`.
- `start_batch(actor, order, equipment)` (rol: `uretim`) → çıktı lotu `QUARANTINE` olarak oluşturulur.
- `record_consumption(actor, batch, requirement, lot, actual_qty, note)` → tolerans dışıysa olay `production.deviation`.
- `finish_batch(actor, batch, output_qty)` → `PRODUCTION_OUTPUT` hareketi (tank lokasyonuna), emir `QC_PENDING`, olay `production_batch.completed`.
- `complete_order` — çıktı lotu `RELEASED` olunca (Faz 1'de `release_lot` sonrası) emir `COMPLETED`.
- Verim: `yield_pct = actual_output / planned_quantity`; düşük verimde (eşik ayarlanabilir, varsayılan %97) olay `production.low_yield`.

## Adım 1.5 — `workflow` (haberleşme)

**`Task`**
- `title`, `description`, `assigned_role` (FK Group, null), `assigned_user` (FK User, null) — en az biri dolu
- `status`: `OPEN` | `IN_PROGRESS` | `DONE` | `CANCELLED`, `priority`, `due_at`
- `related_content_type` + `related_object_id` (hangi kayıt), `event_name` (hangi olaydan doğdu), `rule_code`
- `claimed_by` (role atanmış görevi üstlenen kişi), `completed_by`, `completed_at`
- Görevler **otomatik kapanır**: ilgili adımı tamamlayan olay geldiğinde (ör. `production_order.material_ready`
  gelince "Malzeme hazırla" görevi `DONE`).

**`Notification`**: `recipient` (User), `title`, `body`, `level` (`INFO` | `WARNING` | `CRITICAL`),
`related_*` (GenericFK), `task` (FK, null), `read_at`, `created_at`.
Role giden bildirim, o roldeki tüm aktif kullanıcılara ayrı kayıt olarak yazılır.

**`Comment`**: `related_*` (GenericFK), `author`, `body`, `mentions` (M2M User), `created_at`, `edited_at`.
`@kullanıcı` bahsedilenlere bildirim gider. Yorum silinmez; düzenlenirse eski hali denetim günlüğüne yazılır.

**Kural tablosu** (`workflow/rules.py`, kodda tanımlı, test edilebilir):

| Olay | Aksiyon | Hedef | Kapanış olayı |
|---|---|---|---|
| `goods_receipt.posted` (QC gereken lot varsa) | Görev: "Giriş kontrolü: {lot}" | laboratuvar | `lot.released` / `lot.rejected` |
| `lot.rejected` | Bildirim (WARNING) | depo, satin_alma | — |
| `production_order.approved` | Görev: "Malzeme hazırla: {UE no}" | depo | `production_order.material_ready` |
| `production_order.material_ready` | Görev: "Şarjı başlat: {UE no}" | uretim | `production_batch.started` |
| `production.deviation` | Bildirim (WARNING) | planlama, laboratuvar | — |
| `production_batch.completed` | Görev: "Numune analizi: {lot}" | laboratuvar | `lot.released` / `lot.rejected` |
| `lot.released` (BULK) | Bildirim | planlama, uretim | — |
| `production.low_yield` | Bildirim (WARNING) | planlama, yonetim | — |
| `production_order.cancelled` | Açık görevleri iptal et + bildirim | ilgili roller | — |

**Anlık iletim**: Django Channels; kullanıcı başına grup `user_<id>`. Yeni bildirim/görevde WebSocket mesajı.
WebSocket yoksa frontend 30 sn'de bir `unread-count` sorgular (yedek).

**Zamanlanmış kontroller (Celery Beat)**: her sabah 07:00 SKT'si 30 gün içinde dolacak lotlar ve minimum
stok altı malzemeler için bildirim (`depo`, `planlama`).

## Adım 1.6 — API

`/api/v1/` altında, her modül kendi `urls.py`'si ile. Listeler sayfalı ve filtreli. Durum geçişleri
ayrı aksiyon uç noktalarıdır (PATCH ile `status` değiştirilemez):

```
masterdata/  materials, units, categories, warehouses, locations, equipment, suppliers, customers, import/…
recipes/     recipes, recipes/{id}/versions, versions/{id}/copy|approve, versions/{id}/scale?qty=&unit=
inventory/   lots, lots/{id}/release|reject|block, lots/{id}/trace?direction=backward|forward,
             movements (salt okunur), balances, goods-receipts, goods-receipts/{id}/post,
             adjustments, adjustments/{id}/post, transfers
production/  orders, orders/{id}/approve|start-prep|mark-ready|cancel, orders/{id}/picks,
             batches, batches/{id}/consume|finish
workflow/    tasks?mine=true, tasks/{id}/claim|complete, notifications, notifications/unread-count,
             notifications/mark-read, comments?content_type=&object_id=
```

Her uç nokta için rol izni tanımlı olsun (ör. `release` yalnızca `laboratuvar`).

## Adım 1.7 — Ekranlar (frontend)

| Ekran | Kullanıcı | Notlar |
|---|---|---|
| Görevlerim (ana sayfa) | herkes | Rolüme ve bana atanmış açık görevler, bekleme süresi, tek tıkla ilgili kayda git |
| Bildirim zili + liste | herkes | Okunmamış sayısı, okundu işaretle |
| Malzemeler, tedarikçiler, müşteriler, lokasyonlar, ekipmanlar | admin, planlama | Liste + form + Excel içe aktarma |
| Reçeteler | planlama, laboratuvar | Sürüm listesi, satır düzenleme (DRAFT), onay, sürüm karşılaştırma |
| Mal kabul | depo | Satır ekle, lot bilgisi, kaydet → onayla; lot etiketi PDF |
| Stok sorgu | herkes | Malzeme / lot / lokasyon bazında, durum filtresi |
| Lot detay | herkes | Durum, hareketler, **soy ağacı** (geri/ileri ağaç görünümü), yorumlar |
| Lot onay (giriş kontrol) | laboratuvar | Karantinadaki lotlar listesi, serbest bırak / reddet |
| Üretim emirleri | planlama | Liste, oluştur, onayla, iptal; ihtiyaç listesi |
| Malzeme hazırlama | depo | **Tablet ekranı**: ihtiyaç satırları, barkod okut → lot, miktar, FEFO önerisi |
| Şarj / tartım | uretim | **Tablet ekranı**: reçete sırasıyla satırlar, lot okut, gerçek miktar gir, tolerans renkli gösterge, talimat metni |
| Kayıt yorum paneli | herkes | Her belge/lot detayında sağ panel: yorumlar, @bahsetme, denetim geçmişi |

Barkod: USB/Bluetooth okuyucular klavye gibi davranır; okutma alanı odaklı bir input ve Enter ile çalışır.
Lot etiketi: Code128 + QR (içerik: lot no). PDF olarak yazdırılır (Zebra/ZPL Faz 2).

## Adım 1.8 — Demo verisi ve uçtan uca test

- `seed_demo`: 15 hammadde (LAS, SLES, NaOH, NaCl, parfüm, boya, koruyucu, EDTA, su vb.), 2 bulk ürün
  (bulaşık deterjanı, yüzey temizleyici), birer onaylı reçete, 2 karıştırma tankı, lokasyonlar, 3 tedarikçi.
- Uçtan uca test (`tests/test_e2e_production.py`): mal kabul → lot serbest bırak → üretim emri → onay →
  malzeme hazırlama → şarj + tartım (biri tolerans dışı) → şarj bitir → lot serbest bırak → emir tamam.
  Her adımda: doğru görev açıldı/kapandı, doğru bildirim gitti, stok değişmezleri sağlandı, soy ağacı doğru.

---

## Kabul kriterleri

- [ ] Uçtan uca test yeşil; tüm stok testlerinden sonra `assert_stock_invariants()` geçiyor.
- [ ] Negatif stoka düşürecek tartım reddediliyor (test).
- [ ] Karantinadaki lot hazırlamada seçilemiyor (test + arayüz).
- [ ] Onaylı reçete sürümü değiştirilemiyor; kopyalanıp yeni sürüm onaylanınca eski sürüm OBSOLETE (test).
- [ ] Bulk lotun geri izlemesi kullanılan tüm hammadde lotlarını miktarlarıyla gösteriyor; hammadde lotunun
      ileri izlemesi o lotu kullanan şarjları gösteriyor (test + ekran).
- [ ] Görevler kural tablosuna göre açılıp kapanıyor (her satır için test).
- [ ] Yeni görev WebSocket ile sayfa yenilemeden ekrana düşüyor.
- [ ] Malzeme ve açılış stoku Excel'den önizlemeli içe aktarılabiliyor.
- [ ] Tablet ekranları (hazırlama, tartım) 768 px genişlikte rahat kullanılıyor.
- [ ] `docs/PROGRESS.md` ve `docs/DECISIONS.md` güncel.

## Bu fazda kullanıcıya sorulacak kararlar

- **D-1** Şebeke suyu stoktan düşülsün mü (sayaç/miktar kaydı), yoksa sadece reçetede bilgi olarak mı dursun?
- **D-2** Lot numarası biçimi: önerilen biçim uygun mu, fabrikanın mevcut bir kodlaması var mı?
- **D-3** Sayım farkı düzeltmesini kim onaylar?
- **D-4** Bir üretim emri birden fazla şarja bölünebilsin mi (tank kapasitesi aşılırsa), yoksa 1 emir = 1 şarj mı?
