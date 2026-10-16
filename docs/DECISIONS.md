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
  Ortak `ScanInput` bileşeni ve koli etiketi basımı Adım 2.3 PR'ıyla (#9) bağlandı.
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

## 2026-10-15 — Etiket, barkod ve ekler (Faz 2, Adım 2.3 ve 2.4)

- **Karar D-6 (CUMHUR kararı, "Malzemeye göre")**: mamul koli etiketi, malzemenin GTIN'i varsa GS1-128
  (01) GTIN-14 + (17) SKT + (10) lot; GTIN yoksa firma içi Code128 `LOT:<lot_no>`. Her ikisinde QR
  `LOT:<lot_no>`. SSCC palet etiketi, etiket ayarlarına GS1 firma öneki girilince açılır
  (`sscc_disabled`). GTIN `Material.gtin` alanında (8/12/13/14 hane, kontrol hanesi doğrulanır, boş
  değilse tekil); hangi kolinin GTIN'li basılacağı yalnızca bu alana bağlıdır.
- **Karar D-8 (CUMHUR kararı, "Zebra, 100×150 mm")**: tüm etiketler 100 × 150 mm. Çıktılar: ZPL II
  (varsayılan 203 dpi; yazıcı kaydında 152/203/300/600), tek etiketlik PDF ve A4 PDF (sayfada iki
  etiket, kesim çizgili). ZPL `^CI28` (UTF-8, Türkçe karakter), GS1 barkodu `^BC` mod D, diğerleri mod
  A. **ZPL gerçek bir Zebra yazıcıda henüz denenmedi**; sahte TCP yazıcıyla ve içerik denetimiyle test
  edildi. İlk gerçek yazıcıda "Deneme etiketi" ile hizalama kontrol edilmeli.
- **Okutma içeriği sözleşmesi** (`inventory.selectors.decode_scan`, `/api/v1/inventory/scan/?code=`):
  `LOT:<lot_no>` lot, `LOC:<kod>` lokasyon, `MAT:<kod>` malzeme, GS1 (00) palet, (01)/(02) GTIN ile
  malzeme, (10) varsa lot. AIM öneki (`]C1`) ve GS ayırıcısı tanınır, parantezli yazım da kabul edilir.
  Öneksiz kod sırayla lot no (büyük/küçük harf duyarsız), lokasyon kodu, malzeme kodu ve GTIN olarak
  denenir; böylece Faz 1'de basılmış düz lot etiketleri de okunur. Tanınmayan kod `scan_not_found`.
- **Ortak okutma alanı** (`ScanInput`): okuyucu klavye gibi çalışır (kod + Enter). Beklenen malzeme
  verilirse başka malzemenin lotunda kırmızı dolu uyarı, alçak uzun ses ve titreşim; doğru lotta kısa
  ses. Hazırlama ve tartım ekranları artık lotu okutmayla seçer ve odağı miktara taşır; yanlış malzeme
  sunucuya gitmeden durdurulur, sunucunun reddi (karantina vb.) yine gösterilir. Depo ekranının başlığında
  "Lot okut" alanı lot detayına götürür.
- **Yazıcı**: `masterdata.Printer` (kod, ad, IP, port 9100, dpi, lokasyon). Ham ZPL TCP ile gönderilir,
  zaman aşımı `PRINTER_TIMEOUT_SECONDS` (5 sn); ulaşılamazsa `printer_unreachable`. Her gönderim
  yazdırılan kaydın denetim günlüğüne "Etiket yazdırıldı" notu düşer. Yazıcı ve etiket ayarlarını
  yalnızca `admin` yazar; yazdırma ve PDF/ZPL indirme giriş yapmış herkese açık (etiket veri
  değiştirmez). Palet (SSCC) açma `depo`, `uretim`, `dolum`, `sevkiyat`.
- **SSCC**: uzantı hanesi + firma öneki + seri + kontrol hanesi = 18 hane; seri `LabelSettings`
  üzerinde `select_for_update` ile artar, tükenirse `sscc_exhausted`. Palet etiketi
  (`inventory.PalletLabel`) yalnızca mamul lotu için, reddedilmiş lot için açılmaz.
- **Ekler (`core.Attachment`)**: GenericFK ile lot, mal kabul, numune ve yoruma bağlanır; bir modül
  `register_attachment_target("app.model", can_add=...)` ile kayıt türünü açar. İzin verilen uzantılar
  PDF, resim (JPG/PNG/WEBP/HEIC), Office, CSV/TXT; en çok `ATTACHMENT_MAX_BYTES` (20 MB). Tabletten
  fotoğraf kamerayla çekilir; 1 MB üstü fotoğraf tarayıcıda 2000 px JPEG'e küçültülür. Dosyalar
  `MEDIA_ROOT` altında, herkese açık `/media` yok: indirme `/api/v1/attachments/<id>/download/`
  üzerinden oturumla. Ek silinmez (kural 6), gerekçeyle kaldırılır; kaldırmayı yükleyen ya da admin
  yapar, kaldırılan eki yalnızca admin görür. Yoruma ek yalnızca yorumun yazarı ekler. Ekleme ve
  kaldırma, bağlı kaydın denetim günlüğüne yazılır. Üretimde dosyalar `media` volume'ünde
  (`docker-compose.prod.yml`), nginx yükleme sınırı 25 MB.
- **Dolum tableti** (Adım 2.2 ile birleştirme): ambalaj hazırlama, bulk tüketimi, ambalaj lotu okutma ve
  fire lotu `ScanInput` kullanır. Beklenen malzeme: hazırlamada satırın malzemesi, bulkta partinin bulk
  ürünü, ambalaj okutmada ambalaj reçetesindeki kalemlerden biri (birden çok malzeme kabul edilir).
  Parti ekranında "Koli etiketi" düğmesi mamul lotunun koli etiketini önce seçili açar; GS1 ya da firma
  içi olduğu partideki `finished_product_gtin` ile gösterilir.

## 2026-10-16 — Satış siparişi ve rezervasyon (Faz 3, Adım 3.1)

Plan CUMHUR tarafından onaylandı (karar kartı, 2026-10-16). Kararlar:

- **Karar D-9 "Fiyat burada"** (CUMHUR kararı): sipariş satırına isteğe bağlı birim fiyat ve para birimi
  (TRY / EUR / USD) girilir; sipariş toplamı para birimi bazında 2 ondalıkla gösterilir. Fatura muhasebe
  programında kesilir. Fiyat girilen satırda para birimi zorunludur.
- **Karar D-11 "Müşteri bazında"** (CUMHUR kararı): `Customer.min_remaining_shelf_life_days` (boş = şart
  yok). Lotun SKT'si, ölçüm günü + bu gün sayısından önceyse lot o müşteriye rezerve edilmez. Ölçüm günü
  istenen teslim tarihi (bugünden sonraysa), yoksa bugündür. SKT'siz lot şartı karşılar. Toplamadaki engel
  (Adım 3.2) aynı kontrolü kullanır: `sales.services.shelf_life_error(lot, order)`.
- **Rezervasyon inventory modülündedir** (`inventory.StockReservation`), çünkü kullanılabilir stok hesabı
  (`inventory.selectors.available_lots`) onu düşmek zorundadır ve inventory satışa bağımlı olamaz. Kaynak
  belge genel bağla tutulur (stok hareketindeki gibi); satışta kaynak sipariş satırıdır
  (`SalesOrderLine.reservations`).
- **Onayda otomatik FEFO rezervasyonu** (öneri değil): sipariş onaylanınca her satırın eksik miktarı
  serbest, SKT'si geçmemiş, karantina dışı stoktan SKT'si en yakın lottan başlayarak rezerve edilir.
  Kullanıcı rezervasyon ekranında bir lotu bırakıp elle başka lot seçebilir (satırın eksiği kadar).
- **Eksik**: rezerve edilemeyen miktar için `sales_order.shortage` → planlamaya görev "Eksik ürün için
  üretim/dolum planla". "Eksikleri rezerve et" yeni serbest stoğu FEFO ile ekler; eksik kalmazsa
  `sales_order.fully_reserved` görevi kapatır. Elle bırakma eksik olayı yayınlamaz.
- **Rezerve stok eritilemez**: üretime çıkış, transfer çıkışı, fire ve sevkiyat bakiyeyi aktif
  rezervasyonların altına indiremez (`reserved_stock`). Sayım düzeltmesi ve ters kayıt engellenmez (sayım
  gerçeği yansıtır). Stok listelerinde `reserved_quantity` ve `available_quantity` görünür.
- **Rezerve lot serbest durumdan çıkarsa** (bloke, red; iade ile karantinaya dönerse `lot.quarantine`):
  siparişlerdeki aktif rezervasyonları bırakılır ve etkilenen siparişler için `sales_order.shortage`
  nedeniyle yeniden yayınlanır (planlamaya görev). Lot yeniden serbest kalınca rezervasyon kendiliğinden
  geri gelmez; "Eksikleri rezerve et" ile yapılır.
- **Durumlar**: Taslak → Onaylandı → Kısmen sevk edildi → Sevk edildi → Kapandı, + İptal. Satırlar yalnızca
  taslakta değişir (taslak satır silinebilir, denetimli). İptal yalnızca taslak ve onaylı siparişte
  (sevk başlamamış); kapanış yalnızca kısmen sevk edilmiş ya da sevk edilmiş siparişte, kalan aktif
  rezervasyonları bırakır. Onaylı ve hiç sevk edilmemiş sipariş kapatılmaz, iptal edilir.
- **Yetki**: sipariş yazma, onay, iptal, kapanış ve rezervasyon `sevkiyat` ve `yonetim`; okuma ayrıca
  `planlama` ve `depo`. Menüde "Sevkiyat" bu dört role görünür.

### Rezervasyon sözleşmesi (sevkiyat thread'i, Adım 3.2 için)

| İşlem | Servis | Not |
|---|---|---|
| Rezerve et | `inventory.services.reserve(actor, lot=, location=, quantity=, source=line, document_number=order.number)` | Satışta `sales.services.reserve_lot` (satır eksiği ve D-11 kontrolüyle) |
| Bırak | `inventory.services.release_reservation(actor, reservation, note)` | Satışta `sales.services.release_line_reservation` |
| Kullan (sevk) | `inventory.services.consume_reservation(actor, reservation, quantity=None, note)` | Miktar rezervasyondan azsa bölünür: kullanılan kısım yeni `CONSUMED` kayıt, kalan aktif kalır |

- Sevkiyat çıkışı sırası: önce `consume_reservation`, sonra `post_movement(..., "SHIPMENT", ...)`. Aksi
  halde çıkış rezerve stoğa çarpar (`reserved_stock`).
- Rezervasyondan farklı lot okutulursa: eski rezervasyon (gerekirse kısmen) bırakılır, okutulan lot için
  `reserve` + `consume_reservation` yapılır. Böylece her sevk edilen miktar bir `CONSUMED` rezervasyondur.
- Satırın sevk edilen miktarı şimdilik `CONSUMED` rezervasyonların toplamıdır
  (`sales.selectors.lines_with_quantities().shipped_quantity`, `sales.services.shipped_quantity`); Adım
  3.2 sevkiyat satırlarından hesaplamaya geçebilir, sözleşme aynı kalırsa iki toplam eşittir.
- Rezervasyon bir lokasyondaki stoğa bağlıdır. Rezerve stok sevk lokasyonuna taşınacaksa önce bırakılır,
  transfer edilir, hedef lokasyonda yeniden rezerve edilir.
- Sipariş durumunu `PARTIALLY_SHIPPED` / `SHIPPED` yapmak sevkiyatın işidir (`transition_status`,
  `sales_order_states`); kapanış `sales.services.close_order`.

### Satış olay sözleşmesi (iş akışı tablosuna ek)

| Olay | Payload |
|---|---|
| `sales_order.confirmed` | `transition_status` payload'ı + `customer_code`, `customer_name` |
| `sales_order.cancelled`, `.closed` | `transition_status` payload'ı |
| `sales_order.shortage` | `model: sales.salesorder, id, number, customer_code, customer_name, reason, lines: [{line_no, product_code, product_name, quantity, unit}]` |
| `sales_order.fully_reserved` | `model, id, number, customer_code, customer_name` |
| `lot.expiring` | günlük kontrolde: `days` (30), `lots: [{model: inventory.lot, id, lot_no, material_code, material_name, expiry_date, unit, reserved_quantity, orders: [SS-...]}]`; yalnızca aktif rezervasyonu olan lotlar |

İş akışı kuralları: `plan_shipment` (sevkiyat, "Sevkiyat planla: {number}"; sipariş kapanınca kapanır,
Adım 3.2 `shipment.planned` kapanışını ekler), `sales_shortage` (planlama, eksik ürün listesiyle; tamamen
rezerve edilince ya da sipariş kapanınca kapanır, açık görev varken yenisi açılmaz),
`sales_order_cancelled` (açık görevleri iptal eder), `reserved_lots_expiring` (sevkiyat, planlama; uyarı).
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
- **Rezervasyonlar**: iade kabulünde serbest lot bloke edilir ve `lot.blocked` yayınlanır; satış modülü
  (Adım 3.1) bu olayla lotun siparişlerdeki aktif rezervasyonlarını bırakır ve eksiği yeniden açar
  (`test_return_hold_releases_reservations_and_reopens_shortage`). Lot iade yüzünden karantinaya
  alınmaz, bu yüzden satıştaki `lot.quarantine` dinleyicisi iade için tetiklenmez.
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

## 2026-10-16 — Sevkiyat (Faz 3, Adım 3.2)

Plan CUMHUR tarafından onaylandı (karar kartı, 2026-10-16). Kararlar ve sözleşmeler:

- **Model `apps/sales` içinde**: `Shipment` (numara `SV-`, Karar D-10 gereği tek sipariş),
  `ShipmentLine` (planlanan: sipariş satırı + miktar) ve `ShipmentPick` (okutulan: lot, miktar, kaynak
  ve hedef lokasyon, okutan, zaman, farklı lot gerekçesi, sevkte oluşan `SHIPMENT` hareketi).
  Spesifikasyondaki `ShipmentLine.lot / picked_by / picked_at` alanları `ShipmentPick`'tedir; bir satır
  birden çok lottan toplanabilir.
- **Durumlar**: Planlandı → Toplanıyor → Yüklendi → Sevk edildi, + İptal (sevk edilmeden, gerekçeli).
  İlk okutma Toplanıyor yapar. "Yükleme tamam" `depo`, "Sevki onayla" `sevkiyat` işidir.
- **Planlama**: satır başına varsayılan miktar sipariş − sevk edilen − açık sevkiyatlarda planlanandır
  (`plannable_quantity`); azaltılabilir, aşılamaz (`shipment_exceeds_order`). Bir sipariş birden çok
  sevkiyatla parça parça gidebilir. Açık sevkiyatı olan sipariş iptal edilemez ve kapatılamaz
  (`open_shipments`).
- **Okutma malı sevk alanına taşır**: sevkiyatın sevk alanı (`loading_location`, varsayılan ilk aktif
  `SHIPPING` lokasyonu; yalnızca Planlandı'da değişir). Okutmada satırın o lottaki rezervasyonu bırakılır
  (gerekirse kısmen), lot `TRANSFER` ile sevk alanına taşınır ve orada aynı sipariş satırına yeniden
  rezerve edilir (Adım 3.1 rezervasyon sözleşmesi). Okutma geri alınırsa (Toplanıyor ya da Yüklendi'de,
  sevkten önce) lot geldiği yere döner ve kullanılabilirse yeniden rezerve edilir; iptalde tüm okutmalar
  geri döner.
- **Okutma kuralları**: lot serbest ve SKT'si geçmemiş olmalı (`assert_lot_usable`), müşterinin asgari
  raf ömrünü karşılamalı (D-11, `shelf_life_error`), satırın kalanını aşamaz (`pick_exceeds_line`).
  Miktar verilmezse satırın kalanı (lot rezerveyse rezerve miktar kadar) alınır. Satırın başka lotlarda
  rezervasyonu varken rezervesiz lot ya da rezervesinden fazlası okutulursa gerekçe istenir
  (`lot_not_reserved`); satır taahhüdünü aşan rezervasyon SKT'si en geç olandan başlayarak bırakılır.
- **Sevk onayı**: önce sevk alanındaki rezervasyonlar `consume_reservation` ile `CONSUMED`, sonra
  `post_movement(-miktar, SHIPMENT, kaynak=sevkiyat)` sevk alanından çıkar; sipariş Kısmen sevk edildi /
  Sevk edildi olur. Plaka ve şoför adı sevk onayında zorunludur (`vehicle_required`). Okutulduktan sonra
  lot kullanılamaz hale gelirse (bloke, red, karantina) sevk reddedilir (`picked_lot_unusable`,
  `picked_lot_unreserved`); depo okutmayı geri alır. Yüklendi'de geri alınan okutmada sevkiyat Yüklendi
  kalır, kalanlar sevk edilir ve eksik miktar yeni sevkiyatla gider; okutma kalmadıysa sevk reddedilir
  (`nothing_picked`) ve sevkiyat iptal edilir.
- **Eksik yükleme**: satır eksik toplanmışsa da yüklenebilir; eksik kalan miktar siparişte yeniden
  planlanabilir görünür. Satırın sevk edilen miktarı `CONSUMED` rezervasyonların toplamıdır ve sevkiyat
  okutmalarının toplamına eşittir.
- **İptal sonrası**: sevkiyat iptalinde "Sevkiyat planla" görevi yeniden açılmaz; kalan miktar siparişte
  planlanabilir görünür.
- **KVKK**: şoför TC kimlik no (11 hane) API'de yalnızca yazılır, okurken `*******1234` döner; ekranda ve
  denetim günlüğünde de maskelidir (`Shipment.AUDIT_MASKED_FIELDS`, `core.audit.mask_identifier`). Tam
  numara yalnızca irsaliye PDF'inde yazılır; irsaliye JSON'unda da maskelidir.
- **İrsaliye**: `GET /api/v1/sales/shipments/{id}/waybill.pdf` (A4) ve aynı veri `waybill/` (JSON,
  e-İrsaliye Faz 5 için) yalnızca Yüklendi ve Sevk edildi durumunda (`waybill_not_ready`). Firma bilgileri
  `.env`'den: `COMPANY_NAME`, `COMPANY_ADDRESS`, `COMPANY_TAX_OFFICE`, `COMPANY_TAX_NO`. Koli sayısı
  ürünün `KOLI` birim dönüşümünden hesaplanır (artan adet ayrıca yazılır).
- **İzlenebilirlik**: `traceability.selectors._customers_for` sevk hareketinin kaynağı `sales.shipment`
  olan satırlara müşteri kodu, adı ve sipariş numarasını doldurur (Adım 3.4 sözleşmesi).
- **İade bağı**: `CustomerReturn.shipment` (isteğe bağlı). Sevkiyat sevk edilmiş ve aynı müşterinin
  olmalı (`shipment_not_dispatched`, `shipment_customer_mismatch`); satırdaki lot o sevkiyatta olmalı
  (`lot_not_in_shipment`) ve o lottan o sevkiyata yapılan iadelerin toplamı sevk edileni aşamaz
  (`return_exceeds_shipped`). Taslak satırlar kabul anında yeniden kontrol edilir.
- **Yetki**: planlama, düzenleme, sevk onayı, iptal `sevkiyat`; okutma, geri alma, yükleme `depo`; okuma
  `sevkiyat`, `yonetim`, `planlama`, `depo`. Müşteriye sevk edilen lotlar `sevkiyat` ve `yonetim`.
- **Ekranlar**: Sevkiyat menüsünde "Sevkiyatlar" sekmesi ve sevkiyat detayı (satırlar, okutulanlar,
  yükleme ve sevk onayı, irsaliye, kayıt paneli); sipariş detayında "Sevkiyat planla" ve siparişin
  sevkiyatları; depoya "Toplama" sekmesi ve toplama tableti (satır başına kalan, rezerve lotlar önce sonra
  FEFO önerisi, raf ömrü uyarısı, `ScanInput` ile lot okutma, farklı lotta gerekçe, "Yükleme tamam");
  müşteri kartında sevk edilen lotlar; iade formunda sevkiyat seçimi.

### İnceleme sonrası kurallar (2026-10-16, PR #13)

Kod incelemesinde bulunan hatalar düzeltilirken netleşen kurallar:

- **Sevk alanı yalnızca ara duraktır.** `SHIPPING` lokasyonundaki stok bir sevkiyata okutulmuş maldır:
  FEFO rezervasyonu, elle rezervasyon (`invalid_reservation_location`), rezerve edilebilir stok listesi,
  toplama önerisi ve okutmada kaynak lokasyon seçimi karantina ile birlikte sevk alanlarını da dışarıda
  bırakır (`sales.services.UNRESERVABLE_LOCATION_TYPES`). Birden çok rampa olduğunda bir sevkiyatın
  okutması başka rampadaki okutulmuş mala dokunmaz. QC serbest bırakmada varsayılan lokasyon da sevk
  alanı olmaz (iade dönen mamul son girdiği depo yerine döner).
- **Sevk alanındaki rezervasyon siparişten elle bırakılmaz** (`reservation_on_loading`); okutma geri
  alınır. Sipariş ekranı bu satırlarda "Bırak" göstermez (rezervasyon `location_type` alanı taşır).
- **Sevk edilen = okutulan.** Yükleme ve sevk onayı satır + lot başına okutulan toplamı sevk alanındaki
  rezervasyonla karşılaştırır; sevkte kullanılan (`CONSUMED`) miktar okutulandan az kalırsa işlem geri
  alınır (`picked_lot_unreserved`).
- **Okutma eksiği kapatırsa** (rezervesiz stoktan toplanıp siparişte eksik kalmazsa)
  `sales_order.fully_reserved` yayınlanır; planlamanın eksik görevi kapanır.
- **Aynı lot no sevkiyatın birden çok ürününde varsa** okutma reddedilir (`ambiguous_lot`); lot listeden
  seçilir.
- **İrsaliye** tarihi sevk anının yerel (İstanbul) tarihidir; satırlar farklı birimdeyse toplam miktar
  yazılmaz, tek birimdeyse birimle yazılır (`total_unit`). Plaka 20, şoför adı ve taşıyıcı 100 karakteri
  aşamaz (400).
- **İade sınırı net sevke göre**: ters kayıtla geri alınan sevk hareketi sevk edilmiş sayılmaz (iade
  kontrolü ve müşteri kartı, izlenebilirlikle aynı). İade kabulünde sevkiyat satırı kilitlenir; aynı
  sevkiyata eşzamanlı iki kabul birlikte sınırı aşamaz.
- **Kilit sırası** (eşzamanlı işlemlerde kilitlenme olmasın): sevkiyat → sipariş → lot → bakiye /
  rezervasyon. Okutma, geri alma, sevk ve iptal bu sırayla kilitler; rezervasyon ve stok hareketi zaten
  lot → bakiye sırasıyla kilitler. Lot kilidi yalnızca lot satırını kilitler (`select_for_update(of=
  ("self",))`): rezervasyon, lot durumu değişikliği ve numune açmada malzeme ve ortak birim (ör. ADET)
  satırları kilitlenmez, farklı ürünlerin lotlarıyla çalışan işlemler birbirini beklemez.

### Sevkiyat olay sözleşmesi (iş akışı tablosuna ek)

| Olay | Payload |
|---|---|
| `shipment.planned` | `transition_status` payload'ı + `order {model, id, number}`, `order_number`, `customer_code`, `customer_name`, `vehicle_plate`, `order_fully_planned` |
| `shipment.picking`, `.loaded`, `.cancelled` | aynı alanlar (`order_fully_planned` hariç) |
| `shipment.dispatched` | aynı alanlar + `order_created_by_id`, `lots` (`lot_payload` + `quantity`) |

İş akışı kuralları: `plan_shipment` görevi `shipment.planned` ile, sipariş tamamen planlandıysa kapanır;
`pick_shipment` (depo, "Toplama yap: {number}", yükleme ya da iptalde kapanır); `dispatch_shipment`
(sevkiyat, "Sevki onayla / irsaliye kes: {number}", sevk ya da iptalde kapanır); `shipment_dispatched`
(bildirim "Sevk edildi: {number}" siparişi oluşturan kullanıcıya ve `yonetim`e, lot listesiyle);
`shipment_cancelled` (açık görevleri iptal eder). Bildirim kuralı artık rollerin yanında payload'dan
kullanıcı da alabilir (`NotifyRule.users`).

## 2026-10-16 — Maliyet (Faz 4, Adım 4.1)

Plan: `/mnt/project-files/faz4-costing/plan.md` (karar kartıyla onaya sunuldu). Kararlar:

- **Karar D-12 "Önerilen sıra"** (CUMHUR kararı): maliyet, satın alma, raporlama, bakım, İSG; aynı anda
  iki thread.
- **Karar D-15 "Kg başına"** (CUMHUR kararı): yönetim enerji, işçilik ve amortisman için kg başı oran girer
  (`costing.CostRate`, aşama: üretim / dolum, `valid_from` ile geçerlilik). Oranlar bulk ve dolum lot
  maliyetine **ayrı kalem** olarak eklenir. Üretimde gerçek çıktının kg'ı, dolumda doldurulan bulk'ın kg'ı
  esas alınır; kg'a çevrilemeyen miktar (yoğunluk yok) kalemi "eksik" işaretler. Oran yoksa maliyet yalnızca
  malzemedir. Oranlar silinmez; yeni tarihli oran eskisinin yerini alır, sıfır oran o kalemi kapatır.
- **Fiili maliyet, lot bazında, saklanır**: `LotCost` (sürümlü, lot başına tek güncel) + `LotCostLine`
  (kalem kalem döküm). Maliyet mal kabul kaydında, şarj bitiminde ve dolum partisi bitiminde olayla
  hesaplanır (`goods_receipt.posted`, `production_batch.completed`, `filling_run.completed`). Yeniden
  hesaplama ayrı işlemdir, not zorunludur, yeni sürüm açar; "sonraki lotlara da uygula" seçeneği bu lottan
  türeyen bulk ve mamul lotları sırayla yeniden hesaplar.
- **Alış maliyeti** = satır tutarı (birim fiyat × miktar × kur) + ek masraf payı, ÷ temel birim miktarı.
  Ek masraflar (`GoodsReceiptExtraCost`: nakliye, gümrük, diğer) satırlara miktar ya da tutar oranında
  dağıtılır; tutarda fiyatı olan satır yoksa miktara düşer. Yuvarlama farkı en büyük paya eklenir, toplam
  her zaman ek masrafa eşittir.
- **Fiyatı olmayan lot "tahmini"**: malzemenin son tahmini olmayan alış maliyeti, yoksa standart maliyeti
  (`costing.StandardCost`, Maliyet > Standart maliyetler) kullanılır. İkisi de yoksa lot "eksik" işaretlenir
  (`Lot.unit_cost` boş); tahmini ve eksik işaretleri bulk ve mamul lota taşınır.
- **Mamul maliyeti** = bulk + ambalaj + dolum oranları + fire (bulk ve ambalaj fire kayıtları), ÷ iyi adet.
  Mamul fire payı (`finished_scrap_cost`) bilgi amaçlıdır, toplama ayrıca eklenmez.
- **Para birimi**: `Currency` (TRY / EUR / USD) `core`'a taşındı (satış da oradan kullanır). Mal kabul
  satırında yabancı para ve fiyat varsa kur zorunludur (`exchange_rate_required`); TRY'de kur boşaltılır.
- **Kaydedilmiş mal kabulde fiyat düzeltmesi**: `POST /api/v1/inventory/goods-receipts/<id>/costs/`
  (`inventory.services.set_receipt_costs`), not zorunlu, denetimli, `goods_receipt.cost_changed` olayı
  yayınlar; maliyet o kabulün lotlarını yeni sürümle yeniden hesaplar. Sonraki bulk / mamul lotlar
  kendiliğinden değişmez; lot maliyet ekranında "Yeniden hesapla" (zincirle) yapılır. İptal edilmiş kabulde
  düzeltme yok (`document_locked`).
- **Yetki**: maliyet API'si (`/api/v1/costing/...`) yalnızca `yonetim` ve `admin`. Mal kabul satırındaki
  fiyat, para birimi, kur ve ek masraflar yalnızca `satin_alma` ve `yonetim`e (ve admin'e) görünür;
  diğer roller için alanlar yanıtta yoktur, `extra_costs` `null` döner ve gönderilen değerler yok sayılır.
  Depo mal kabul formunda fiyat alanı yoktur; fiyat "Fiyat ve masraflar" panelinden girilir.
- **Satın alma (Adım 4.2) ile paylaşım**: satın alma, PO'ya bağlı mal kabulde aynı alanları doldurur:
  `GoodsReceiptLine.unit_price`, `currency`, `exchange_rate` (ve gerekirse `GoodsReceipt.extra_costs`).
  Kayıttan önce doldurulursa maliyet `goods_receipt.posted` ile hesaplanır; kayıttan sonra fiyat değişirse
  `set_receipt_costs` kullanılır (olay ve yeniden hesap onun içindedir). `Lot.unit_cost` ve
  `Lot.cost_is_estimated` yalnızca `inventory.services.set_lot_cost` ile yazılır (costing çağırır).
- **Alanlar iki PR'da aynı tanımlı**: `currency` (TRY / EUR / USD, varsayılan TRY) ve `exchange_rate`
  (`DecimalField(18, 6)`, "kur (TL)", siparişteki kurla aynı hassasiyet). TL satırda kur kayıtta boşaltılır
  (siparişten 1 gelse de); maliyet hesabında boş kur 1 sayılır. İkinci birleşen PR bu iki alanı kendi
  migration'ından çıkarır.

### Maliyet okuma API'si (raporlama thread'i, Adım 4.3 için)

Tutarlar `Decimal`; para 2, birim maliyet 4 ondalık. Hepsi `apps/costing/selectors.py`'dedir.

| Fonksiyon | Dönen |
|---|---|
| `lot_unit_cost(lot)` | `UnitCost(unit_cost: Decimal \| None, is_estimated: bool)`; maliyetsiz lotta `(None, True)` |
| `stock_value(material_type=, warehouse_id=, location_id=, material=)` | `{total_value, by_type: [{material_type, value}], rows: [{material_id, material_code, material_name, material_type, unit, quantity, value, average_unit_cost, uncosted_quantity, estimated_quantity}]}` |
| `stock_value_lots(**aynı filtreler)` | lot × lokasyon satırları (miktar, birim maliyet, değer, işaretler) |
| `cost_trend(material=, date_from=, date_to=)` | ürün × ay: ortalama birim maliyet, miktar, lot sayısı |
| `batch_variance(product=, date_from=, date_to=)` | şarj başına teorik (reçete × bugünkü bilinen maliyet) ve fiili birim maliyet, fark ve % |
| `scrap_cost(product=, date_from=, date_to=)` | dolum lotu başına bulk / ambalaj fire tutarı ve mamul fire payı |
| `top_materials(date_from=, date_to=, material_type=, limit=20)` | üretim ve dolumda tüketilen malzemelerin tutara göre sıralı listesi |

Doğrudan alanlar: `inventory.Lot.unit_cost` (boş = maliyet yok) ve `Lot.cost_is_estimated`. Lotun kalem
döküm ve sürümleri `costing.LotCost` / `LotCostLine` (`is_current=True`). Pano maliyet kartları yalnızca
`yonetim` ve `admin`'e gösterilmelidir.

## 2026-10-16 — Satın alma (Faz 4, Adım 4.2)

Yeni uygulama `apps/purchasing`, ekran menüde "Satın alma" (`/satin-alma`). Plan:
`/mnt/project-files/faz4-purchasing/plan.md`.

- **Satın alma talebi `ST-`**: elle (planlama, depo, üretim, satin_alma, yonetim) ya da otomatik açılır.
  Durumlar `OPEN → ORDERED / CANCELLED`; siparişe bağlanınca ORDERED, sipariş satırı silinir ya da sipariş
  iptal edilirse yeniden OPEN. Talebi açan kişi ya da satın alma düzenler/iptal eder.
- **Otomatik talep (basit MRP)**: önerilen = ihtiyaç + minimum stok − serbest stok − açık sipariş − açık talep.
  - İhtiyaç: APPROVED..IN_PRODUCTION üretim emirlerinin reçete ihtiyacı eksi tüketilen; dolum emirlerinin
    ambalaj ihtiyacı eksi tüketilen. Şebeke suyu ve sabit lotlu satırlar dışarıda. Yalnızca RAW ve PACKAGING.
  - Serbest stok: RELEASED + QUARANTINE (gelmiş ama analiz bekleyen), SKT'si geçmemiş, rezerve hariç.
  - Açık sipariş: taslak ve onay bekleyen siparişler de sayılır (aynı ihtiyaç iki kez sipariş edilmesin).
  - İhtiyaç tarihi: açığı karşılanmayan ilk emrin planlı tarihi, yoksa bugün.
  - Her gün 07:00 kontrolünde (`DAILY_CHECK`) önerisi olan malzemeye açık talep yoksa otomatik talep açılır.
    "Öneriler" sekmesinden elle de talep açılabilir.
- **Satın alma siparişi `SA-`**: `DRAFT → PENDING_APPROVAL → APPROVED → SENT → PARTIALLY_RECEIVED → RECEIVED`,
  ve `CANCELLED`. Şartnamedeki listeye **PENDING_APPROVAL** eklendi (yönetim onayı beklerken görünür olsun).
  Yönetim siparişi notla taslağa geri gönderebilir.
- **Onay limiti (D-13)**: limit `PurchasingSettings.approval_limit_try`, yalnızca yonetim girer. Sipariş TL
  tutarı (satır tutarı × siparişteki kur) limitin altındaysa satin_alma doğrudan onaylar, değilse ya da limit
  boşsa onaya gönderir ve yonetim onaylar (`approval_limit_exceeded`). Onayda tutar, kur ve limit siparişe
  ve denetim günlüğüne yazılır.
- **Kalanı kapat**: kısmen teslim alınmış sipariş notla RECEIVED'a kapatılır (tedarikçi kalanı göndermeyecek).
  Teslimatı olan sipariş iptal edilemez (`order_has_receipts`).
- **PDF ve e-posta**: sipariş PDF'i her zaman indirilebilir; "Tedarikçiye gönder" adresi onaylatır, PDF ekli
  e-posta gönderir, sipariş SENT olur. E-posta gitmezse işlem geri alınır (`email_failed`). Sunucu `EMAIL_URL`
  ile ayarlanır (`.env.example`); boşsa e-posta konsola yazılır. Adres boş bırakılırsa yalnızca SENT işaretlenir.
- **Siparişten mal kabul**: depo "Beklenen teslimatlar"dan siparişi açar, gelen miktarı girer; mal kabul
  taslağı sipariş birimi, birim fiyatı, para birimi ve kuruyla oluşur (`GoodsReceiptLine.currency`,
  `exchange_rate`; maliyet thread'iyle aynı adlar). Bağ `purchasing.ReceiptLineLink` (mal kabul satırı →
  sipariş satırı) tablosunda; teslim alınan miktar POSTED mal kabullerden hesaplanır, ayrı sayaç yok.
  Fazla teslim toleransı varsayılan **%10** (ayarlardan değişir); taslaklar dahil aşılırsa `over_receipt`.
- **Depo fiyat görmez**: sipariş tutarları, birim fiyat ve kur yalnızca satin_alma, yonetim ve admin'e döner;
  depo siparişte miktarları görür. Sipariş PDF'i de yalnızca bu rollere açık.
- **Tedarikçi performansı**: zamanında teslim oranı = teslim tarihi geçmiş satırlardan tarihine kadar tamamı
  gelenler; QC red oranı = aralıkta kabul edilen lotlardan REJECTED olanlar. Varsayılan son 90 gün.

### Mal kabul kancası (inventory → purchasing)

`inventory` satın almayı import etmez. `inventory.services.register_receipt_post_hook(fn)` ile kaydedilen
fonksiyonlar `post_goods_receipt` içinde, satırlar stoka işlendikten sonra ve mal kabul POSTED olmadan önce,
aynı transaction'da `fn(receipt, actor)` olarak çağrılır. Satın alma bu kancada siparişin teslim
alınabilir olduğunu, malzemenin tuttuğunu ve toleransı denetler (hata işlemi geri alır), sonra siparişi
PARTIALLY_RECEIVED ya da RECEIVED yapar.

### Raporlama için okuma API'si (Adım 4.3)

| Fonksiyon | Döner |
|---|---|
| `purchasing.selectors.open_order_lines(supplier=None, material=None)` | Teslimat bekleyen sipariş satırları, `received_quantity` ve `pending_quantity` (temel birim) dolu |
| `purchasing.selectors.order_lines()` | Tüm satırlar, teslim alınan ve taslak mal kabul miktarı annotate edilmiş queryset |
| `purchasing.selectors.order_totals(order)` | `OrderTotals(total, total_try)` |
| `purchasing.selectors.purchase_suggestions(today=None)` | `Suggestion` listesi: ihtiyaç, minimum stok, serbest stok, açık sipariş/talep, önerilen, ihtiyaç tarihi, kaynak emirler |
| `purchasing.selectors.supplier_performance(date_from, date_to, supplier=None, today=None)` | `SupplierPerformance` listesi: `due_lines`, `on_time_lines`, `on_time_rate`, `received_lots`, `rejected_lots`, `reject_rate` (oranlar % ya da `None`) |

Tutarlar yalnızca yonetim/satin_alma/admin'e gösterilmeli.

### Satın alma olay sözleşmesi (iş akışı tablosuna ek)

| Olay | Payload |
|---|---|
| `purchase_request.created`, `.ordered`, `.cancelled` | `transition_status` payload'ı + `material_id`, `material_code`, `material_name`, `unit`, `quantity`, `need_date`, `source`, `reason` |
| `purchase_order.pending_approval`, `.approved`, `.draft` (geri gönderildi), `.sent`, `.cancelled` | `transition_status` payload'ı + `supplier_id`, `supplier_name`, `currency`, `total`, `total_try`, `expected_date` (en erken), `lines` (malzeme, miktar, birim, teslim tarihi) |
| `purchase_order.partially_received`, `.received` | aynı alanlar + `receipt_id`, `receipt_number` |
| `lot.rejected` | mevcut payload + `supplier_name` (satın alma lotunda) |

İş akışı kuralları: `purchase_request` (satin_alma görevi, siparişe bağlanınca ya da iptalde kapanır);
`purchase_order_approval` (yonetim görevi, onay ya da geri gönderimde kapanır); `purchase_order_returned`
(satin_alma'ya uyarı); `expected_delivery` (onayda depoya "Beklenen teslimat" bildirimi, satır listesiyle);
`purchase_order_received` (satin_alma'ya bildirim); `purchase_order_cancelled` (açık görevleri iptal eder).
`lot_rejected` bildirimi satin_alma'ya da gider ve tedarikçi adını taşır.
