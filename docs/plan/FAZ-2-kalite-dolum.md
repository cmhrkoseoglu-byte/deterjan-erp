# Faz 2 — Kalite kontrol, dolum/ambalaj ve barkod

**Amaç:** Faz 1'de manuel olan lot onayını gerçek laboratuvar akışına bağlamak; bulk ürünün şişelere
dolumunu, ambalaj tüketimini, fireyi ve mamul lotunu sisteme almak; etiket ve barkod altyapısını kurmak.

Ön koşul: Faz 1 kabul kriterleri tamam.

---

## Adım 2.1 — `quality`

**`TestDefinition`** (`MasterDataModel`): `code` (PH, VISK, YOGUNLUK, AKTIF_MADDE, RENK, KOKU, GORUNUS, KATI_MADDE),
`name`, `result_type`: `NUMERIC` | `PASS_FAIL` | `TEXT`, `unit` (ör. cP, g/ml, %), `method` (ölçüm yöntemi metni), `decimal_places`.

**`Specification`** (sürümlü, reçete gibi): `material` (RAW/BULK/FINISHED), `version_no`, `status` (`DRAFT` | `APPROVED` | `OBSOLETE`),
`sample_stage`: `INCOMING` (giriş) | `IN_PROCESS` (şarj sırasında) | `FINAL` (şarj sonu / dolum sonrası).
Satırlar **`SpecificationLine`**: `test`, `min_value`, `max_value`, `target_value`, `text_expected` (PASS_FAIL/TEXT için), `is_mandatory`.

**`Sample`** (`DocumentModel`, numara `NM-`): `lot`, `stage`, `specification` (oluşturma anında sabitlenir),
`taken_by`, `taken_at`, `status`: `PENDING` → `IN_TEST` → `DECIDED`, `retain_location` (şahit numune yeri).

**`TestResult`**: `sample`, `spec_line`, `numeric_value` / `text_value` / `passed` (bool), `is_within_spec` (hesaplanır),
`measured_by`, `measured_at`, `instrument` (opsiyonel). Sonuç düzeltmesi yeni kayıt + eski kayıt `superseded_by` (silinmez).

**`QualityDecision`**: `sample`, `decision`: `RELEASE` | `REJECT` | `REWORK` | `CONDITIONAL_RELEASE`, `reason`, `decided_by`, `decided_at`.
- Zorunlu testlerin hepsi girilmeden karar verilemez.
- Spec dışı sonuç varken `RELEASE` verilemez; `CONDITIONAL_RELEASE` (şartlı kabul) `yonetim` onayı ister.

**Servis değişiklikleri**
- Faz 1'deki `inventory.release_lot` / `reject_lot` artık **yalnızca** `quality.services.decide(...)` tarafından çağrılır.
  Manuel serbest bırakma uç noktası kaldırılır (veya `admin` rolüne, gerekçe zorunlu olarak kısıtlanır — Karar D-5).
- `goods_receipt.posted` → `INCOMING` numune otomatik oluşur (`requires_incoming_qc` olan malzemeler için).
- `production_batch.completed` → `FINAL` numune otomatik oluşur.
- `REWORK` kararı → planlamaya görev: "Yeniden işleme emri aç: {lot}". Yeniden işleme emri, girdi olarak
  reddedilen lotu kullanan yeni bir üretim emridir (soy ağacı korunur).
- **Analiz sertifikası (CoA)**: serbest bırakılan lot için PDF (`GET /api/v1/quality/samples/{id}/coa.pdf`):
  ürün, lot, üretim/SKT tarihleri, test-spec-sonuç tablosu, onaylayan.

**Ekranlar**: Numune kuyruğu (laboratuvar ana ekranı: bekleyen numuneler, bekleme süresi), sonuç giriş formu
(spec sınırları yanında, dışı kırmızı), karar ekranı, spesifikasyon yönetimi, lot detayında QC sekmesi.

## Adım 2.2 — `filling` (dolum ve ambalaj)

**`PackagingSpec`** (mamulün ambalaj reçetesi, sürümlü): `finished_product` (FINISHED), `bulk_product` (BULK),
`fill_quantity` + `fill_unit` (ör. 750 ML), `fill_tolerance_pct`, `units_per_case`, `cases_per_pallet`, `status`.
Satırlar **`PackagingSpecLine`**: `material` (PACKAGING: şişe, kapak, etiket, arka etiket, koli, streç, palet),
`quantity_per_unit` (ör. şişe 1, koli 1/12), `scrap_allowance_pct`.

**`FillingOrder`** (`DocumentModel`, numara `DO-`)
- `finished_product`, `packaging_spec` (sabitlenir), `planned_units`, `filling_line` (Equipment), `planned_date`
- Durumlar: `DRAFT` → `APPROVED` → `MATERIAL_PREP` → `MATERIAL_READY` → `IN_PROGRESS` → `QC_PENDING` → `COMPLETED` (+ `CANCELLED`)
- Ambalaj malzemesi hazırlığı Faz 1'deki `MaterialPick` deseniyle (ortak bir servis/mixin'e çıkar).

**`FillingRun`** (dolum vardiyası/partisi): `order`, `output_lot` (dolum lotu, `D-…`), `bulk_lots` (birden fazla tank lotu olabilir),
`started_at`, `finished_at`, `good_units`, `operator`.

**`FillingConsumption`**: bulk lot tüketimi (litre/kg) ve her ambalaj malzemesi lotu tüketimi. Her biri
`ISSUE_PRODUCTION` hareketi + `LotLink(parent=bulk/ambalaj lotu, child=dolum lotu)`.

**`ScrapRecord`**: `run`, `material` (bulk / şişe / etiket / mamul), `lot`, `quantity`, `reason_code`
(`OVERFILL`, `UNDERFILL`, `LEAK`, `LABEL_ERROR`, `CAP_ERROR`, `DAMAGED_PACKAGING`, `SETUP_LOSS`, `OTHER`), `note`.
`SCRAP` hareketi yazar.

**Kurallar ve hesaplar**
- Teorik bulk tüketimi = `good_units × fill_quantity` (temel birime çevrilmiş). Gerçek tüketim ile fark
  eşik üstündeyse (`fill_variance_threshold_pct`, varsayılan %1,5) olay `filling.bulk_variance`.
- Ambalaj tüketimi = `good_units × quantity_per_unit` + kayıtlı fire. Teorik vs gerçek raporu.
- Dolum lotu `QUARANTINE` doğar; `FINAL` numune (görünüm, dolum miktarı, sızdırmazlık, etiket kontrolü) ile serbest bırakılır.
- Dolum bitince mamul `PRODUCTION_OUTPUT` ile mamul deposuna; birimi `ADET` (koli/palet dönüşümleri ile).

**Yeni olaylar ve iş akışı kuralları**

| Olay | Aksiyon | Hedef |
|---|---|---|
| `filling_order.approved` | Görev: "Ambalaj malzemesi hazırla" | depo |
| `filling_order.material_ready` | Görev: "Dolumu başlat" | dolum |
| `filling_run.completed` | Görev: "Mamul kontrolü: {lot}" | laboratuvar |
| `filling.bulk_variance` | Bildirim (WARNING) | planlama, yonetim |
| `lot.released` (FINISHED) | Bildirim: "Sevke hazır" | sevkiyat, planlama |

**Ekranlar**: Ambalaj reçeteleri, dolum emirleri, **dolum hattı tablet ekranı** (bulk lot okut, ambalaj lotları okut,
sayaç girişi, fire girişi hızlı butonlarla), dolum raporu (teorik/gerçek).

## Adım 2.3 — Etiket ve barkod

- Barkod içeriği: Lot etiketi → Code128 + QR, içerik `LOT:<lot_no>`. Mamul koli etiketi → GS1-128
  (GTIN (01), lot (10), SKT (17)) — GTIN bilgisi `Material.gtin` alanına eklenir (Karar D-6: firmanın GS1 üyeliği var mı?).
- Palet etiketi: SSCC (00) — opsiyonel, GS1 üyeliği varsa.
- Çıktı: PDF (A4 / etiket boyutu şablonları) ve **ZPL** (Zebra yazıcılar). Yazıcıya gönderim: ağ yazıcısına
  TCP 9100 ile ham ZPL (yazıcı tanımları `masterdata.Printer`: ad, IP, port, tür).
- Okutma: tüm tablet ekranlarında ortak `ScanInput` bileşeni; okutulan kod çözülür (lot / malzeme / lokasyon)
  ve ilgili alan doldurulur. Yanlış malzemenin lotu okutulursa sesli/görsel uyarı.

## Adım 2.4 — Ekler ve belgeler

- `core.Attachment` (GenericFK): dosya, tür, yükleyen, tarih. Lot, numune, mal kabul, yorumlara eklenebilir
  (tedarikçi CoA'sı, fotoğraf, irsaliye görüntüsü). Depolama: yerel volume, S3 uyumlu depoya geçilebilir.
- Yorumlara dosya/fotoğraf eki (tabletten kamera ile).

---

## Kabul kriterleri

- [ ] Spec dışı sonuçla `RELEASE` verilemiyor; zorunlu test eksikken karar verilemiyor (test).
- [ ] Mal kabul ve şarj bitişinde numune otomatik açılıyor, laboratuvara görev düşüyor (test).
- [ ] CoA PDF'i doğru bilgilerle üretiliyor.
- [ ] Uçtan uca test: … → bulk lot serbest → dolum emri → ambalaj hazırlama → dolum (fire dahil) → mamul QC → mamul lot serbest.
      Mamul lotunun geri izlemesi: bulk lot(lar) + ambalaj lotları + bulk lotun hammadde lotları (çok seviyeli ağaç).
- [ ] Teorik/gerçek bulk ve ambalaj tüketim raporu doğru (test).
- [ ] Lot etiketi PDF ve ZPL üretiliyor; okutma bileşeni tüm tablet ekranlarında çalışıyor.
- [ ] Stok değişmezleri tüm yeni testlerde geçiyor.

## Bu fazda kullanıcıya sorulacak kararlar

- **D-5** Laboratuvar dışında manuel lot serbest bırakma yetkisi kalsın mı (acil durum, gerekçeli)?
- **D-6** GS1 barkod (GTIN/SSCC) kullanılıyor mu, yoksa firma içi barkod yeterli mi?
- **D-7** Hangi testler hangi aşamada zorunlu? (Laboratuvar sorumlusuyla spesifikasyon listesi çıkarılmalı.)
- **D-8** Etiket yazıcısı modeli (Zebra vb.) ve etiket ölçüleri.
