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

