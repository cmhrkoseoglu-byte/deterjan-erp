# Kararlar

Planda olmayan, iş kuralı ya da mimari düzeyindeki kararlar tarih ve gerekçesiyle burada tutulur.

## 2026-10-15 — Geliştirmede ASGI sunucusu: uvicorn

Faz 0 "daphne veya uvicorn" seçeneği bırakmıştı. `uvicorn --reload` seçildi: kod değişikliğinde otomatik
yeniden başlar, Channels (WebSocket) ile çalışır, üretimde de `--workers` ile kullanılabilir.

## 2026-10-15 — Frontend için geçici yer tutucu

`docker compose up` tek komutla çalışabilsin diye `frontend/` içine yalnızca Vite ile servis edilen
düz bir HTML sayfası kondu. Adım 0.5'te React + TypeScript + Mantine kurulumuyla tamamen değiştirilecek.

## 2026-10-15 — Sağlık uç noktası kimlik doğrulama istemez

`/api/v1/health/` izleme araçları ve Docker sağlık kontrolü için açıktır; yalnızca `ok`/`error` döner,
ayrıntı (hata mesajı, sürüm) sızdırmaz. Herhangi bir kontrol başarısızsa HTTP 503 döner.

## 2026-10-15 — Kimlik doğrulama API sözleşmesi (frontend ile ortak)

Adım 0.4'teki auth uç noktalarının biçimi. Frontend (Adım 0.5) buna göre yazılır; değişirse burası güncellenir.

- Kimlik doğrulama: Django session + CSRF. Çerezler `sessionid` ve `csrftoken`; yazma isteklerinde
  `X-CSRFToken` başlığı `csrftoken` çerezinin değeriyle gönderilir.
- `GET /api/v1/auth/csrf/` → `204`, `csrftoken` çerezini ayarlar. SPA açılışta bir kez çağırır.
- `POST /api/v1/auth/login/` gövde `{"username": "...", "password": "..."}` → `200` ve `me` ile aynı gövde.
  Hatalı bilgi: `400 {"code": "invalid_credentials", "detail": "Kullanıcı adı veya şifre hatalı."}`.
  Başarılı girişten sonra CSRF çerezi yenilenir; frontend çerezi yeniden okur.
- `POST /api/v1/auth/logout/` → `204`.
- `GET /api/v1/auth/me/` → `200`:
  ```json
  {
    "id": 3,
    "username": "depo",
    "full_name": "Ayşe Yılmaz",
    "email": "ayse@example.com",
    "roles": ["depo", "planlama"],
    "is_superuser": false
  }
  ```
  `roles`, CLAUDE.md §5'teki rol kodlarıdır (Django `Group` adları), alfabetik sıralı.
  Superuser için `roles` yalnızca gerçekten atanmış grupları içerir; menüde her şeyi görmesi için
  frontend `is_superuser` ya da `admin` rolünü "tüm roller" sayar.
- Giriş yapılmamışsa korumalı her uç nokta `401 {"code": "not_authenticated", "detail": "..."}` döner;
  giriş yapılmış ama rol yetkisi yoksa `403 {"code": "permission_denied", "detail": "..."}`.
- CSRF doğrulaması başarısızsa (çerez yok, eski token) `403 {"code": "csrf_failed", "detail": "..."}`.
  Frontend bu durumda `/auth/csrf/` çağırıp isteği bir kez tekrarlayabilir.
- Çok fazla giriş denemesi: `429 {"code": "throttled", "detail": "..."}` (IP başına, varsayılan 10/dakika).
- Tüm API hataları `{"code", "detail"}` biçimindedir. Alan doğrulama hatalarında ek olarak
  `"errors": {"alan": ["mesaj", ...]}` gelir (`code` = `"validation_error"`). Bozuk JSON:
  `400 {"code": "parse_error"}`; tanımsız `/api/` adresi: `404 {"code": "not_found"}` (geliştirmede,
  `DEBUG=True` iken Django'nun hata sayfası görünür).
- Liste uç noktaları sayfalıdır: `{"count", "next", "previous", "results"}`; `?page=2`,
  `?page_size=100` (en fazla 500, varsayılan 50). Tarih-saatler ISO 8601, Türkiye saatiyle
  (`2026-10-15T13:32:47+03:00`); ondalıklar metin olarak (`"12.5000"`).

## 2026-10-15 — Admin rolü her yere erişir (CUMHUR onayı)

`admin` rolündeki kullanıcılar ve superuser'lar rol korumalı her uç noktaya erişir
(`core.permissions.HasRole`). `user.has_role("depo")` ise yalnızca gerçekten atanmış rollere bakar;
böylece "depo rolüne görev aç" gibi işlerde admin kullanıcılar yanlışlıkla alıcı olmaz.
Pasif (`is_active=False`) kullanıcı hiçbir rol korumalı uç noktaya erişemez.

## 2026-10-15 — Başarısız girişler de denetim günlüğüne yazılır (CUMHUR onayı)

Başarılı giriş (`login`), çıkış (`logout`) ve başarısız giriş (`login_failed`) `AuditLog`'a yazılır.
Spesifikasyondaki işlem listesine `logout` ve `login_failed` eklendi. Başarısız denemede kullanıcı adı
`note` alanına, IP `ip_address` alanına yazılır; kullanıcı adı sistemde varsa kayıt o kullanıcıya
bağlanır. Kayıt Django'nun giriş sinyalleriyle yapılır, böylece API girişi ve yönetim paneli girişi
aynı şekilde denetlenir.

Kaba kuvvet denemelerine karşı giriş IP başına sınırlıdır (`LOGIN_RATE_LIMIT`, varsayılan
`10/minute`, API ve yönetim paneli ortak). IP, nginx'in yazdığı `X-Real-IP` başlığından okunur;
istemcinin gönderebileceği `X-Forwarded-For` dikkate alınmaz. Sayaçlar Redis önbelleğinde
(`CACHE_URL`, varsayılan Redis veritabanı 2) tutulur, tüm worker'larda ortaktır.

## 2026-10-15 — Denetim günlüğü ayrıntıları

- `changes` her zaman `{"alan": [eski, yeni]}` biçimindedir; FK'lar kimlik (id) olarak, ondalıklar
  veritabanına yazılan basamakta (`"12.5000"`) tutulur.
- Şifre özeti hiçbir zaman yazılmaz. Şifre değişikliği (servis, yönetim paneli, `changepassword`)
  `{"password": ["***", "***"]}` ve "Şifre değiştirildi" notuyla yazılır.
- `created_at/updated_at/created_by/updated_by/last_login` farka girmez (her kayıtta değişir ya da
  zaten kaydın kendisinde vardır).
- Hiçbir alan değişmediyse `save_with_audit` ne kayıt yapar ne günlük yazar.
- Rol değişiklikleri `{"roles": [[eski roller], [yeni roller]]}` olarak yazılır (`set_user_roles`
  servisi ve yönetim paneli).
- İşlemi yapan kullanıcı servis fonksiyonuna `actor` olarak verilir. IP adresi ve (yalnızca şifre
  değişikliği sinyalinde) kullanıcı, istek bağlamından (`core.context`) alınır.
- Roller (Django `Group`) yönetim panelinde salt okunurdur: eklenemez, yeniden adlandırılamaz,
  silinemez (grup adı yetkinin kendisidir). Kullanıcılar panelden silinemez, pasife alınır.

## 2026-10-15 — Belgeler, durum ve olaylar

- Belge `core.services.create_document(belge, actor, prefix="UE", machine=...)` ile oluşturulur:
  numarayı ve başlangıç durumunu bu fonksiyon verir, `<makine_adı>.created` olayını yayınlar.
  `save_with_audit` yeni belge oluşturmayı reddeder.
- Numara, durum ve iptal alanları (`DocumentModel.STATE_FIELDS`) yalnızca `transition_status` ve
  `cancel_document` ile değişir; `save_with_audit` bu alanlara doğrudan atamayı reddeder. Başka bir
  kullanıcının durumu değiştirdiği bayat bir nesne kaydedilirse, güncel durum korunur.
- Durum geçişi belge satırını `select_for_update` ile kilitler; aynı belgeye eşzamanlı iki geçişten
  yalnızca biri başarılı olur.
- İptal `CANCELLED` durumudur, iptal nedeni zorunludur (`cancel_reason_required`).
- Belge numarası: önek büyük harf/rakam (en fazla 10), 5 haneli sıra, Türkiye saatine göre yıl
  (`UE-2026-00001`). Belgeyi oluşturan transaction'ın içinde alınır; işlem geri alınırsa numara da
  geri alınır, numara atlaması olmaz.
- Olay handler'ları her uygulamanın `handlers.py` modülünde `@subscribe(...)` ile tanımlanır ve
  otomatik yüklenir. Şimdilik commit sonrası aynı süreçte, her biri kendi transaction'ında çalışır;
  uzun işler gerekirse handler Celery görevi başlatır.

## 2026-10-15 — API şeması ve yalnızca testte yüklenen uygulama

- `/api/schema/` ve `/api/docs/` geliştirmede herkese, diğer ortamlarda yalnızca giriş yapmış
  kullanıcılara açıktır.
- Çekirdek soyut modelleri (BaseModel, DocumentModel) denemek için `apps/core/tests/testapp`
  (`core_testapp`) yalnızca `config.settings.test` ile yüklenir; geliştirme/üretim veritabanında
  tablosu yoktur. `pytest` her zaman test ayarlarıyla çalışır (`--ds=config.settings.test`).

## 2026-10-15 — Menüde hangi rol hangi modülü görür

Faz 0'da menü yalnızca yer tutucu sayfalara gider; rol eşlemesi `frontend/src/layout/menu.ts` içindedir.
Başlangıç eşlemesi: Ana veriler → planlama, yönetim; Depo ve stok → depo, planlama, yönetim;
Üretim → uretim, planlama, yönetim; Kalite → laboratuvar, yönetim; Dolum → dolum, planlama, yönetim;
Sevkiyat → sevkiyat, yönetim; Satın alma → satin_alma, yönetim; Raporlar → yönetim, planlama;
Yönetim paneli (Django admin) → admin. `admin` rolü her öğeyi görür, Görevlerim herkese açıktır.
Her modül kendi fazında kurulurken backend izinleriyle birlikte gözden geçirilecek. Menü gizlemek yetki
değildir (CLAUDE.md §4.12). CUMHUR 2026-10-15'te onayladı.

## 2026-10-15 — Karar D-1: Şebeke suyu stoktan düşülür (CUMHUR kararı)

Su da diğer malzemeler gibi stoklu bir hammaddedir; her şarjda tartılan/okunan miktar stoktan düşülür.
Girişi sayaç okuması ya da dönemsel düzeltmeyle yapılır. `RecipeLine.is_water` yalnızca bir işarettir
(ekranda "Şebeke suyu" rozeti); satırı stoktan muaf tutmaz, ihtiyaç listesinde (`scale_requirements`)
diğer satırlar gibi yer alır. CUMHUR önerilen seçeneğin ("yalnızca reçetede bilgi") yerine bunu seçti.

## 2026-10-15 — Ana veriler (Adım 1.1)

- **Kodlar** baştaki/sondaki boşluk atılıp büyük harfe çevrilir (`hm-las` → `HM-LAS`), böylece büyük/küçük
  harf farkı tekrar kayıt açmaz. Barkoda uygun kalsın diye `i` → `I` çevrilir (`İ` değil).
  Lokasyon kodu tüm depolarda benzersizdir (barkodla okutulur).
- **Birimler:** KG, G, LT, ML, ADET, KOLI, PALET migration ile gelir. KOLI ve PALET'in genel katsayısı
  yoktur (`factor_to_kind_base` boş); yalnızca malzemeye özel dönüşümle çevrilir (1 KOLI = 12 ADET),
  yoksa `no_conversion`. Katsayılar 6 ondalıkla tutulur (miktarlar 4). Dönüşüm sırası: temel birim →
  malzemeye özel dönüşüm → aynı tür içi katsayı → kütle ↔ hacim için yoğunluk (g/ml = kg/lt).
  Temel birime ya da aynı türden genel katsayılı bir birime malzemeye özel dönüşüm tanımlanamaz.
- **Kullanılmış veri korunur:** herhangi bir modülden başvurulan malzemenin temel birimi değiştirilemez
  (`base_unit_locked`); kullanımdaki birimin türü ve katsayısı değiştirilemez; aktif malzemelerin temel
  birimi, aktif lokasyonu olan depo ve aktif ekipmanı olan lokasyon pasife alınamaz. Kontrol modül
  bağımlılığı doğurmadan ters ilişkilerle yapılır, böylece stok ve üretim tabloları da otomatik kapsanır.
- **Tanklar** (karıştırma ve stok tankı) "Tank" türünde bir lokasyona bağlanmak zorundadır.
- **Yetki:** ana verileri herkes okur; `planlama` yazar (admin her yere erişir). Birimler fabrika
  genelini etkilediğinden yalnızca `admin` yazar. Silme yoktur, pasife alma vardır.
- **Excel / CSV içe aktarma** (malzeme, tedarikçi, müşteri): önizleme ve onay aynı dosyanın iki kez
  gönderilmesidir (`confirm=false` / `true`); sunucuda geçici dosya tutulmaz. Hatalı satır varsa hiçbir
  satır yazılmaz ve satır bazlı hata listesi döner. Kodu sistemde olan satır kaydı günceller; güncellemede
  boş bırakılan isteğe bağlı hücre mevcut değeri değiştirmez. Türkçe ondalık (`1,05`, `1.234,5`),
  `Evet/Hayır`, `;` ya da `,` ayraçlı ve Windows-1254 kodlu CSV kabul edilir. Tür sütununda kod, Türkçe
  ad ya da yaygın eş anlamlı ("Yarı mamul", "Dökme") yazılabilir. Sınır: 5 MB, 5000 satır.

## 2026-10-15 — Reçeteler (Adım 1.2)

- `RecipeVersion` numaralı bir belge olmadığından `DocumentModel` değildir; durum makinesi
  `recipes/state.py`'de, geçişler `recipes.services` içinde aynı kurallarla yapılır (izin tablosu,
  denetim kaydı, commit sonrası `recipe_version.approved` / `recipe_version.obsolete` olayı).
- Onay yetkisi `planlama` ve `laboratuvar` (servis de kontrol eder). Onay için en az bir satır, aktif
  reçete/ürün/malzemeler ve temel birime çevrilebilen satır birimleri gerekir. Aynı reçetede eşzamanlı
  iki onay reçete satırı kilitlenerek sıraya girer; veritabanında da "tek onaylı sürüm" kısıtı vardır.
- Reçetenin ürünü dökme (BULK) olmalıdır; sürümü açılmış reçetenin ürünü değiştirilemez. Satırlarda
  yalnızca hammadde ya da dökme ürün kullanılır, ürün kendi satırında kullanılamaz, aynı malzeme birden
  fazla satırda olabilir (ör. iki aşamada eklenen su).
- **Taslak satır/adım kaldırma:** taslak (DRAFT) sürümün satırı ve adımı API'den kaldırılabilir
  (`DELETE /recipes/lines/{id}/`). Taslak hiçbir işlemde kullanılmadığı için "kullanılmış veri"
  sayılmadı; kaldırılan satır tüm alanlarıyla sürümün denetim kaydına yazılır. Onaylı ve geçersiz
  sürümde kaldırma da düzenleme de yasaktır (`version_locked`). CLAUDE.md §4.6 "hard delete API'de
  yoktur" dediği için bu yorum CUMHUR'a ayrıca soruldu; CUMHUR 2026-10-15'te "Kalsın" dedi.
- Ölçekleme (`scale_requirements`) ihtiyaçları malzemenin temel biriminde, 4 ondalığa (yarım yukarı)
  yuvarlayarak döner; hedef birim ürünün birimine çevrilir (KG reçeteden LT hedefe ürünün yoğunluğuyla).

## 2026-10-15 — İş akışı (Adım 1.5): olay sözleşmesi

Kural tablosu `backend/apps/workflow/rules.py` içindedir; olay adları `core/event_names.py`'de sabittir.
Olay yayınlayan modüller (inventory, production) payload'ı aşağıdaki biçimde gönderir. Bir kaydı anlatan
her sözlük en az `{"model": "app_label.model", "id": <pk>}` içerir; görünen ad için `number`, `lot_no`
ya da `repr` alanlarından biri bulunur. Görev bu kayda bağlanır ve kapanış olayı **aynı kayıt** için
gelince kendiliğinden `DONE` olur. Eksik alan şablonda boş kalır, hata vermez.

| Olay | Payload |
|---|---|
| `goods_receipt.posted` | `model, id, number, lots: [{model, id, lot_no, material_code, material_name, requires_qc}]` |
| `lot.released`, `lot.rejected` | `model, id, lot_no, material_code, material_name, material_type` (`RAW`/`BULK`/...), `note` |
| `production_order.<durum>` | `transition_status` / `cancel_document` payload'ı (`model, id, number, from_status, to_status`); onayda isteğe bağlı `priority` (1–4) |
| `production_batch.started` | `model, id, batch_no, order: {model, id, number}` |
| `production_batch.completed` | `model, id, batch_no, order: {model, id, number}, output_lot: {model, id, lot_no, material_code, material_name}` |
| `production.deviation` | `model, id` (şarj), `batch_no, order_number, material_code, lot_no, planned_quantity, actual_quantity, deviation_pct, note` |
| `production.low_yield` | `model, id` (şarj), `batch_no, order_number, yield_pct, threshold_pct` |
| `inventory.lots_expiring` | `days, lots: [{lot_no, material_code, material_name, expiry_date}]` |
| `inventory.below_min_stock` | `materials: [{code, name, quantity, min_stock, unit}]` |

Bir olay iki kez gelirse aynı kayıt ve kural için ikinci açık görev açılmaz. Her kural kendi
savepoint'inde çalışır; biri hata verirse loglanır, diğerleri etkilenmez.

## 2026-10-15 — İş akışı: 07:00 kontrolleri

Celery Beat her sabah 07:00'de (`Europe/Istanbul`) `core.publish_daily_check` işini çalıştırır; bu iş
`system.daily_check` olayını yayınlar. SKT ve minimum stok sorguları inventory modülünde olacağı için
workflow inventory'yi çağırmaz: inventory bu olayı dinleyip `expiring_lots(30)` ve `below_min_stock()`
sonuçlarını `inventory.lots_expiring` ve `inventory.below_min_stock` olaylarıyla yayınlar; workflow da
bunlardan `depo` ve `planlama`'ya birer WARNING bildirimi üretir. Liste boşsa bildirim gitmez.

## 2026-10-15 — İş akışı: görev, bildirim ve yorum kuralları

Plan onayı için CUMHUR'a sunulan varsayılanlar (thread "Görevler ve bildirimler"):

- Olayı tetikleyen kişiye kendi işleminin bildirimi gitmez; görevler yine de açılır.
- Rol görevini o roldeki herkes görür. Biri "üstlen"ince görev `IN_PROGRESS` olur, `claimed_by` dolar;
  ikinci kişi üstlenemez (`task_already_claimed`), diğerleri görevi görmeye devam eder.
- Görev kural olayıyla kendiliğinden kapanır; görevin rolündeki/atanan/üstlenen kullanıcı ya da admin
  elle de tamamlayabilir (not isteğe bağlı, denetim günlüğüne yazılır). Başkası 403 alır.
- Üretim emri iptalinde emre bağlı açık görevler `CANCELLED` olur; bildirim, iptal edilen görevlerin
  rollerine (ve üstlenen/atanan kişilere) ve `planlama`'ya gider.
- `yonetim` ve admin tüm görevleri görür (ama başka rolün görevini kapatamaz, admin hariç); diğer roller
  yalnızca kendine, rollerine atanmış ya da üstlendiği görevleri görür.
- Yeni görev açılınca atanan role/kişiye "Yeni görev: …" bildirimi de düşer.
- Role giden bildirim rolün gerçek, aktif üyelerine gider; admin/superuser yalnızca bu yüzden alıcı olmaz.
- Yorum herhangi bir proje kaydına (`apps.*` modelleri; kullanıcı, denetim günlüğü, bildirim hariç)
  bağlanabilir. `@kullanıcıadı` (büyük/küçük harfe duyarsız) bahsedilene bildirim gönderir; yazar kendi
  bahsinden bildirim almaz. Yorum silinmez, yalnızca yazarı düzenler; eski metin denetim günlüğüne yazılır,
  düzenlemede yalnızca yeni eklenen bahsedilenlere bildirim gider.
- Yorum panelindeki "Geçmiş" (`record-history`) o kaydın denetim kayıtlarını giriş yapmış herkese
  gösterir; IP adresi gösterilmez.

## 2026-10-15 — İş akışı: anlık iletim

- WebSocket `/ws/notifications/`, oturum çereziyle; giriş yoksa 4401 ile kapanır. Kullanıcı başına grup
  `user_<id>`. Mesajlar commit sonrası gönderilir: `notification.created` (`id, title, body, level,
  task_id`), `notification.read`, `task.changed` (`id, status`). Redis'e ulaşılamazsa hata loglanır,
  işlem etkilenmez.
- Frontend bağlantı koparsa üstel bekleme ile (en çok 30 sn) yeniden bağlanır; bağlı değilken
  okunmamış sayısı ve açık görevler 30 sn'de bir yoklanır.
- Görev/bildirimden kayda gitmek için her modül kendi detay sayfasını
  `frontend/src/workflow/recordLinks.ts` içindeki `RECORD_ROUTES`'a ekler. Yorum paneli:
  `<RecordPanel contentType="inventory.lot" objectId={lot.id} />`.
- `channels.testing` daphne'yi içe aktardığı için `daphne` geliştirme bağımlılıklarına eklendi
  (yalnızca WebSocket testleri; sunucu uvicorn olarak kalır).

## 2026-10-15 — Karar D-2: Lot numarası biçimi (CUMHUR kararı)

Lot numarası `<önek>-YYMMDD-NNN`: `H-` satın alma (mal kabul), `B-` üretim (bulk şarj), `D-` dolum.
Sayaç önek + gün başınadır ve tüm malzemelerde ortaktır (`H-261015-001`, `H-261015-002` farklı malzemeler
olabilir); `LotNumberSequence` satırı `select_for_update` ile kilitlenir, gün Türkiye saatine göredir.
Lot no malzeme içinde tekildir (`unique(material, lot_no)`). Açılış stokunda ve iadelerde lot no
dışarıdan verilir (Excel'deki mevcut numara korunur). Tedarikçinin lot numarası ayrı alanda tutulur.

## 2026-10-15 — Karar D-3: Sayım düzeltmeyi depo onaylar (CUMHUR kararı)

Sayım düzeltme belgesini `depo` rolü hazırlar ve kendisi kaydeder; yönetim onayı adımı yoktur. CUMHUR
önerilen seçeneğin (yönetim onayı) yerine bunu seçti. Her satırda neden zorunludur; kayıt anında sistem
miktarı kilitlenerek yeniden okunur, fark `ADJUSTMENT` hareketi olarak yazılır ve belge, satırlar ve
hareketler denetim günlüğüne düşer.

## 2026-10-15 — Stok ve lot (Adım 1.3)

CUMHUR'un 2026-10-15'te onayladığı plan varsayılanları:

1. SKT'si geçmiş lot üretimde tüketilemez ve sevk edilemez (`lot_expired`), serbest olsa bile.
   Transfer ve sayım düzeltme serbesttir.
2. Bloke lot yeniden serbest bırakılabilir ya da reddedilebilir; reddedilen lot kesindir
   (geçiş yoktur), stoku karantinada kalır. Durum tablosu `apps/inventory/state.py`.
3. Kaydedilmiş mal kabul iptal edilemez ve değiştirilemez; düzeltme sayım düzeltme ya da hareketin ters
   kaydıyla yapılır. Taslak mal kabul iptal edilebilir.
4. Açılış stoku lotları `RELEASED` başlar; Excel'deki "Durum" sütunu `Karantina` verirse karantinada
   başlar. Aynı lot farklı lokasyonlarda tekrar verilebilir, ama malzeme/SKT tutarlı olmalıdır.
5. Karantinadaki lot lokasyonlar arasında taşınabilir, ama üretime verilemez ve sevk edilemez.
6. Lot etiketi için `reportlab` eklendi (100×60 mm, Code128 + QR, lot başına bir sayfa).

Diğer ayrıntılar:

- `post_movement` stoka dokunan tek yoldur: bakiyeyi `select_for_update` ile kilitler, negatif stoku
  reddeder (`negative_stock`), `ISSUE_PRODUCTION` ve `SHIPMENT` için lotun serbest ve SKT'sinin geçmemiş
  olmasını ister. `StockMovement` ve `LotLink` tablolarında UPDATE/DELETE PostgreSQL tetikleyicisiyle
  engellenir (ORM'i atlayan sorgular da dahil).
- Ters kayıt (`reverse_movement`) neden ister, bir hareket yalnızca bir kez ters kaydedilir, ters kaydın
  ters kaydı yapılmaz. Transferin ters kaydı iki bacağı birlikte geri alır.
- Mal kabule yalnızca hammadde ve ambalaj girer (`receipt_material_type`); bulk ve mamul üretimden gelir.
  Giriş kontrolü gereken malzeme karantina lokasyonuna `QUARANTINE` lotla, gerekmeyen depo lokasyonuna
  `RELEASED` lotla girer. Satırda SKT boşsa üretim tarihinden (yoksa kabul tarihinden) raf ömrüyle
  hesaplanır. Satır miktarı `convert_quantity` ile temel birime çevrilir.
- Lot serbest bırakılırken karantina lokasyonunda stoku varsa hedef lokasyon zorunludur; stok aynı
  işlemde oraya transfer edilir. Red ve bloke için not zorunludur. Lot kararını `laboratuvar` verir.
- Stoka yazan uç noktalar (`mal kabul`, `transfer`, `ters kayıt`, `sayım`, `açılış`) `depo` rolüne,
  lot kararları `laboratuvar` rolüne açıktır; stok sorgu, lot detayı ve soy ağacı her giriş yapmış
  kullanıcıya açıktır.
- `core.services.transition_status` isteğe bağlı `event_payload` alır; olay payload'ına eklenir
  (lot kararlarında olay sözleşmesindeki malzeme alanları bununla gönderilir). Yeni olay adları:
  `lot.blocked`, `goods_receipt.cancelled`, `stock_adjustment.posted`.
- Soy ağacı (`selectors.lot_trace`) tek bir özyinelemeli CTE sorgusudur (geri: girdiler, ileri:
  kullanıldığı lotlar).
- 07:00 kontrolü: inventory `system.daily_check`'i dinler, 30 gün içinde SKT'si dolan stoklu lotları ve
  minimum stok altındaki malzemeleri (reddedilen ve bloke lotlar sayılmaz) olay sözleşmesindeki
  biçimle yayınlar.
- Menü: "Depo ve stok" artık herkese görünür (önceki eşleme: depo, planlama, yönetim). Sekmeler rolle
  daralır: Stok sorgu ve Lotlar herkes; Mal kabul depo, planlama, yönetim, satın alma, laboratuvar;
  Lot onay laboratuvar; Sayım düzeltme depo ve yönetim. Laboratuvar sekmesiz adreste Lot onay'a düşer.
  (Faz 2'de Lot onay sekmesi kalktı; bkz. "Kalite kontrol (Faz 2, Adım 2.1)".)

## 2026-10-15 — Üretim (Adım 1.4)

CUMHUR'un 2026-10-15'te onayladığı plan varsayılanları:

1. Şebeke suyu depo tarafından hazırlanmaz; tartımda kendi stok lokasyonundan düşülür (D-1 ile birlikte).
   Su satırı hazırlama ekranında görünmez ve "Malzeme hazır" için beklenmez.
2. Hazırlanıp kullanılmayan malzeme üretim lokasyonunda kalır; depo mevcut transfer ekranıyla geri taşır.
   Emir iptal edilirse hazırlanan lotlar geldikleri lokasyona otomatik transfer edilir.
3. Çıktı lotu reddedilirse emir `QC_PENDING`'de kalır, planlama ve üretim bildirim alır (yeni kural
   `bulk_lot_rejected`); yeniden işleme Faz 2'de ele alınacak.
4. Hazırlama ihtiyacı aşabilir ama ihtiyacın 2 katını geçemez (`pick_exceeds_requirement`).

Diğer ayrıntılar:

- Emir onaylanınca reçetenin onaylı sürümü planlanan miktara ölçeklenir ve ihtiyaç satırları
  (`ProductionRequirement`) yazılır; sonradan reçete değişse de emir etkilenmez. Taslak dışında emir
  değiştirilemez.
- Hazırlama, lotu kaynak lokasyondan emrin üretim lokasyonuna transfer eder (`MaterialPick`). İlk hazırlama
  emri `MATERIAL_PREP`'e geçirir. Lot okutma (numara) ya da öneri listesinden seçim; öneri yalnızca
  serbest ve SKT'si geçmemiş stoku ilk SKT ilk çıkar sırasıyla gösterir.
- Şarj (D-4): şarj miktarı varsayılan olarak kalan miktar ile tank kapasitesinin küçüğüdür. Bir tankta
  aynı anda yalnızca bir açık şarj olabilir. Şarj numarası çıktı lotunun numarasıdır (B-YYMMDD-NNN, D-2);
  çıktı lotu karantinada açılır. Satır planı = ihtiyaç × şarj miktarı / emir miktarı.
- Tartım bir satırda birden çok lottan yapılabilir. Satır toplamı toleransın üstüne çıkarsa sapma notu
  zorunludur ve `production.deviation` yayınlanır. Bitişte toleransın altında kalan satır varsa bitiş
  notu zorunludur ve sapma olayı yayınlanır. Tartım yapılmış şarj iptal edilemez.
- Bitiş: çıktı miktarı tank lokasyonuna `PRODUCTION_OUTPUT` olarak girer; verim = çıktı / tartılan toplam.
  Verim `PRODUCTION_LOW_YIELD_THRESHOLD_PCT` (varsayılan 97) altındaysa `production.low_yield` yayınlanır.
  Emrin tüm miktarı şarjlanıp şarjlar bitince emir `QC_PENDING`'e geçer; tüm çıktı lotları serbest
  bırakılınca (`lot.released`) emir kendiliğinden `COMPLETED` olur.
- Yetki: emir yazma `planlama`, hazırlama `depo`, şarj ve tartım `uretim`; okuma her giriş yapmış
  kullanıcıya açık. Menüde "Üretim" artık `depo` rolüne de görünür (hazırlama ekranı için); depo yalnızca
  Malzeme hazırlama sekmesine düşer.
- Olay payload'larına eklenenler: `production_order.approved` için `priority`; şarj olayları
  `production_batch.started` / `production_batch.completed` olay sözleşmesindeki alanlarla yayınlanır.
- Hesaplanan miktarlar (kalan, önerilen şarj miktarı) API'de diğer miktarlar gibi metin döner.


## 2026-10-15 — Kalite kontrol (Faz 2, Adım 2.1)

CUMHUR'un 2026-10-15'te onayladığı plan varsayılanları ve kararları:

1. **Lot serbest bırakma ve ret yalnızca kalite kararıyla** (`quality.services.decide`). Depo ekranındaki
   "Lot onay" sekmesi ve `POST /inventory/lots/{id}/reject/` kaldırıldı. `inventory.release_lot` /
   `reject_lot` yalnızca `quality_decision=True` ile çağrıldığında çalışır.
2. **Karar D-5 "Admin, gerekçeli"**: `POST /inventory/lots/{id}/release/` yalnızca `admin` rolüne açık,
   not zorunlu (`note_required`); not "Elle serbest bırakma (D-5): …" önekiyle lota ve denetim
   günlüğüne yazılır. Laboratuvarın "Bloke et" işlemi kalır; bloke lot yeni numuneyle yeniden karara gider.
3. **Karar D-7 "Örnek listeyle başla"**: 11 standart test migration ile gelir (PH, VISK, YOGUNLUK,
   AKTIF_MADDE, KATI_MADDE, RENK, KOKU, GORUNUS ve dolum için DOLUM_MIKTARI, SIZDIRMAZLIK, ETIKET).
   `seed_quality_demo` (seed_demo sonunda çağrılır) giriş kontrollü her hammaddeye giriş, her bulk ürüne
   son kontrol spesifikasyonu yazıp onaylar. Laboratuvar değerleri yeni sürümle düzenler.
4. **Yeniden işleme "İkisi de olsun"**: REWORK kararı (yalnızca bulk lot) lotu bloke eder ve planlamaya
   "Yeniden işleme emri aç: {lot}" görevi açar. Yeniden işleme emri `rework_lot` alanı dolu bir üretim
   emridir; reçete isteğe bağlıdır:
   - Reçeteyle: lotun tüm stoku + reçete "planlanan miktar − lot miktarı" kadar ölçeklenir (harmanlama;
     planlanan miktar lot miktarından büyük olmalı, `rework_quantity_too_small`).
   - Reçetesiz: lotun tüm stoku + planlamacının girdiği düzeltme listesi (`ReworkAddition`: malzeme,
     miktar, birim, tolerans, su mu, talimat).
   - İkisinde de düzeltme satırları eklenebilir. Lot satırı sabit lottur (`ProductionRequirement.lot`),
     toleransı 0, depoda hazırlanmaz (`rework_lot_not_picked`); bulunduğu yerden (tank) tüketilir.
   - **CLAUDE.md kural 4'ün tek istisnası:** bloke lot yalnızca kendi yeniden işleme emrinde tüketilebilir
     (`post_movement(..., rework=True)`, lot bloke değilse `rework_lot_not_blocked`). Lot başına tek açık
     yeniden işleme emri olur (`rework_order_exists`).
   - Yeni B- lotu eski lota `LotLink` ile bağlanır (soy ağacı korunur). Yeniden işleme emri tamamlanınca
     eski lotu üreten emir, diğer çıktıları serbestse kendiliğinden tamamlanır.
5. **Şartlı kabul**: spec dışı sonuçla laboratuvar `CONDITIONAL_RELEASE` önerir; numune "Onay bekliyor"a
   geçer, yönetime görev düşer. Yönetim onaylarsa lot serbest bırakılır; reddederse (not zorunlu) numune
   "Testte"ye döner ve laboratuvar yeniden karar verir.
6. Onaylı spesifikasyonu olmayan malzemeye de numune açılır; laboratuvar karar vermeden önce onaylı bir
   sürüm atar (`sample_has_no_specification`). Numune açılışta o anki onaylı sürümü sabitler.
7. Ret kararında Faz 1 kuralı geçerli: üretim emri "Analiz bekliyor"da kalır, planlama bildirim alır.

Diğer ayrıntılar:

- **Spesifikasyon**: malzeme + aşama başına sürümlü (Taslak → Onaylı → Eski sürüm). Aynı malzeme ve
  aşamada tek onaylı sürüm olur (veritabanı kısıtı); yenisi onaylanınca eskisi `OBSOLETE` olur. Satırı
  olmayan sürüm onaylanmaz. Taslakta satır kaldırılabilir (reçetelerdeki gibi, denetim günlüğüne yazılır).
  Sayısal satırda en az bir sınır olmalı ve beklenen metin girilmez; diğer türlerde sınır girilmez.
  Ambalaj malzemesine de spesifikasyon yazılabilir (dolum aşaması için).
- **Uygunluk**: sayısal sonuç sınırlar dahil `min ≤ değer ≤ max`; uygun/uygun değil sonuç `passed`;
  metin sonuç, `passed` verilmezse beklenen metinle büyük/küçük harf ve kenar boşlukları yok sayılarak
  karşılaştırılır. Sonucu kullanılan testin sonuç türü değiştirilemez (`test_in_use`).
- **Sonuç düzeltme**: satırın geçerli sonucu varken yeni sonuç düzeltmedir ve not ister
  (`correction_reason_required`); eski kayıt `superseded_by` ile yenisine bağlanır, silinmez. Bir satırda
  tek geçerli sonuç olur (kısmi benzersizlik kısıtı). İlk sonuç numuneyi "Testte"ye geçirir.
- **Numune durumları**: Bekliyor → Testte → (Onay bekliyor) → Karar verildi; açık numune gerekçeyle
  iptal edilebilir. Otomatik açılan numunede alan kişi ve zaman boştur; ilk sonucu giren kişi ve ölçüm
  zamanıyla dolar. Aynı lot ve aşamada tek açık numune olur (`sample_already_open`); numune yalnızca
  karantina ya da bloke lota açılır (`lot_not_sampleable`). `quality.services.open_sample` rol denetimi
  yapmaz, diğer modüllerin (dolum, Adım 2.2) çağırması içindir.
- **Şarj sırası (IN_PROCESS) numunesi** lotun durumunu değiştirmez; yalnızca Serbest (uygun) ya da Ret
  (uygun değil) kararı alır. Ret olursa `uretim` ve `planlama`'ya bildirim gider.
- **Serbest bırakma lokasyonu**: varsayılan, lotun mal kabulündeki depolama lokasyonu; karar ekranında
  değiştirilebilir. Karantinada stok varsa lokasyon zorunludur (Faz 1 kuralı).
- **CoA**: yalnızca o numunenin kararıyla serbest bırakılmış lot için (`coa_not_available`); A4,
  reportlab, Türkçe sayı biçimi. Şartlı kabulde gerekçe ve yönetim onayı da yazılır.
- **Yetki**: test tanımı, spesifikasyon, numune, sonuç ve karar yazma `laboratuvar`; şartlı kabul onayı
  `yonetim`; okuma her giriş yapmış kullanıcıya açık. Menüde "Kalite kontrol" laboratuvar ve yönetime
  görünür; laboratuvar "Numune kuyruğu"na, yönetim "Şartlı kabul onayı"na düşer.
- **Lot detayı**: "Kalite kontrol" bölümü lotun numunelerini listeler; laboratuvar açık numunesi yoksa
  numune açar, planlama bloke bulk lottan yeniden işleme emri açar (`/uretim/emirler/yeni?yeniden-isleme=<lot>`).
- `core.services.create_document` isteğe bağlı `event_payload` alır (`<belge>.created` olayına eklenir).

### Kalite olay sözleşmesi (iş akışı tablosuna ek)

| Olay | Payload |
|---|---|
| `sample.created`, `sample.in_test`, `sample.awaiting_approval`, `sample.cancelled` | `model, id, number, stage, lot_no, material_code, material_name, material_type, lot: {model, id, lot_no}` |
| `sample.decided` | yukarıdakiler + `decision` (`RELEASE`/`REJECT`/`REWORK`/`CONDITIONAL_RELEASE`), `reason` |
| `specification.approved`, `specification.obsolete` | `transition_status` payload'ı |
| `production_order.completed` | `transition_status` payload'ı (yeniden işleme sonrası asıl emri kapatmak için) |
| `production_order.approved` | yeniden işleme emrinde ek olarak `rework_lot: {model, id, lot_no}` |

İş akışı kuralları: `incoming_qc` (giriş numunesi → laboratuvar, "Giriş kontrolü: {lot}") ve
`batch_sample_analysis` (şarj sırası / son numune → laboratuvar, "Numune analizi: {lot}") artık numuneye
bağlanır ve numune karar verilince ya da iptal edilince kapanır; `conditional_release_approval`
(yönetim), `rework_order` (planlama; yeniden işleme emri onaylanınca kapanır), `in_process_out_of_spec`
(bildirim). Görev başlığı lot numarasını, açıklaması numune numarasını taşır.

## 2026-10-15 — Dolum ve ambalaj (Faz 2, Adım 2.2)

CUMHUR'un 2026-10-15'te onayladığı plan varsayılanları:

1. **Bulk hazırlanmaz, tanktan tüketilir.** Bulk lot depo hazırlamasına girmez; dolumcu tank lotunu okutur,
   tüketim lotun durduğu yerden (`TANK`) düşülür. Bir partide birden çok bulk lot tüketilebilir.
2. **Ambalaj tüketimi bitişte hesaplanır.** Parti bitince her ambalaj satırı için
   `(sağlam adet + mamul firesi) × adet başı miktar` hat başından düşülür (adet birimlerinde yukarı
   yuvarlanır); önce partide okutulan lotlar, sonra hat başındaki diğer lotlar SKT sırasıyla. Yetmezse
   `packaging_short`. Ambalaj firesi ayrıca kayıtla düşülür.
3. **Mamul SKT'si = dolum tarihi + mamulün raf ömrü** (`shelf_life_days`).
4. **Kullanılmayan ambalaj hat başında kalır**; depo stok transfer ekranıyla geri alır (Faz 1 kuralıyla aynı).
   İptal edilen emirde hazırlanan ambalaj kendiliğinden geri transfer edilir.

Diğer ayrıntılar:

- **Ortak hazırlama servisi**: Faz 1'deki `MaterialPick` deseni `inventory.picking` servisine ve soyut
  `inventory.PickRecord` modeline çıkarıldı (`pick_lot`, `return_picks`, `picked_total`). Üretim ve dolum
  aynı kuralları kullanır: lot serbest ve SKT'si geçmemiş olmalı, hazırlanan miktar fire payı dahil ihtiyacın
  iki katını aşamaz (`pick_exceeds_requirement`).
- **Ambalaj reçetesi** (`PackagingSpec`): mamul başına sürümlü (Taslak → Onaylı → Eski sürüm); tek onaylı
  sürüm (veritabanı kısıtı), yenisi onaylanınca eskisi eski sürüm olur. Onaylı sürüm değiştirilemez, kopyayla
  yeni taslak açılır; taslakta satır kaldırılabilir (denetim günlüğüne yazılır). Mamulün temel birimi adet
  türünde olmalı (`finished_unit_not_count`); dolum miktarı bulkun temel birimine çevrilebilmeli
  (kg ↔ lt için yoğunluk). Satır malzemesi `PACKAGING` olmalı.
- **Dolum emri** (`DO-`): açılırken mamulün onaylı ambalaj reçetesi sabitlenir; taslak güncellenince yeniden
  sabitlenir, onayda reçete hâlâ onaylı olmalı (`packaging_spec_not_approved`). Onayda ihtiyaç
  `planlanan adet × adet başı × (1 + fire payı)` olarak hesaplanır (adet birimleri yukarı yuvarlanır).
  "Ambalaj hazır" için her satır fire payı **hariç** ihtiyaç kadar hazırlanmış olmalı (`material_not_ready`).
  `planned_units` tam sayıdır. Dolum hattı `FILLING_LINE` türünde ve hat başı lokasyonu `PRODUCTION`
  türünde olmalı; mamul deposu `STORAGE` türünde.
- **Dolum partisi** (`FillingRun`): başlarken `D-YYMMDD-NNN` lotu karantinada açılır (D-2); emir başına tek
  açık parti. Bitişte toplam dolan adet (sağlam + mamul firesi) `PRODUCTION_OUTPUT` ile mamul deposuna
  girer, mamul firesi aynı anda `SCRAP` ile düşülür; böylece depoda sağlam adet kalır. Mamul lotu karantinada
  olduğu için sevk edilemez; serbest bırakılınca yer değiştirmez. Bitişte mamul lotuna `FINAL` numune açılır
  (`Sample.Origin.FILLING`). Kaydı olmayan parti gerekçeyle iptal edilir (`run_has_records`).
- **Bulk farkı**: teorik = `sağlam adet × dolum miktarı` (bulkun temel biriminde); gerçek = tüketilen bulk +
  bulk firesi. Fark yüzdesi `(gerçek − teorik) / teorik`, eşik `FILL_VARIANCE_THRESHOLD_PCT` (varsayılan
  1,5). Mutlak fark eşiği aşarsa `filling.bulk_variance`.
- **Fire** (`ScrapRecord`): bulk ve ambalaj firesi lotla ve hemen `SCRAP` hareketiyle; mamul firesi tam adet,
  bitişte düşülür. "Diğer" nedeni açıklama ister (`scrap_note_required`).
- **Emir kapanışı**: "Dolumu bitir" emri "Analiz bekliyor"a alır; partilerin tüm mamul lotları serbest
  kalınca (`lot.released` dinleyicisi) emir tamamlanır. Reddedilen mamul lotu emri analiz bekliyorda bırakır,
  planlama ve dolum bildirim alır.
- **Rapor**: tamamlanan partilerden; ambalaj teorik = sağlam adet × adet başı, gerçek = tüketim + fire,
  fark fire payını aşarsa işaretlenir.
- **Yetki**: ambalaj reçetesi ve emir yazma/onay/iptal `planlama`; ambalaj hazırlama ve "Ambalaj hazır"
  `depo`; parti, tüketim, okutma, fire, bitiş ve "Dolumu bitir" `dolum`; okuma her giriş yapmış kullanıcıya
  açık. Menüde "Dolum" artık `depo`'ya da görünür (ambalaj hazırlama sekmesi).
- **Okutma**: lot numarası ya da lot etiketi içeriği (`LOT:<lot_no>`) kabul edilir. Okutulan lot reçetedeki
  malzemelerden değilse `lot_material_mismatch`; hat başında olmayan ambalaj lotu `lot_not_at_line`.
  Ortak `ScanInput` bileşeni ve koli etiketi basımı Adım 2.3 ile bağlanır (hangi PR ikinci gelirse).
- **Üretim lokasyonu varsayılanı**: `production.default_production_location` dolum hattı başı lokasyonlarını
  atlar (demo verisinde DOLUM-1, URETIM-1'den önce sıralanıyordu).
- **Mamul spesifikasyonu (D-7)**: `seed_filling_demo` (seed_demo sonunda) mamullere `FINAL` spesifikasyon
  yazar: görünüş, dolum miktarı (dolum ±%1,5, ml), sızdırmazlık, etiket.

### Dolum olay sözleşmesi (iş akışı tablosuna ek)

| Olay | Payload |
|---|---|
| `filling_order.approved`, `.material_ready`, `.cancelled`, `.completed` | `transition_status` payload'ı (onayda ek olarak `product_code`) |
| `filling_run.started` | `model, id, lot_no, order: {model, id, number}, order_number` |
| `filling_run.completed` | yukarıdakiler + `output_lot` (`lot_payload` + `material_type`), `good_units`, `scrapped_units`, `sample_number` |
| `filling.bulk_variance` | `model: filling.fillingorder, id, number, lot_no, product_code, good_units, theoretical_quantity, actual_quantity, variance_pct, threshold_pct` (sayılar Türkçe biçimli metin) |

İş akışı kuralları: `packaging_prep` (depo, "Ambalaj malzemesi hazırla: {number}", ambalaj hazır olunca
kapanır), `start_filling` (dolum, "Dolumu başlat: {number}", parti başlayınca kapanır), `finished_qc`
(laboratuvar, "Mamul kontrolü: {lot}", mamul lotuna bağlı, numune karar verilince kapanır; bulkun
`batch_sample_analysis` görevi mamul numunesi için açılmaz), `filling_bulk_variance` (planlama, yönetim;
uyarı), `finished_lot_released` (sevkiyat, planlama: "Sevke hazır: {lot}"), `finished_lot_rejected`
(planlama, dolum), `filling_order_cancelled` (açık görevleri iptal eder, planlamaya bildirim).

## 2026-10-16 — İade (Faz 3, Adım 3.3)

CUMHUR'un 2026-10-16'da onayladığı plan ve kararı:

1. **İade gelince lotun tamamı karara kadar bekler** ("Tüm lot beklesin"). İade kabulünde lot `RELEASED`
   ise `BLOCKED` olur (kalite kararı yoluyla, `inventory.block_lot(quality_decision=True)`); depodaki ve
   müşteriden dönen miktar QC kararına kadar ne tüketilir ne sevk edilir. Lot zaten karantinada ya da
   blokeliyse durumu değişmez.
2. **İade ayrı modül**: `apps/returns` (`CustomerReturn`, numara `IA-`); izlenebilirlik ayrı modül:
   `apps/traceability`. Satış (`sales`) modülü ikisine de bağımlı değildir. CLAUDE.md modül tablosu
   buna göre güncellendi.

Ayrıntılar:

- **Durumlar**: Taslak → Kabul edildi → Sonuçlandı; taslak iptal edilebilir (gerekçeli). Kabulde her satır
  `RETURN` hareketiyle iadenin karantina lokasyonuna (`QUARANTINE` türü) girer; lot numarası korunur.
  Satır ürünü `FINISHED` olmalı, lot o ürünün lotu olmalı, bir iadede aynı lot bir kez.
- **İade numunesi**: kabulde lotun açık numunesi varsa o kullanılır, yoksa `stage=RETURN`,
  `origin=RETURN` numune açılır. `RETURN` aşamasında onaylı spesifikasyon yoksa ürünün `FINAL`
  spesifikasyonu kullanılır.
- **Karar → satır sonucu**: `lot.released` → yeniden sevke uygun (lot depodaki yerine, yoksa son pozitif
  hareket aldığı karantina dışı lokasyona taşınır); `lot.rejected` → imha; `REWORK` kararı → yeniden
  işleme (lot bloke kalır, planlamaya görev). `REWORK` kararı mamul lotlarda yalnızca iade numunesine
  verilebilir; dışarıda hâlâ yalnızca bulk lota. Kabulde lot zaten `REJECTED` ise satır hemen imha olur.
- **İmha**: imha satırı depo ya da sevkiyat tarafından "İmha et" ile `SCRAP` hareketiyle karantinadan
  düşülür. Tüm satırlar sonuçlanınca (imha satırları düşülmüş, diğerleri karara bağlanmış) iade
  kendiliğinden "Sonuçlandı" olur.
- **Yetki**: iade açma / düzenleme / iptal `sevkiyat`; kabul `sevkiyat` ve `depo`; imha `depo` ve
  `sevkiyat`; okuma her giriş yapmış kullanıcıya açık. Menüde "İadeler" spesifikasyondaki sevkiyat ve
  laboratuvarın yanında `depo` (kabul, imha) ve `yonetim`e de görünür.
- **Rezervasyonlar**: iade kabulü rezervasyonu olan bir lotu bloke edebilir. Lot `RELEASED` dışına
  çıkınca rezervasyonun ne olacağını Adım 3.1 (satış) belirler; hangi PR ikinci gelirse bağlar.
- **Sevkiyata bağ** (Adım 3.2'ye sözleşme): `CustomerReturn` şimdilik sevkiyatsız. Sevkiyat modülü
  `CustomerReturn.shipment` (opsiyonel FK) alanını ve "iade miktarı o sevkiyatta o lottan sevk edilenden
  fazla olamaz" kuralını ekler.

### İade olay sözleşmesi (iş akışı tablosuna ek)

| Olay | Payload |
|---|---|
| `customer_return.received`, `.closed`, `.cancelled` | `transition_status` payload'ı + `customer_code`, `customer_name`, `lots` (her satır için `lot_payload` + `disposition`) |
| `customer_return.scrap_required` | `model: returns.customerreturn, id, number` + yukarıdaki ek alanlar |

İş akışı kuralları: `return_qc` (laboratuvar, "İade kontrolü: {lot}", iade numunesi açılınca, karar ya da
iptalde kapanır), `return_rework` (planlama, "İade lotu yeniden işlenecek: {lot}"), `return_scrap` (depo,
"İade imha et: {number}", iade sonuçlanınca kapanır), `return_closed` (sevkiyata bildirim "İade
sonuçlandı: {number}"). Mamul numunesinin `rework_order` kuralı iade numunesinde çalışmaz.

## 2026-10-16 — İzlenebilirlik ve geri çağırma (Faz 3, Adım 3.4)

- **Hedef 1 sn**: spesifikasyondaki 1 dakika yerine performans testi 10.000+ hareketli, 5 seviyeli veride
  geri çağırma simülasyonunun 1 sn altında kalmasını ister (`test_recall_performance_on_deep_wide_data`).
- **İleri kapanış** tek özyinelemeli CTE ile (`LotLink`); stok, sevk ve iade miktarları lot listesine toplu
  sorgularla okunur. Sevk = `SHIPMENT` hareketleri eksi onları ters çeviren `REVERSAL`lar; iade =
  `RETURN` hareketleri.
- **Geri izleme** hammadde lotunda tedarikçi, tedarikçi lot no ve mal kabul belgesine (numara, tarih)
  iner.
- **Müşteri bilgisi** (Adım 3.2'ye sözleşme): sevkiyat modeli yokken sevk satırlarında müşteri alanları
  boştur ("Müşteri bilgisi yok"). Sevkiyat modülü `traceability.selectors._customers_for` içinde
  `SHIPMENT` hareketinin kaynağından (`source` → sevkiyat → sipariş → müşteri) `customer_id`,
  `customer_code`, `customer_name` alanlarını doldurur; rapor, API ve çıktılar bu alanları kullanır.
- **Çıktılar**: Excel (Özet, Etkilenen lotlar, Stokta kalan, Sevkiyatlar, Müşteriler) ve A4 yatay PDF.
- **Yetki**: tüm izlenebilirlik uçları ve ekran `laboratuvar` ve `yonetim` (admin her zaman).
- **API**: `/api/v1/traceability/lots/<id>/backward/`, `/forward/`, `/api/v1/traceability/recall/?lot=..`
  (1–50 lot), `/recall/xlsx/`, `/recall/pdf/`.
