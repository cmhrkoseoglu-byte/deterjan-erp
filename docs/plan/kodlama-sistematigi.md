# Kodlama sistematiği

> **Durum:** CUMHUR onayladı (2026-11-04). İki paket hâlinde, adım adım uygulanır (§10).
> Kararların gerekçesi `docs/DECISIONS.md` "2026-11-04 — Kodlama sistematiği" kaydındadır.

## 1. Amaç ve sahip kararları

Kod gerektiren her kayda, standartlara uygun ve tek bir ekrandan yönetilen bir kodlama
sistematiği getirilir. Sahip kararları (CUMHUR, 2026-11-04):

1. **Kapsam:** ana veri kodları, belge numaraları, lot numaraları, basılı çıktılarda doküman
   kontrol bilgisi (ISO 9001 md. 7.5) ve GS1 barkodları.
2. **Kod üretimi:** yeni ana veri kaydında sistem sıradaki kodu önerir. Kullanıcı kodu
   değiştirebilir, ama kod biçime uymak zorundadır.
3. **Mevcut kodlar:** yeni sistematiğe taşınır. Eski kod kayıtta kalır ve aranabilir. Verilmiş
   belge ve lot numaraları hiç değişmez.
4. **Yetki:** kodlama ayarlarını yalnızca admin değiştirir; her değişiklik denetim günlüğüne
   yazılır.
5. **Varsayılan biçimler:** canlıda zaten kullanılan düzen (§3).
6. **Kod kilidi:** kayıt açıldıktan sonra kodu yalnızca admin değiştirir.
7. **Lot numarası tarihi:** ISO 8601 (`H-20261104-001`). D-2'deki `YYMMDD` düzeninin yerini alır.

## 2. ISO ne ister, ne istemez

| Konu | İstenen | İstenmeyen (gelenek) |
|---|---|---|
| ISO 9001 md. 7.5 (dokümante bilgi) | Doküman tanımlanır (başlık, tarih, referans no örnek olarak geçer), gözden geçirilip onaylanır, değişiklikleri kontrol edilir, kayıtlar istenmeden değişmeye karşı korunur. | Belirli bir kod biçimi (`FR-KAL-001`), revizyon biçimi, alt bilgi bandı. Bunlar Türk KYS geleneğidir. |
| ISO 9001 md. 8.5.2 (tanımlama, izlenebilirlik) | Çıktı benzersiz tanımlanır, izlenebilirlik kaydı tutulur. | Numara biçimi. |
| ISO 8601 (tarih) | Takvim tarihi `YYYYMMDD`, sıra tarihi `YYYYDDD`; yıl 4 hane. | Numarada tarih bulunması. `YYMMDD` GS1 düzenidir. |
| GS1 (ISO/IEC 15459 uyumlu) | GTIN ve SSCC yapısı, kontrol hanesi, AI kuralları. | Firma içi barkodlar (`LOT:`, `LOC:`, `MAT:`). |

Bu çalışma firmayı ISO 9001'e uygun ya da belgeli yapmaz. Kalite yönetim sistemi (prosedürler,
ana doküman listesi, onay süreci) firmanındır. ERP şunları sağlar: kayıtların benzersiz ve kalıcı
tanımlanması, değişiklik izi, çıktılarda doküman kontrol bilgisi. Bunlar denetimde kanıt olarak
kullanılabilir.

## 3. Kod türleri ve varsayılanlar

### 3.1 Ana veri kodları

Ana veri kodlarında izinli karakterler A-Z, 0-9 ve `-`'dir. Türkçe harf ve boşluk kullanılamaz;
barkoda ve muhasebe aktarımına uygundur. Biçim `<önek>-<sıra no>` şeklindedir. Sıra no soldan
sıfırla doldurulur ve hane sayısı ayarlanabilir.

| Tür | Varsayılan | Örnek | Not |
|---|---|---|---|
| Malzeme | `MLZ`, 7 hane | MLZ-0000001 | Barkodla okutulur (`MAT:`) |
| Kategori | `KAT`, 4 hane | KAT-0001 | |
| Depo | `DEPO`, 5 hane | DEPO-00001 | |
| Lokasyon | `LOKASYON`, 4 hane | LOKASYON-0001 | Barkodla okutulur (`LOC:`) |
| Ekipman | Türe göre önek, 5 hane: karıştırma tankı `TANK`, stok tankı `STOK`, dolum hattı `DOLUM`, terazi `TERAZI`, diğer `EKIPMAN` | TANK-00001 | |
| Tedarikçi | `TED`, 6 hane | TED-000001 | |
| Müşteri | `MUS`, 6 hane | MUS-000001 | |
| Yazıcı | `YAZICI`, 3 hane | YAZICI-001 | |
| Reçete | `REC`, 7 hane | REC-0000001 | |
| Test tanımı | Serbest kod; yalnızca kural uygulanır (A-Z, 0-9, `_`, `-`) | AKTIF_MADDE | Taşınmaz |
| Birim, H/P/EUH | Standart kodlar | KG, H315 | Değişmez; ekranda salt okunur |

- **Biçim kapalı ya da etkin olabilir.** Kod, biçimi etkinleşmemiş türde bugünkü gibi serbesttir.
  Etkin türde:
  - yeni kayıtta sıradaki kod önerilir,
  - biçime uymayan yeni kod kabul edilmez,
  - kod değiştirilirken de biçim denetlenir.

  Biçime uymayan mevcut bir kaydın kodu değişmedikçe kayıt düzenlenebilir.
- **Öneri:** sayaç, verilen son numarayı tutar. Öneri, sayaçtan sonraki ilk boş numaradır. Dolu
  ya da başka bir kaydın eski kodu olan numaralar atlanır.
- **Sayaç ilerlemesi:** önerilenden en çok 10 ileri bir numara yazılırsa sayaç o numaraya
  ilerler. Daha ileri bir numara kabul edilir ama sayacı ilerletmez; böylece yanlış yazılmış tek
  bir kod numaraları tüketmez.
- **Sayaç düzeltme:** admin sayacı ekrandan not yazarak düzeltebilir. Sayaç geri alınsa bile
  öneri dolu numarayı atlar.
- **Sıra taşması:** sıra hanesini aşan numara bir hane uzar (MLZ-9999999 → MLZ-10000000). Uzun
  biçimde ilk hane sıfır olamaz.
- **Kod kilidi:** kayıt açıldıktan sonra kodu yalnızca admin değiştirir (karar 6). Kural
  sunucuda denetlenir; yetkisiz istek 403 alır. Ekran, admin olmayan kullanıcıda alanı kilitler.
- **Django yönetim paneli:** kayıtlı türlerde kod alanı salt okunurdur ve yeni kayıt açılamaz.
  Yeni kayıt uygulamadan açılır; öneri, biçim, eski kod kuralları uygulamada denetlenir.

### 3.2 Belge numaraları

Varsayılan bugünküyle aynıdır: `<önek>-<YYYY>-<5 hane sıra>` (`UE-2026-00001`). Sayaç önek ve
yıl başınadır; yıl başında sıfırlanır (CLAUDE.md kural 10). PU ve BR belgeleri dönem yılını alır.

Belge türü başına ayarlanabilenler:
- önek (harfle başlar, büyük harf ve rakam, en çok 10 karakter),
- yıl (`YYYY` ya da `YY`),
- sıra hanesi (4-7).

Kurallar:
- Önek tüm belge türlerinde tektir ve geçmişte kullanılmış önek başka türe verilmez. Önek
  değişirse yeni önekte sayaç 1'den başlar; eski numaralar aynen kalır.
- Sıra hanesi, bu yılın sayacına yetmeyecek kadar küçültülemez.
- **İrsaliye numarası (SV)** yasal belge numarası olduğu için ekranda değiştirilemez.
- Değişiklik yalnızca bundan sonra verilecek numaraları etkiler.

Belge türleri: ST, SA, UE, DO, SS, SV, NM, PU, BR, IA, BK, MK, SD, AT, OL, SK, SB.

### 3.3 Lot numaraları

Varsayılan biçim `<önek>-<YYYYMMDD>-<3 hane sıra>` (`H-20261104-001`) olur (karar 7). Önekler
şunlardır: H satın alma (mal kabul), B üretim şarjı, D dolum. Sayaç önek ve gün başınadır, tüm
malzemelerde ortaktır.

Ayarlanabilenler:
- önek (1-4 büyük harf, lot türleri arasında tek),
- tarih: `YYYYMMDD` (ISO 8601 takvim tarihi), `YYYYDDD` (ISO 8601 sıra tarihi) ya da `YYMMDD`
  (GS1 düzeni),
- sıra hanesi (3-5).

Lot numarası en çok 20 karakter olur (GS1 AI 10 sınırı). Açılış stokundaki ve tedarikçiden gelen
lot numaraları olduğu gibi kalır.

### 3.4 Eski kodlar

- Kodu değişen kaydın önceki kodu, geçerlilik aralığıyla (`valid_from`, `valid_to`)
  `core.CodeHistory` tablosuna yazılır. Satırlar değiştirilmez ve silinmez.
- **Kullanılmış bir kod, aynı türde başka bir kayda hiçbir zaman verilmez.** Bu kural biçim etkin
  olsun olmasın her kayıtta, içe aktarmada ve göçte uygulanır. Kayıt, bıraktığı kodu geri
  alabilir (geri alma).
- Eski kod şu yerlerde tanınır:
  - liste aramaları ve seçim kutuları,
  - barkod okutma (`LOC:`, `MAT:` ve öneksiz); ekranda "Eski etiket okutuldu" uyarısı çıkar,
  - Excel içe aktarma: eşleşen satır kaydı günceller, yeni kayıt açmaz.
- Belgeler yeniden basılırken belgenin tarihindeki kod basılır (Paket 2, §6).

### 3.5 Mevcut kodların göçü

Göç tür tür yapılır:

1. **Önizleme:** salt okunur; çalıştırmak hiçbir şeyi değiştirmez.
2. **Uygulama:** önizlemeden sonra kayıtlar değiştiyse reddedilir.
3. **Geri alma:** kodu hâlâ göçteki yeni kod olan kayıtlar eski koduna döner.

Eşleme şöyle yapılır: biçime uyan kod korunur. Uymayan kayıtlar oluşturulma sırasıyla sıradaki boş
numaraları alır; göçte bırakılan bir kod başka kayda verilmez.

Uygulama yalnızca kod kurallarını denetler: biçim, tekillik ve eski kod. Kaydın diğer alanları
yeniden doğrulanmaz. Her değişiklik denetim günlüğüne yazılır (`code: [eski, yeni]`, not "Kod göçü
#n"). Stok defterine, lotlara ve belge numaralarına dokunulmaz.

Canlıda uygulamadan önce yedek alınır.

## 4. Kodlama motoru (`apps/core/coding/`)

| Dosya | İçerik |
|---|---|
| `registry.py` | Kod türleri. Modüller kendi türlerini `AppConfig.ready()` içinde kaydeder; `core` modül import etmez (`core/records.py` deseni). |
| `formats.py` | Biçimin saf fonksiyonları: doğrulama, numara üretme, koddan sıra no okuma. |
| `selectors.py` | Etkin biçim, öneri, örnek ve önizleme, eski kodla bulma, belirli bir tarihteki kod. |
| `services.py` | Biçim değiştirme, kodu alma (sayaç kilidi), eski kodu yazma, göç ve geri alma. |

Modeller (`core/models.py`):

| Model | Ne tutar |
|---|---|
| `CodeScheme` | Türün etkin biçimi ve revizyon numarası. Satır yoksa kayıttaki varsayılan geçerlidir. |
| `CodeSchemeRevision` | Her değişikliğin değiştirilemez kopyası ve zorunlu değişiklik notu. Bir önekin geçmişte kullanılıp kullanılmadığı buradan bilinir. |
| `CodeSequence` | Ana veri önekleri için sayaç (`key` + önek). Belge ve lot sayaçları (`DocumentSequence`, `LotNumberSequence`) olduğu gibi kalır. |
| `CodeHistory` | Eski kodlar ve geçerlilik aralıkları. |
| `CodeMigrationRun` | Uygulanan göçler, eşlemeleri ve geri alma bağı (Adım 5). |

Bağlantı noktaları:
- `core.services.next_document_number(prefix, *, year=None)`: imzası değişmez. Kayıtlı belge
  türünde etkin biçim uygulanır. Kayıtsız önek (yalnızca testler) bugünkü biçimde kalır. Kaynaktaki
  bütün sabit önekler bir testle kayıtlı türlerle karşılaştırılır.
- `inventory.services.next_lot_number(prefix, day)`: imzası değişmez; `prefix` lot türüdür (H, B,
  D).
- `masterdata.services.validate_record`: kod kurallarını uygular. `_save` kodu sayaç kilidiyle
  alır, `update_record` kod kilidini ve eski kodu işler. Reçete, test tanımı ve tehlike ifadeleri
  de bu yoldan geçer.
- Ayar uç noktaları `/api/v1/coding/` altındadır ve yalnızca admin içindir. Servisler de yetkiyi
  ayrıca denetler. Öneri uç noktası (`suggest-code`) türün yazma rollerine açıktır.

Hata kodları sabit ve İngilizcedir, mesajlar Türkçedir. Örnekler: `code_format`, `code_reserved`,
`invalid_characters`, `prefix_in_use`, `sequence_too_narrow`, `scheme_locked`, `recode_stale`.

## 5. Ayar ekranı: Sistem > Kodlama sistematiği

Ekran `/sistem/kodlama` adresindedir. Sistem sayfası zaten yalnızca admin'e açıktır.

| Bölüm | Ne var |
|---|---|
| Ana veri kodları | Tür, biçim, örnek, sıradaki kod, durum (Kapalı / Etkin / Standart). Düzenleme penceresinde önek, sıra hanesi, ekipmanda türe göre önekler, sayaç ve "Biçimi etkinleştir" bulunur. |
| Belge numaraları | 17 tür: önek, yıl, sıra hanesi, bu yıl verilen son numara. SV salt okunur. |
| Lot numaraları | H, B, D: önek, tarih biçimi, sıra hanesi, bugün verilen son numara. |
| Kod göçü | Tür seçimi, önizleme tablosu (Değişecek / Aynı kalır), uygula, geri al, son yedek bilgisi. |
| Geçmiş | Biçim revizyonları ve göçler. |
| Çıktı doküman kodları, GS1 | Paket 2. |

Biçim seçmeli alanlarla ayarlanır; serbest biçim dili yoktur. Kaydetmeden önce sunucudan örnek
alınır ("Sıradaki", "En uzun hali"). Değişiklik notu zorunludur ve onay penceresi çıkar.

Ana veri formlarında:
- yeni kayıtta önerilen kod gelir; altında "Önerilen kod. Değiştirebilirsiniz; biçim: MLZ-0000000"
  yazar,
- kayıt formunda eski kodlar görünür.

Lokasyon etiketinde kod hiç kesilmez; sığmazsa yazı küçülür. Bugün uzun kodlar "…" ile kesiliyor.

## 6. Paket 2

### 6.1 Çıktı doküman kodları (ISO 9001 md. 7.5)

- Çıktılar bir kayıt defterine kaydedilir: irsaliye, analiz sertifikası, satın alma siparişi,
  geri çağırma, raporlar, personel ve maliyet çıktıları, içe aktarma şablonları.
- Admin her çıktıya doküman no, ilk yayın tarihi ve revizyonları girer. Revizyonun yürürlük
  tarihi, değişiklik açıklaması, onaylayan ve onay tarihi zorunludur; satırlar değiştirilemez.
- Bant, admin açtığı çıktıya basılır:
  - **PDF:** "Doküman no · Yayın tarihi · Rev. no · Rev. tarihi · Sayfa x/y"
  - **Excel:** yazdırma alt bilgisi ve dosya özellikleri
- **Yeniden basım:** belgenin tarihinde yürürlükte olan revizyon ve o tarihteki kodlar basılır.
- **Şablon sürümü:** her üreticinin şablon sürümü vardır. Şablon değişip yeni revizyon girilmezse
  ekran uyarır.
- **İrsaliye:** bandı açmadan önce mali müşavire danışılır. Etiketlere bant basılmaz.

### 6.2 GS1

- GS1 ayarları tek yerdedir (Kodlama > GS1): firma öneki, SSCC uzantı hanesi, sıradaki SSCC seri
  no (salt okunur). Değişiklik notu zorunludur.
- **Okutma:**
  - (00), (01), (02) alanlarında kontrol hanesi denetlenir,
  - AI tablosu genişletilir (310n, 400, 410, 414 vb.),
  - (15) ve (17) alanlarında gün 00 ayın son günü sayılır,
  - üretim, dolum ve sevkiyatta lot çözümü ortaktır.
- **GTIN tekilliği:** 14 haneli normal biçimde denetlenir; ürün ve koli GTIN'lerinin tamamında tek
  olur. Lotu olan malzemenin GTIN'i değişmez.
- **GTIN önerisi:** yalnızca mamulde, firma öneki ve ilk boş ürün referansı girildikten sonra
  açılır.
- **Koli GTIN'i:** KOLI dönüşümünde tutulur.
  - Tanımlıysa koli etiketinin (01) alanında, palet etiketinin (02) alanında koli GTIN'i ve
    (37) koli sayısı basılır.
  - Okutmada koli GTIN'i koli birimiyle çözülür.
  - Tanımlı değilse bugünkü davranış sürer ve uyarı verilir.

### 6.3 Standart kod alanları

- **Birim:** UN/ECE Rec 20 ortak kodu (KGM, GRM, LTR, MLT, C62; ambalaj birimleri GİB listesinden)
  ve sembol (kg, g, L, mL).
- **Cari:** ülke kodu (ISO 3166-1 alpha-2, varsayılan TR).
- **GBF dili:** ISO 639-1 listesinden seçilir.
- **Tehlike ifadeleri:** kodda büyük/küçük harf korunur (`H360Fd` ile `H360FD` farklıdır).

## 7. Değişmezler ve testler

- Stok defteri, lot soy ağacı, lot ve belge numaraları göçte ve biçim değişikliğinde değişmez.
  Göç testlerinde `assert_stock_invariants()` çağrılır.
- Her servis için mutlu yol ve kural ihlali testi; her uç noktada yetkisiz rol 403.
- Belge ve lot sayaçlarının eşzamanlılığı bugünkü testlerle korunur. Ana veri sayacı için de
  eşzamanlı kod alma testi yazılır.
- Kaynaktaki her sabit belge öneki kayıtlı bir belge türüne karşılık gelmelidir (test).

## 8. Kapsam dışı

- e-İrsaliye ve e-Fatura numarası: Faz 5'te entegratörden ayrı alan olarak gelir; SV numarası
  firma içi numara olarak kalır.
- Personel sicil no, CoA sertifika no, yeni belge türleri.
- Muhasebe kodu: D-18 gereği kartlar bu sistemde açılır ve muhasebeye bu kodlarla gider. Muhasebe
  programındaki mevcut kartların kodu farklıysa Faz 5'te ayrı "muhasebe kodu" alanı eklenir.
- Barkod baskı ölçüleri (GS1 X boyutu, çubuk yüksekliği): gerçek Zebra yazıcıda deneme gerekir.

## 9. Canlıya alma

1. Paket 1 yayına alınır. Biçimler kapalı gelir. Kullanıcının hemen göreceği değişiklikler:
   - lot numarasının yeni tarih biçimi,
   - kodu yalnızca admin'in değiştirebilmesi,
   - kullanılmış bir kodun başka kayda verilememesi,
   - lokasyon etiketindeki kodun artık kesilmemesi.
2. Admin Kodlama sistematiği ekranında ana veri biçimlerini etkinleştirir.
3. Canlıdaki biçime uymayan kodlar için göç önizlemesi çalıştırılır ve sahibe gösterilir. Yedek
   alındıktan sonra göç uygulanır.
4. Paket 2 yayına alınır; çıktı kodları firmanın doküman listesinden girilip etkinleştirilir.

## 10. Adımlar

Her adım: kısa plan, uygulama, testler yeşil (`pytest`, `ruff`, `mypy`, ön yüz lint, typecheck,
test, derleme), `PROGRESS.md`, ayrı commit. Push ve PR her paketin sonunda sahibe sorulur.

| # | Adım | Commit |
|---|---|---|
| 0 | Plan ve karar kaydı | `docs: kodlama sistematiği planı ve kararları` |
| 1 | Kodlama motoru: modeller, kayıt, biçimler, servisler, ayar API'si | `feat(core): kodlama motoru ve ayar API'si` |
| 2 | Belge ve lot numaraları ayardan; lot tarihi ISO 8601 | `feat(core): belge ve lot numaraları kodlama ayarlarından` |
| 3 | Ana veri kodları: öneri, biçim, eski kod, kod kilidi, içe aktarma, okutma, etiket | `feat(masterdata): ana veri kod önerisi ve eski kodlar` |
| 4 | Kodlama sistematiği ekranı | `feat(system): Kodlama sistematiği ekranı` |
| 5 | Kod göçü: önizleme, uygulama, geri alma | `feat(core): kod göçü` |
| 6 | Çıktı doküman kodları (PDF, Excel, ekran) | `feat(core): çıktı doküman kodları` |
| 7 | GS1: okutma, GTIN, koli GTIN'i, GS1 bölümü | `feat(inventory): GS1 kodlama` |
| 8 | Standart kod alanları | `feat(masterdata): standart kod alanları` |
| 9 | Kılavuz | `docs: kodlama sistematiği kılavuzu` |
