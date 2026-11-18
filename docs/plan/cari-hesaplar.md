# Cari hesaplar (tedarikçi ve müşteri paneli)

İstek (CUMHUR, 2026-11-18): "tedarikçi ve müşteri paneli yapalım cari hesapları kontrol edeceğimiz bir
ekran olsun."

## 1. Sahibin kararları (2026-11-18)

| Konu | Karar |
|---|---|
| Bakiye kaynağı | **Hareket + elle tahsilat.** Sevk edilen sevkiyat müşteriye borç, kaydedilen mal kabul tedarikçiye alacak (fiyatlarıyla) sistemden yazılır. Tahsilat, ödeme, iade dekontu, borç/alacak dekontu ve açılış bakiyesi ekrandan elle girilir. Fiyatsız satır "tutarı eksik" diye işaretlenir. |
| Para birimi | **Her birim ayrı** (TRY / EUR / USD ayrı bakiye). Kur girilmişse TL karşılığı da gösterilir. |
| Yetki | **Yönetim + bölüm rolleri.** Yönetim ikisini görür ve girer; satın alma tedarikçi carilerini görür ve girer; sevkiyat müşteri carilerini görür (tutarlar yalnız "Fiyatları görür" varsa). |
| Çıktı | **Excel + PDF ekstre.** Cari listesi ve ekstre Excel; ekstre ayrıca firma bilgili A4 PDF (mutabakat). |
| KDV | **KDV dahil.** Malzeme kartına KDV oranı (varsayılan %20); KDV muaf cari (ihracat / ithalat) %0. Ekstrede matrah ve KDV ayrı. |
| İade | **Elle iade dekontu.** İade ekstrede tutarsız bilgi satırıdır; iade alacak dekontu girilir ve iadeye bağlanır, tutar sevkiyatın sipariş fiyatından önerilir. |
| Ek masraf | **Yalnız maliyete.** Mal kabul ek masrafları tedarikçi carisine yazılmaz. |
| Vade | **Cari kartında vade günü**, vadesi geçen tutar ve 0-30 / 31-60 / 61-90 / 90+ yaşlandırma (alacaklar en eski borçtan kapatılır). |

## 2. Tasarım

### 2.1 Yeni modül `ledger` ("Cari hesaplar")

Bağımlılık: `core ← masterdata ← inventory ← sales/returns ← ledger`. `ledger` diğerlerinin modellerini
okur, kimse `ledger`'a bağımlı olmaz; sevkiyat ve mal kabul olaylarını dinler.

**`LedgerEntry` (cari hareket defteri)** — stok defteri gibi: değiştirilmez, silinmez, düzeltme ters
kayıtla.

- Taraf: `customer` ya da `supplier` (tam olarak biri dolu, kısıtla).
- `entry_date` (vade ve ekstre bu tarihe göre), `kind`, `currency`, `debit` / `credit`
  (`decimal_places=2`, biri sıfır), `net_amount`, `vat_amount` (otomatik kayıtta), `exchange_rate`
  (varsa, 18,6), `description`, `reference` (çek/dekont no), `method` (tahsilat/ödemede: nakit,
  havale/EFT, çek, senet, kredi kartı, mahsup, diğer).
- Kaynak: `source_type` + `source_id` (`shipment`, `goods_receipt`) ya da elle kayıt (`document_no`
  `CH-2026-00001`); iade dekontunda `customer_return`.
- `reversal_of` (ters kayıt), `is_reversed`.

Türler ve yön (carinin bizim defterimizdeki hesabı; bakiye = borç − alacak, (B)/(A) gösterilir):

| Tür | Kim | Yön | Nasıl |
|---|---|---|---|
| Satış (sevkiyat) | müşteri | Borç | `shipment.dispatched` |
| Alış (mal kabul) | tedarikçi | Alacak | `goods_receipt.posted`, `goods_receipt.cost_changed` |
| Tahsilat | müşteri | Alacak | elle |
| Ödeme | tedarikçi | Borç | elle |
| İade alacak dekontu | müşteri | Alacak | elle, iadeye bağlı |
| Borç / alacak dekontu | ikisi | seçilir | elle (fark, kur farkı, ek masraf vb.) |
| Açılış bakiyesi | ikisi | seçilir | elle (canlıya geçişte devir) |
| Ters kayıt | ikisi | tersi | iptal |

**Otomatik kayıt kuralları**

- Sevkiyat: her sevk satırı × sipariş satırının birim fiyatı; para birimi başına bir kayıt. KDV =
  matrah × malzemenin KDV oranı (cari KDV muafsa 0), satır bazında 2 ondalığa yuvarlanır.
- Mal kabul: satır miktarı (sipariş birimiyle girilen fiyat × miktar, maliyet modülünün kullandığı
  tutar) × KDV; ek masraflar hariç. Kur kabulden gelir.
- **İdempotent eşitleme** `sync_source(kind, id)`: belgenin bugünkü tutarını defterdeki etkin kayıtlarla
  karşılaştırır, fark varsa düzeltme yazar. İlk kayıt belge tarihli, sonraki düzeltmeler (fiyat
  düzeltmesi) düzeltme günü tarihli ve "Fiyat düzeltmesi: MK-…" açıklamalı. Olay kaçarsa
  `manage.py sync_ledger` aynı işi tüm belgeler için yapar (canlıdaki geçmiş sevkiyat ve kabuller için
  de bu çalıştırılır).
- **Fiyatı eksik satır** cariye yazılmaz; "Tutarı eksik" listesinde görünür. Sevkiyatta sipariş onaydan
  sonra değişmediği için fiyat cari ekranından girilir (`ShipmentLinePrice`, yalnız cari için; sipariş
  değişmez, denetimli); mal kabulde mevcut "Fiyat ve masraflar" paneli kullanılır. İkisi de eşitlemeyi
  tetikler.

### 2.2 Ana veri eklemeleri (masterdata)

- `Material.vat_rate` — KDV oranı (%; 0 / 1 / 10 / 20, varsayılan 20; mevcut malzemeler 20).
- `BusinessPartner.payment_term_days` (vade, gün; boş = peşin) ve `vat_exempt` (KDV muaf; ihracat
  müşterisi / ithalat tedarikçisi).
- Kart formları, Excel içe aktarma şablonu ve denetim günlüğü bu alanları içerir.

### 2.3 Okuma (selectors)

- **Cari listesi** (müşteri / tedarikçi sekmesi): kod, ünvan, para birimi başına bakiye (B/A), vadesi
  geçen, yaşlandırma (0-30 / 31-60 / 61-90 / 90+), son hareket tarihi, tutarı eksik belge sayısı.
  Süzgeç: arama, "bakiyesi olanlar", "vadesi geçenler", para birimi, pasif cariler.
- **Ekstre**: tarih aralığı, devreden bakiye, satır satır borç / alacak / yürüyen bakiye (para birimi
  başına), belge bağlantısı, matrah/KDV, vade tarihi; iadeler bilgi satırı (tutarsız).
- **Yaşlandırma**: alacak kayıtları en eski borçtan kapatılır (FIFO), vade = belge tarihi + carinin
  vade günü (bugünkü kart değeri).
- Değişmez test yardımcısı: cari bakiye == SUM(kayıtlar), her kaynak için etkin toplam == belgenin
  bugünkü tutarı.

### 2.4 Yetki (`ledger/access.py`)

| Bölüm | Düzey | Anlamı |
|---|---|---|
| `ledger.customers` "Müşteri carileri" | Görür | Liste ve ekstre; tutarlar yalnız "Fiyatları görür" ile |
| | Değiştirir | Tahsilat, iade dekontu, dekont, açılış, eksik fiyat, iptal (ön koşul: Fiyatları görür) |
| `ledger.suppliers` "Tedarikçi carileri" | Görür / Değiştirir | Aynısı tedarikçi için (ödeme) |

Varsayılan paketler: `yonetim` ikisinde Görür + Değiştirir; `satin_alma` tedarikçide Görür +
Değiştirir; `sevkiyat` müşteride Görür. Fiyat hakkı olmayana tutar alanları yanıtta yoktur (Excel ve
PDF dahil). PDF'te carinin adres ve vergi bilgisi yalnız iletişim bilgisini görebilene basılır.
Her uç noktada denetlenir; yetkisiz rol 403 alır.

### 2.5 API (`/api/v1/ledger/`)

- `GET partners/?side=customer|supplier` (liste, sayfalı, süzgeçli), `GET partners/<side>/<id>/`
  (özet + yaşlandırma), `GET .../statement/?from=&to=` (ekstre), `.../statement.xlsx`,
  `.../statement.pdf`, `GET partners/export.xlsx`.
- `POST entries/` (elle kayıt), `POST entries/<id>/reverse/` (gerekçe zorunlu),
  `GET missing-prices/`, `POST shipment-line-prices/`.

### 2.6 Ekran

Menüde "Cari hesaplar": Müşteriler / Tedarikçiler sekmeleri, liste ve özet kutuları (toplam alacak,
toplam borç, vadesi geçen — para birimi başına). Cari satırından ekstre sayfası: tarih aralığı, Excel,
PDF, "Tahsilat gir" / "Ödeme gir", "Dekont", "Açılış bakiyesi", satırdan "İptal et" ve "Tutarı eksik"
paneli. Kayıtlara bağlı yorum/geçmiş mevcut `core/records.py` düzeniyle.

## 3. Adımlar

1. **Ana veri alanları**: KDV oranı, vade günü, KDV muaf; migration, kart formları, içe aktarma, testler.
2. **Defter ve servisler**: `ledger` modülü, modeller, yetki bölümleri, `post_manual_entry`,
   `reverse_entry`, `set_shipment_line_price`, `sync_source`, olay dinleyicileri, `sync_ledger` komutu,
   servis ve değişmez testleri.
3. **Okuma ve API**: liste, ekstre, yaşlandırma, eksik fiyat; tutar gizleme; API ve yetki testleri.
4. **Excel ve PDF**: liste ve ekstre Excel'i, A4 ekstre PDF'i (firma bilgisi, mutabakat notu).
5. **Ekran**: React sayfaları, formlar, Vitest.
6. **Belgeler**: DECISIONS, PROGRESS, yardım metni; canlıya alışta `sync_ledger` adımı.

## 4. Kapsam dışı

Fatura kesme ve e-Fatura (muhasebe programında), kur farkı hesabı, çek/senet portföyü takibi, banka
entegrasyonu, muhasebeye aktarım (Faz 5.1; bu defter o aktarımın kaynağı olabilir).
