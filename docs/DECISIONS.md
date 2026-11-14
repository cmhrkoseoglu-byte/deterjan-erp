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
- **Değişti (2026-11-04):** lot tarihi ISO 8601 (`H-20261104-001`); biçim Sistem > Kodlama
  sistematiği ekranından ayarlanır (bkz. "2026-11-04 — Kodlama sistematiği"). İadede lot no
  dışarıdan verilmez; iade orijinal lotla girer (müşteri iadesi kararı).

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
  (2026-11-14: kaydı olan ya da bitmiş parti, fiilen yapılmamış dolumda emirle birlikte geri
  alınır ve iptal olur; bkz. "Dolum emrini geri alma".)
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
  (2026-11-14: başlamış emir planlamaca iptal edilemez; fiilen yapılmamış dolumu admin ve yönetim
  "Dolum emrini geri alma" yetkisiyle geri alır; bkz. "Dolum emrini geri alma".)
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
| `filling_run.cancelled` | başlama alanları + `output_lot` (`lot_payload` + `material_type`), `reason` |
| `filling_run.completed` | yukarıdakiler + `output_lot` (`lot_payload` + `material_type`), `good_units`, `scrapped_units`, `sample_number` |
| `filling.bulk_variance` | `model: filling.fillingorder, id, number, lot_no, product_code, good_units, theoretical_quantity, actual_quantity, variance_pct, threshold_pct` (sayılar Türkçe biçimli metin) |

İş akışı kuralları: `packaging_prep` (depo, "Ambalaj malzemesi hazırla: {number}", ambalaj hazır olunca
kapanır), `start_filling` (dolum, "Dolumu başlat: {number}", parti başlayınca kapanır), `finished_qc`
(laboratuvar, "Mamul kontrolü: {lot}", mamul lotuna bağlı, numune karar verilince kapanır; bulkun
`batch_sample_analysis` görevi mamul numunesi için açılmaz), `filling_bulk_variance` (planlama, yönetim;
uyarı), `finished_lot_released` (sevkiyat, planlama: "Sevke hazır: {lot}"), `finished_lot_rejected`
(planlama, dolum), `filling_order_cancelled` (açık görevleri iptal eder, planlamaya bildirim).
(2026-11-14: `finished_qc` görevi `filling_run.cancelled` ile de kendiliğinden kapanır; bkz.
"Dolum emrini geri alma".)

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

## 2026-10-16 — Raporlama ve panolar (Faz 4, Adım 4.3)

Plan kartla CUMHUR'a sunuldu; cevap beklenirken önerilen seçenekle ("Onayla") ilerlendi.

- **Uygulama `reporting`** diğer modüllerin verisini yalnızca okur (modelleri ve `selectors`
  fonksiyonları), hiçbir modeli değiştirmez. Tek tablosu `ReportJob` (arka plan dosyası).
  Bağımlılık zincirinin en üstündedir; kimse `reporting`'e bağımlı olmaz.
- **Panolar** (`/api/v1/reporting/dashboards/<kod>/`): `management` (yonetim, planlama),
  `warehouse` (depo, planlama, yonetim), `lab` (laboratuvar, planlama, yonetim), `production`
  (uretim, planlama, yonetim), `shipping` (sevkiyat, depo, planlama, yonetim); admin hepsini görür.
  Tanımlar: haftalık = pazartesiden bugüne; dökme üretim = biten şarjların gerçek çıktısı
  (temel birim); mamul = biten dolum partilerinin sağlam adedi; **fire oranı** = son 7 günde
  biten partilerde mamul firesi ÷ (sağlam + fire); QC bekleyen = kararı verilmemiş numuneler,
  bekleme numune açılışından; SKT yaklaşan = 30 gün (geçmişler dahil); gecikmiş görev = açık ve
  `due_at` geçmiş, atanan role göre. Tank doluluğu lokasyondaki stokun kapasite birimine
  dönüşümü ÷ kapasite (dönüşüm yoksa gösterilmez).
- **Raporlar** (`/api/v1/reporting/reports/<kod>/`, tanımlar `apps/reporting/reports.py`):
  stok durumu ve stok hareketleri (depo, planlama, yonetim, satin_alma), üretim (uretim,
  planlama, yonetim), dolum (dolum, planlama, yonetim), QC (laboratuvar, planlama, yonetim),
  sevkiyat (sevkiyat, planlama, yonetim), görev süreleri (planlama, yonetim). Tarih filtresi
  boşsa son 30 gün, en fazla 366 gün. Üretimde sapma = tolerans dışı tartım satırı; QC red oranı
  yürürlükteki karara göre; görev türü kural kodundan, adı görev başlığının ":" öncesi.
- **Tutar görünürlüğü**: sütunun `sensitive` alanı — `cost` (lot maliyeti, stok değeri) yalnızca
  yonetim ve admin (D-15), `price` (alış fiyatı) satin_alma, yonetim ve admin. Ekran, Excel ve
  PDF aynı süzmeyi kullanır; yönetim panosunda stok değeri de yalnızca bu rollere döner.
- **Excel / PDF**: `POST reports/<kod>/export/` `{file_format: xlsx|pdf, ...filtreler}`.
  5.000 satıra kadar dosya hemen döner; daha büyüğü `ReportJob` olarak Celery'de hazırlanır
  (202). PDF en fazla 10.000 satır (`pdf_too_large`, Excel önerilir). Dosyayı yalnızca isteyen
  kişi görür ve indirir; 7 gün saklanır, sabah 07:00 kontrolünde silinir, kayıt `EXPIRED` kalır.
  Hemen inen dosyalar denetim günlüğüne `custom` kaydı olarak yazılır.
- **Rapor işi durumları**: QUEUED → RUNNING → DONE → EXPIRED; QUEUED/RUNNING → FAILED.

### Rapor olay sözleşmesi (iş akışı tablosuna ek)

- `report_job.done` / `report_job.failed`: payload `{"model": "reporting.reportjob", "id",
  "repr", "report_code", "title", "file_format", "row_count", "requested_by_id", "error"}`,
  aktör yok (sistem). Kurallar `report_ready` ve `report_failed` yalnızca isteyene bildirim
  gönderir; bildirim bağlantısı Panolar ve raporlar > İndirmeler.

### Bakım ve İSG bağlantısı

Bakım ve İSG PR'ı (#17) ikinci birleştiği için bağlantıyı o yaptı. Üretim panosunda açık duruştaki
tankın kartı duruş nedeni ve başlangıcını kırmızıyla gösterir (`downtime: {reason, reason_display,
started_at}`). Yönetim panosuna iki kutu eklendi: **Bakım** (açık iş emri, süresi geçen plan, açık
duruş, son 7 günde duruş süresi; `maintenance` anahtarı) ve **İSG olayları** (son 30 gün, yaralanmalı
ve açık olay; `hse` anahtarı).

## 2026-10-16 — Bakım (Faz 4, Adım 4.4)

Plan: `/mnt/project-files/faz4-maintenance-hse/plan.md` (karar kartıyla onaya sunuldu). Kararlar:

- **Karar D-14 "İstisnalı"** (CUMHUR kararı): tankta şarj başlarken tankın son tamamlanan şarjı başka bir
  dökme üründense ve o şarjın bitişinden sonra tamamlanmış bir temizlik iş emri yoksa şarj başlamaz
  (`cleaning_required`). Laboratuvar **temizliksiz geçiş** çiftlerini tanımlar (`ChangeoverRule`, yönlü:
  önceki ürün → sonraki ürün). Aynı ürün art arda temizliksiz geçer; tankta hiç şarj yoksa kural uygulanmaz.
  Temizlik kaydı tek adımda tamamlanan `CLEANING` türü iş emridir ("Temizlik kaydı gir", görev açmaz).
- **Kalibrasyon** (onaylı Faz 4 planı): terazinin kalibrasyon planının sıradaki tarihine ayarlardaki gün
  (varsayılan **7**) ya da daha az kaldıysa tartım ekranı sarı uyarı gösterir; tarih geçmişse tartım reddedilir
  (`calibration_overdue`). Tartım kaydına kullanılan terazi yazılır (`BatchConsumption.scale`). Aktif terazi
  tanımlıysa su (D-1, sayaçtan) dışındaki tartımda terazi zorunludur (`scale_required`); terazi tanımlı
  değilse tartım eskisi gibi terazisiz yapılır. "Uygun değil" sonuçlu kalibrasyon teraziye kalibrasyon
  duruşu açar ve planı ileri atmaz. Kalibrasyon planı olmayan terazi engellenmez ("Kalibrasyon planı yok").
- **Duruş**: açık duruştaki (bitişi girilmemiş) ekipman üretim ya da dolum emrine atanamaz, emir onaylanamaz,
  şarj / dolum partisi başlatılamaz, teraziyle tartım yapılamaz (`equipment_down`). Ekipman başına tek açık
  duruş. Arıza bildirimi her rola açıktır; onarım iş emri açar ve isteğe bağlı olarak arıza duruşu başlatır;
  iş emri tamamlanınca bağlı açık duruş kendiliğinden kapanır.
- **Bakım planı**: periyot gün **ya da** çalışma sayısıdır (tankta tamamlanan şarj, dolum hattında tamamlanan
  dolum partisi; son yapılmadan bu yana). Kalibrasyon planı yalnızca terazide ve gün bazlıdır. Günlük 07:00
  kontrolünde sıradaki tarihine ayarlardaki gün (varsayılan **7**) kalan ya da çalışma sayısına ulaşan ve açık
  iş emri olmayan plan için `BK-` iş emri açılır; termini geçen planlar yönetime tek bildirimle gider.
  İş emri tamamlanınca gün bazlı plan tamamlanma günü + periyoda ilerler.
- **Roller** (karar kartında önerilen "mevcut roller"): bakım ve temizlik **uretim**, dolum hattı **dolum**,
  kalibrasyon **laboratuvar** (sorumlu rol ekipman türünden önerilir, planda değiştirilebilir). İş emrini
  sorumlu rol ya da yönetim yürütür. Planları uretim, dolum, laboratuvar ve yönetim yönetir; duruşu bu
  roller ve planlama girer; temizliksiz geçişleri laboratuvar tanımlar; ayarları yönetim değiştirir.
- **Yedek parça**: stoklu parça serbest lottan yeni `ISSUE_MAINTENANCE` ("Bakım sarfı") hareketiyle düşülür
  (rezerve stok ve negatif stok kuralları geçerli); stoksuz parça açıklama ve miktardır. Stoktan parça
  düşülmüş iş emri iptal edilemez.
- **İş emri durumları**: `OPEN → IN_PROGRESS → COMPLETED`, `OPEN → COMPLETED` (tek adımda kayıt) ve
  `CANCELLED` (neden zorunlu). Tamamlamada yapılan iş zorunlu, kontrol listesinin tüm maddeleri işaretli
  olmalı; kalibrasyonda sonuç (uygun / uygun değil) zorunlu.

### Ekipman kancası (masterdata → maintenance)

Üretim ve dolum bakımı import etmez. `masterdata.services.register_equipment_guard(fn)` ile kaydedilen
fonksiyonlar `masterdata.services.check_equipment(equipment, use, **context)` içinde çağrılır; engel için
`BusinessRuleError` fırlatır, uyarıları liste olarak döner. Kullanım yerleri: üretim emri açma/güncelleme/
onay ve dolum emri açma/onay (`use="assign"`), şarj ve dolum partisi başlatma (`"start"`, `product`
ile), tartım (`"weigh"`, terazi).

### Stok hareketi kancası (inventory → hse)

`inventory.services.register_movement_hook(fn)`: `post_movement` her hareketi yazdıktan sonra aynı
transaction içinde `fn(actor, movement)` çağrılır (İSG depolama limiti denetimi bunu kullanır).

### Bakım okuma API'si (raporlama thread'i, Adım 4.3 için)

| Fonksiyon | Döner |
|---|---|
| `maintenance.selectors.downtime_summary(date_from, date_to, equipment=None)` | `DowntimeRow` listesi: `equipment_id`, `equipment_code`, `equipment_name`, `reason`, `reason_display`, `count`, `minutes` (aralıkla kırpılır, açık duruş şimdiye kadar) |
| `maintenance.selectors.open_work_orders()` | Açık ve yapılmakta olan iş emirleri (termine göre queryset) |
| `maintenance.selectors.due_plans(today=None)` | Vadesi gelmiş aktif planlar: `PlanStatus(plan, next_due_date, runs_done, is_due, is_overdue)` |
| `maintenance.selectors.calibration_status(today=None)` | Aktif teraziler: `CalibrationStatus(equipment, status OK/DUE_SOON/OVERDUE/NO_PLAN, next_due_date, days_left, is_down)` |
| `maintenance.selectors.open_downtime(equipment)` | Ekipmanın açık duruşu ya da `None` |

API karşılıkları: `/api/v1/maintenance/downtime-summary/`, `/work-orders/?status=OPEN&status=IN_PROGRESS`,
`/plans/`, `/calibration/`, `/downtimes/?is_open=true`.

### Bakım olay sözleşmesi (iş akışı tablosuna ek)

| Olay | Payload |
|---|---|
| `maintenance_work_order.created`, `.in_progress`, `.completed`, `.cancelled` | belge payload'ı + `equipment_id`, `equipment_code`, `equipment_name`, `title`, `kind`, `kind_display`, `source`, `responsible_role`, `due_date`, `open_task` |
| `downtime.started`, `downtime.ended` | `equipment_id`, `equipment_code`, `equipment_name`, `reason`, `reason_display`, `started_at`, `ended_at`, `minutes`, `note` |
| `maintenance.overdue` | `count`, `plans` (`equipment_code`, `title`, `next_due_date`, `runs_done`) |

İş akışı kuralları: `maintenance_work_order_<rol>` (iş emrinin sorumlu rolüne görev; `open_task=False` olan
tek adımlı temizlik kaydında görev açılmaz; tamamlanınca ya da iptalde kapanır), `equipment_down` (planlama ve
yönetime uyarı), `equipment_up` (planlamaya bilgi), `maintenance_overdue` (yönetime uyarı).

## 2026-10-16 — İSG ve çevre (Faz 4, Adım 4.5)

Plan: `/mnt/project-files/faz4-maintenance-hse/plan.md`. Kararlar:

- **Tehlike bilgisi**: malzeme kartında GHS piktogramları (sınıf olarak da kullanılır), uyarı kelimesi
  (Tehlike / Dikkat; piktogram varsa zorunlu) ve H/P/EUH ifadeleri. İfade listesi SEA Türkçe metinleriyle
  58 kayıtla gelir; yönetim ve laboratuvar ekler, düzeltir, pasife alır. Tehlike bilgisini yönetim ve
  laboratuvar girer. Kayıt `Material.is_hazardous` bayrağını piktogram olup olmamasına göre günceller; bayrak
  ana veri formundan elle de işaretlenebilir (tehlike bilgisi girilmeden önce), bilgi kaydedilince ona uyar.
  Tehlikeli malzemenin lotları stok listesi, lot kartı, tartım ekranında uyarı simgesiyle görünür.
- **GBF arşivi**: malzeme başına tek geçerli GBF; yeni revizyon öncekini arşive alır, eskisinden eski
  tarihli revizyon geçerlinin yerine girilemez (`older_revision`), ileri tarihli revizyon ve revizyondan önce
  biten geçerlilik reddedilir. PDF kayıttan sonra ek olarak yüklenir; dosyasız GBF kaydedilir ama raporda
  "Dosya yok" görünür. **Eksik/eskimiş GBF raporu** aktif hammaddeleri ve tehlikeli işaretli malzemeleri
  tarar, sırasıyla: GBF yok, dosya yok, geçerliliği dolmuş, eskimiş (revizyon ayarlardaki aydan, varsayılan
  36, eski). Excel çıktısı var. GBF'yi yönetim girer; yönetim, depo ve laboratuvar görür.
- **Depolama limitleri**: lokasyon × tehlike sınıfı için kg limiti (yönetim tanımlar; yönetim ve depo
  görür). Miktar kg'a çevrilerek (yoğunluk ve dönüşümlerle) toplanır. Piktogramlı bir malzeme limitli bir
  lokasyona girdiğinde (mal kabul, transfer, iade, üretim çıktısı; her pozitif hareket) işlem commit
  olduktan sonra limit aşılmışsa depo ve yönetime uyarı bildirimi gider. İşlem engellenmez (planda "uyarı").
  Lokasyon limit üstündeyken gelen her yeni tehlikeli giriş yeniden uyarır.
- **Atık kayıtları** (`AT-`, yalnızca yönetim): atık kodu (yıldızlı kod tehlikeli atıktır), tanım, kg,
  lisanslı firma, teslim tarihi, belge no ve belge eki. İleri tarihli teslim, pasif firma ve teslim gününde
  lisansı dolmuş firma reddedilir. Hatalı kayıt nedenle iptal edilir.
- **Olay / kaza kayıtları** (`OL-`): her rol bildirir (ana sayfada düğme); tür, zaman, yer, anlatım,
  yaralanma, ağırlık. Yönetime inceleme görevi açılır, yaralanma varsa ayrıca uyarı gider. Yönetim inceler
  (kök neden, düzeltici faaliyet, sorumlu, termin) ve kapatır ya da iptal eder. Yaralanan kişinin
  mahremiyeti için yönetim dışındaki roller yalnızca kendi bildirdiklerini görür. Durumlar:
  `OPEN → INVESTIGATING → CLOSED`, açık ya da incelenen olay iptal edilebilir (neden zorunlu).

### İSG okuma API'si (raporlama thread'i, Adım 4.3 için)

| Fonksiyon | Döner |
|---|---|
| `hse.selectors.incident_summary(date_from, date_to)` | `IncidentSummary(total, injury_count, open_count, by_type, by_severity)`; satırlar `CountRow(code, label, count)`, tüm seçenekler listelenir; `occurred_at` yerel tarihine göre, iki uç dahil, iptaller hariç; `open_count` aralıktaki açık/incelenen olaylar |
| `hse.selectors.waste_summary(date_from, date_to)` | `WasteSummaryRow(waste_code, description, is_hazardous, count, quantity_kg)`; `delivered_on`'a göre, iptaller hariç |
| `hse.selectors.sds_gaps(today=None)` | Sorunlu GBF satırları `SdsStatus(material_id, material_code, material_name, is_hazardous, status MISSING/NO_FILE/EXPIRED/OUTDATED, sds_id, revision_no, revision_date, valid_until, has_file)` |
| `hse.selectors.storage_utilisation(location=None)` | `StorageUtilisation(limit_id, location_code, location_name, hazard_class, hazard_class_display, limit_kg, quantity_kg, pct, exceeded)`, aktif limitler |

API karşılıkları: `/api/v1/hse/summary/?date_from&date_to` (yönetim), `/sds-gaps/`, `/storage-utilisation/`.

### İSG olay sözleşmesi (iş akışı tablosuna ek)

| Olay | Payload |
|---|---|
| `incident.created`, `.investigating`, `.closed`, `.cancelled` | belge payload'ı + `incident_type`, `incident_type_display`, `occurred_at` ("gg.aa.yyyy SS:DD"), `place`, `injury`, `severity` |
| `waste_record.created`, `.cancelled` | belge payload'ı; `created` ayrıca `waste_code`, `is_hazardous`, `quantity_kg`, `contractor_name` |
| `hse.storage_limit_exceeded` | `model: "masterdata.location"`, `id`, `repr`, `location_code`, `hazard_class`, `hazard_class_display`, `quantity_kg`, `limit_kg` |

İş akışı kuralları: `incident_review` (yönetime inceleme görevi; kapanınca ya da iptalde kapanır),
`incident_injury` (yaralanmalı olayda yönetime uyarı), `storage_limit_exceeded` (depo ve yönetime uyarı).

## 2026-10-16 — Faz 5 kararları (D-16 … D-20)

CUMHUR'un 2026-10-16 19:07'de kartlarla verdiği kararlar (hepsi önerilen seçenek):

- **D-16 "Önce canlı"**: canlıya geçiş hazırlığı (Adım 5.4–5.6) önce; terazi ajanı, muhasebe aktarımı ve
  e-İrsaliye sonraki grupta.
- **D-17 "Belli değil"**: muhasebe programı henüz seçilmedi; programdan bağımsız XML/Excel aktarımıyla
  başlanır, program belli olunca bağlayıcı eklenir.
- **D-18 "Bu sistemde"**: cari ve malzeme kartları bu sistemde açılır, muhasebeye tek yönlü gider; muhasebedeki
  mevcut kartlar kodla eşleştirilir.
- **D-19 "e-Fatura firması"**: e-İrsaliye, firmanın e-Faturayı gönderdiği özel entegratör üzerinden.
- **D-20 "Yerel sunucu"**: sistem fabrikadaki sunucuda çalışır (UPS, RAID, yedeğin ayrı konumda kopyası,
  uzaktan erişim için VPN). Gerekçe: backend etiket yazıcılarına fabrika ağında TCP ile ZPL gönderir,
  terazi ajanı ve tabletler de o ağdadır. Docker Compose kurulumu bulutta da çalışır (CLAUDE.md §10).

## 2026-10-16 — Canlı ortam, yedek, izleme ve giriş güvenliği (Faz 5, Adım 5.4 ve 5.5)

Plan: `/mnt/project-files/faz5-canli-guvenlik/plan.md`. Kurulum adımları `docs/KURULUM.md`, kişisel veri
envanteri `docs/KVKK.md`, canlı öncesi kontrol listesi `docs/CANLI-KONTROL-LISTESI.md`.

### Giriş güvenliği

- **Şifre politikası**: en az 10 karakter (`PASSWORD_MIN_LENGTH`), en az bir harf ve bir rakam, kullanıcı
  bilgisine benzemeyen, yaygın olmayan, yalnızca rakamdan oluşmayan. Yalnızca yeni ve değişen şifrelere
  uygulanır. Kullanıcı kendi şifresini Güvenlik sayfasından değiştirir (`POST /api/v1/auth/password/`).
- **Hesap kilidi**: aynı kullanıcı adıyla 15 dakika içinde 5 hatalı denemede (şifre ya da doğrulama kodu)
  hesap 15 dakika kilitlenir (`LOGIN_LOCKOUT_*`). Sayaç veritabanında, kullanıcı adına göre tutulur: var
  olmayan kullanıcı adları da kilitlenir, böylece yanıt kullanıcı adının var olup olmadığını belli etmez.
  Kilitliyken doğru şifre de reddedilir (`account_locked`). IP başına sınır (`LOGIN_RATE_LIMIT`) ayrıca
  sürer. Kilit denetim günlüğüne yazılır; kullanıcı varsa admin rolüne bildirim gider (`user.locked`,
  kural `user_locked`). Admin kilidi Sistem > Kullanıcılar'dan açar (`POST /users/{id}/unlock/`). Başarılı
  giriş sayacı sıfırlar. Yönetim paneli girişi aynı kurala tabidir.
- **Hareketsizlik süresi**: son kullanıcı etkinliğinden 60 dakika sonra (`SESSION_IDLE_TIMEOUT_MINUTES`)
  oturum kapanır, API `401 {"code": "session_expired"}` döner; mutlak süre 12 saat kalır. SPA her istekte
  `X-ERP-Idle-Seconds` başlığıyla kullanıcının kaç saniyedir ekrana dokunmadığını bildirir; arka planda
  kendiliğinden yenilenen ekranlar (bildirim zili, panolar) oturumu açık tutmaz. Kapanış denetim günlüğüne
  "Hareketsizlik nedeniyle oturum kapandı" notuyla yazılır.
- **Saha tableti**: admin, tabletin tarayıcısından Sistem > Bu cihaz ile cihazı "saha tableti" işaretler
  (imzalı, 5 yıllık, HttpOnly çerez; `POST /api/v1/auth/field-device/`). İşaretli cihazda kim giriş
  yaparsa yapsın hareketsizlik süresi 10 dakikadır (`FIELD_DEVICE_IDLE_TIMEOUT_MINUTES`). Önerilen seçenek;
  karar kartı cevap bekliyor (alternatif: depo/üretim/dolum/sevkiyat rollerine göre).
- **İki aşamalı doğrulama (TOTP, RFC 6238)**: telefondaki doğrulayıcı uygulamayla 6 haneli kod; kurulumda 10
  tek kullanımlık kurtarma kodu (yalnızca bir kez gösterilir, HMAC özeti saklanır). Aynı kod ikinci kez
  kullanılamaz; ±30 sn saat kayması kabul edilir. **Admin ve yönetim rollerinde zorunlu**
  (`OTP_REQUIRED_ROLES`; geliştirme ortamında varsayılan boş). Önerilen seçenek; karar kartı cevap
  bekliyor. Zorunlu rol kurulum yapmadan girerse yalnızca Güvenlik sayfasını kullanabilir (diğer API'ler
  `403 otp_setup_required`), yönetim paneline giremez. Diğer roller isterse açar ve şifresiyle kapatır;
  zorunlu rolde kapatılamaz. Telefonunu kaybedenin doğrulamasını admin sıfırlar
  (`POST /users/{id}/reset-otp/`), kullanıcı sonraki girişte yeniden kurar. Hatalı kod başarısız giriş
  sayılır (kilide dahil). Yönetim paneli girişinde de kod alanı vardır.

### Kimlik doğrulama API sözleşmesine eklenenler

- `POST /auth/login/` gövdesine isteğe bağlı `otp_code`. Yeni hata kodları: `account_locked`,
  `otp_required` (kodu isteyip aynı isteği `otp_code` ile tekrarla), `invalid_otp`. Kurtarma kodu da
  `otp_code` olarak girilir.
- `me` yanıtına: `otp_enabled`, `otp_setup_required`, `field_device`, `idle_timeout_seconds`.
- `GET /auth/security/`, `POST /auth/password/`, `POST /auth/otp/setup/` (QR kodu SVG, anahtar),
  `POST /auth/otp/confirm/` (kurtarma kodları), `POST /auth/otp/recovery-codes/`, `POST /auth/otp/disable/`,
  `POST /auth/field-device/` (admin).
- Kullanıcı listesinde `is_locked`, `otp_enabled`; admin işlemleri `unlock`, `reset-otp`.

### İzleme (`ops` uygulaması)

- Celery Beat her dakika `ops.heartbeat` (beat ve worker canlı mı), her 5 dakikada `ops.run_checks`
  çalıştırır. Kontroller: gece yedeği (son başarılı yedek 26 saatten eski, son yedek başarısız ya da ayrı
  konuma kopyalanamadıysa sorun), geri yükleme testi (son test başarısız ya da 8 günden eskiyse; ilk hafta
  beklenir), disk doluluğu (%85), 15 dakikalık yük ortalaması / çekirdek ≥ 1, Celery kuyruğu > 100 iş.
  Eşikler `.env`'de. Yedek kontrolleri yalnızca üretimde açık (`OPS_BACKUP_CHECK_ENABLED`).
- Sorun başlayınca admin rolüne `ops.alert` bildirimi (kural `ops_alert`), sorun sürerken saatte bir tekrar
  (`OPS_ALERT_REPEAT_MINUTES`), düzelince bir kez `ops.recovered`. Durum `ops.CheckState` tablosunda.
- Sistem > Sistem durumu ekranı (`GET /api/v1/ops/status/`, admin): kontroller, diskler, yük, kuyruk, son
  20 yedek/test çalışması.
- Dış izleme aracı (ör. Uptime Kuma) için `GET /api/v1/ops/health/` (kimlik doğrulamasız, ayrıntısız):
  veritabanı, Redis, yedek, geri yükleme testi, arka plan servisleri; biri `error` ise 503. Celery
  durursa uyarıyı Celery gönderemeyeceği için bu uç dışarıdan izlenmelidir. `GET /api/v1/health/` docker
  sağlık kontrolü için olduğu gibi kalır.
- Hata takibi: `SENTRY_DSN` tanımlıysa Sentry (ya da Sentry uyumlu GlitchTip); çerez, IP, istek gövdesi
  gönderilmez. Arayüzdeki beklenmeyen hatalar `POST /api/v1/ops/client-errors/` ile sunucu günlüğüne
  (ve Sentry'ye) yazılır, kullanıcı başına dakikada 30 kayıt.

### Yedek durum dosyası (yedek servisi → backend sözleşmesi)

Yedek servisi her çalışmadan sonra `/backups/status/latest-backup.json` ya da `latest-restore-test.json`
yazar (ve `history.jsonl`'e ekler); backend ve worker klasörü salt okur, `ops.run_checks` içe aktarır
(`BackupRun`, aynı çalışma iki kez eklenmez):

```json
{"kind": "backup | restore_test", "run_id": "20261017T020000", "source_run_id": "20261017T020000",
 "started_at": "2026-10-17T02:00:00+03:00", "finished_at": "2026-10-17T02:01:12+03:00",
 "status": "ok | failed", "message": "Türkçe açıklama", "database_bytes": 0, "media_bytes": 0,
 "media_files": 0, "tables": 0, "rows": 0, "offsite": "ok | failed | disabled", "offsite_message": "",
 "mismatches": [{"table": "inventory_lot", "expected": 10, "actual": 9}]}
```

### Üretim kurulumu ve yedek servisi

- Üretim: `scripts/prod-compose.sh` (`docker-compose.yml` + `docker-compose.prod.yml`, `.env.prod`).
  nginx derlenmiş arayüzü ve statik dosyaları verir, 443'te TLS 1.2/1.3 sonlandırır, 80'i yönlendirir;
  `/admin/`, `/api/docs/`, `/api/schema/` yalnızca `INTERNAL_NETWORKS` (iç ağ/VPN) IP'lerine açık.
  `migrate` servisi her açılışta migrate, collectstatic, seed_roles çalıştırır. Backend imajı geliştirme
  paketleri olmadan, root olmayan kullanıcıyla çalışır. db ve Redis'in portu dışarı açılmaz, Redis şifreli.
- Sertifika üç yoldan biriyle (KURULUM.md §4): firma alan adı + Let's Encrypt DNS-01, satın alınmış sertifika
  ya da iç sertifika otoritesi (`scripts/gen-selfsigned-cert.sh`; CA tabletlere bir kez yüklenir).
- `backup` servisi: her gece 02:00 tutarlı anlık görüntüden `pg_dump` (tablo sayımları aynı işlemde) +
  ekler arşivi + manifest (sha256), 30 gün saklama; her pazar 04:00 son yedeği geçici veritabanına kurup
  tablo sayılarını manifestle karşılaştıran geri yükleme testi. Saatler `BACKUP_CRON`, `RESTORE_TEST_CRON`.
- **Ayrı konum kopyası başarısızsa yedek başarısız sayılır** (`status: failed`, `offsite: failed`; mesaj
  yerel kopyanın sağlam olduğunu söyler) ve admin'e uyarı gider. Gerekçe: D-20 ayrı konumda kopyayı şart
  koşuyor; sessizce yalnızca yerelde kalan yedek fark edilmez.
- Harici disk/NAS klasöründe `.deterjan-erp-offsite` işaret dosyası bulunmalı; yoksa kopya yapılmaz ve
  hata verilir. Gerekçe: takılı olmayan USB diskte kopyanın sessizce sunucunun kendi diskine yazılmasını
  önlemek. Disk değiştirildikten sonra `backup` servisi yeniden başlatılır.
- Gerçek geri yükleme `scripts/restore.sh <çalışma|latest>`: önce güvenlik amaçlı yedek alır, servisleri
  durdurur, veritabanını ve ekleri geri yükler, servisleri başlatır; "EVET" onayı ister.
- CI: `prod` işi üretim imajlarıyla HTTPS üzerinden duman testi, yedek ve geri yükleme testini çalıştırır;
  `security` işi gitleaks (tüm geçmiş), pip-audit ve `npm audit --omit=dev --audit-level=high`.
- API dokümantasyonu katı CSP altında çalışsın diye `SpectacularSwaggerSplitView` (satır içi betik yok).

### KVKK

- Envanter `docs/KVKK.md`. Şoför TC kimlik numarası yalnızca irsaliyede açıktır; irsaliye PDF'inin ve
  irsaliye verisinin her açılışı denetim günlüğüne yazılır (`sales.services.record_waybill_access`).
- Her gece 03:30 `core.purge_expired_personal_data`: giriş/çıkış/başarısız giriş kayıtlarındaki IP
  adresleri 1 yıl sonra boşaltılır (`AUDIT_IP_RETENTION_DAYS`; denetim kaydının değiştirilemezliğinin
  bilinçli tek istisnası, kaydın kendisi kalır), süresi dolan oturumlar ve bitmiş giriş sayaçları silinir.

## 2026-10-16 — Geçiş ve eğitim (Faz 5, Adım 5.6)

Plan thread'de CUMHUR'un onayıyla ("Onayla"). Kararlar:

- **İçe aktarmalar**: ana veri içe aktarmasına depo, lokasyon, ekipman ve birim dönüşümü eklendi
  (`masterdata.importers`, rol planlama). Dönüşümün anahtarı malzeme + birimdir (kodu yok); diğerleri
  koda göre günceller ya da açar. Sıra: depo → lokasyon → ekipman (tankın lokasyonu önce açılmış olmalı).
  **Reçete içe aktarma** (`recipes.importers`, rol planlama ve laboratuvar): her satır bir bileşen, aynı
  reçete kodlu satırlar tek sürüm; reçete yoksa açılır, her reçeteye yeni **taslak** sürüm açılır (onaylı
  sürüm üretmez; onayı laboratuvar verir). Taslak sürümü olan reçete dosyada varsa satır reddedilir
  (tekrar yükleme çift sürüm açmasın diye). Proses adımları elle girilir. Doğrulama servis fonksiyonlarıyla
  geri alınan bir işlemde yapılır; önizleme ile aktarma aynı kuralları uygular. **Açık sipariş aktarımı
  yok**; canlıya geçişte elle girilir. Kategoriler az olduğu için elle girilir.
- **Canlı başlangıç tarihi** (`inventory.InventorySettings.go_live_date`): yönetim ve admin girer
  (`PUT /api/v1/golive/go-live/`). O günden itibaren (Türkiye saatiyle) `post_opening_balance` ve açılış
  stoku içe aktarma `opening_closed` ile reddedilir; farklar sayım düzeltmesiyle girilir. Tarih kaldırılır ya
  da ileri alınırsa yükleme yeniden açılır (denetim kaydıyla).
- **Hazırlık kontrol listesi** (`golive.selectors.readiness`, yönetim/planlama/depo): her rolde kullanıcı,
  malzeme türleri, tedarikçi, müşteri, depo, lokasyon türleri (depolama, karantina, üretim, sevkiyat),
  tank ve dolum hattı (eksikse kırmızı), terazi ve yazıcı (eksikse sarı), yarı mamullerin onaylı reçetesi,
  mamullerin onaylı ambalaj reçetesi, kontrol edilen malzemelerin onaylı spesifikasyonu (sarı), açılış
  stoku ve canlı tarihi.
- **Paralel çalışma stok karşılaştırması** (`golive.StockComparison`, `SK-`; depo ve yönetim açar,
  planlama da görür): Excel stok listesi (malzeme kodu, miktar; isteğe bağlı lot no, lokasyon kodu, birim)
  seçilen günün **sonundaki** sistem stoğuyla karşılaştırılır; geçmiş gün stoğu hareket defterinden
  hesaplanır, ileri tarih reddedilir. Düzey dosyadan çıkar: lot no tüm satırlarda doluysa lot, lokasyon tüm
  satırlarda doluysa lokasyon bazında, karışıksa bir alt düzeye (malzeme toplamı) iner. Aynı anahtar
  birden çok satırdaysa toplanır; miktar temel birime çevrilir. Varsayılan olarak sistemde stoğu olup
  dosyada olmayan malzemeler de "Excel'de yok" farkı olarak listelenir; "yalnızca dosyadaki malzemeler"
  seçilebilir. Fark = sistem − Excel. Kayıt ve satırları değişmez; her hafta yeni karşılaştırma açılır;
  Excel çıktısı farklı satırları önce ve kırmızı verir. Önerilen bitiş: iki hafta üst üste açıklanmamış fark
  kalmazsa yönetim Excel'i bırakır (kılavuzda öneri; sistem zorlamaz).
- **Sorun bildir** (`golive.ProblemReport`, `SB-`): üst çubukta her ekranda; açıklama zorunlu, sayfa
  adresi, başlık, tarayıcı ve ekran boyutu kendiliğinden eklenir. Ekran görüntüsü tarayıcıda alınır
  (html2canvas-pro; pencere açılmadan önce, kullanıcı çıkarabilir), JPEG/PNG/WEBP, en çok 8 MB. Görüntü
  genel ek tablosunda değil kayıtta tutulur ve yalnızca bildirene ve admin'e verilir (ekranda maliyet
  gibi kısıtlı bilgi olabilir). Liste kişiye kendi bildirimlerini, admin'e hepsini döner. Olay
  `problem_report.created` → iş akışı kuralı `problem_reported` admin rolüne görev açar; admin kayıt
  sayfasında yorumla yanıtlar ve görevi tamamlar.
- **Kılavuzlar**: rol bazında Markdown kılavuzlar `frontend/src/modules/help/guides/`, ekran görüntüleri
  `frontend/public/kilavuz/` (demo verisinden `scripts/kilavuz-ekran-goruntuleri.mjs` üretir). Uygulamada
  **Yardım** menüsü (herkese açık) kullanıcının rol kılavuzunu önce açar; sayım günü planı "Canlıya geçiş ve
  sayım günü" kılavuzudur.
- **Menü**: "Canlıya geçiş" yönetim, planlama ve depoya (admin her yerde); "Sorun bildirimleri" sekmesi
  yalnızca admin'e.

### Geçiş olay sözleşmesi (iş akışı tablosuna ek)

| Olay | Payload |
|---|---|
| `problem_report.created` | `model: "golive.problemreport"`, `id`, `number`, `summary` (ilk 120 karakter), `reporter`, `page_url`, `page_title` |

İş akışı kuralı: `problem_reported` (admin rolüne "Sorun bildirimi: SB-…" görevi; admin tamamlayınca kapanır).

## 2026-10-16 — Kullanıcılara açılış: bulutta eğitim ortamı

- **Karar (CUMHUR, "Bulutta eğitim"):** fabrika sunucusu (D-20) hazır olana kadar kullanıcılar bir bulut
  sunucusunda **yalnızca demo veriyle** sistemi dener. Gerçek veri ve canlı kullanım fabrika sunucusunda
  başlar; eğitim kayıtları taşınmaz. Kişisel veri olmadığından sunucu konumu KVKK açısından serbesttir.
- **Plan onayı (CUMHUR, "Onayla"):** `TRAINING_MODE=true` canlı ayarlarla (`config.settings.prod`) çalışır,
  demo kullanıcı ve demo veri komutlarına izin verir (`apps.core.demo.require_demo_allowed`), arayüz her
  ekranda "EĞİTİM ORTAMI" şeridi gösterir (`GET /api/v1/site/`, giriş gerektirmez). Demo şifresi zorunlu,
  en az 10 karakter, örnek şifre olamaz. Ortak demo hesapları yüzünden eğitim ortamında 2FA kapalı
  (`OTP_REQUIRED_ROLES=`). Kurulum `scripts/egitim-kur.sh` (adres `<ip>.sslip.io`, Let's Encrypt),
  ayrıntı `docs/EGITIM-ORTAMI.md`.

## 2026-10-21 — D-21 "Turhost bulut, gerçek kullanım" (D-20'nin yerine)

- **Karar (CUMHUR, 2026-10-21 14:30, "Gerçek kullanım"):** sistem gerçek veriyle, firmanın Turhost'tan
  aldığı bulut sunucusunda (Türkiye) çalışır. D-20 "Yerel sunucu" bu kararla değişti. Veri Türkiye'de
  kaldığından KVKK yurt dışı aktarım koşulu doğmaz; aydınlatma metni ve VERBİS kaydı sunucu yeriyle
  güncellenir (`docs/KVKK.md`).
- **Sonuçları:** etiket yazıcıları ve terazi fabrika ağında olduğundan sunucunun onlara ulaşması için
  fabrika ile sunucu arasında VPN gerekir (KURULUM.md §13); o kurulana kadar etiketler PDF olarak
  basılır. RAID/UPS sağlayıcının sorumluluğundadır; dış yedek kopyası sunucudan ayrı bir yerde
  (fabrikada NAS/PC ya da Türkiye'de bir depolama) yine zorunludur.
- **Plan onayı (CUMHUR, "Onayla"):** `scripts/bulut-kur.sh` (varsayılan `KIP=canli`) tek komutla kurar:
  Docker, ufw (22/80/443), Let's Encrypt, otomatik güvenlik güncellemeleri, demo veri yok, admin ve
  yönetim için 2FA zorunlu, ilk yönetici hesabı (`create_first_admin`, kullanıcı adı `yonetici`).
  Adres firma alan adı (`ADRES=erp.firma.com.tr`) ya da `<ip>.sslip.io`. Eğitim kipi (`KIP=egitim`,
  `scripts/egitim-kur.sh`) aynı betiği kullanır; bir kipte kurulan sunucu öbür kipe çevrilmez.

## 2026-10-23 — Kullanıcı yönetimi uygulamada (Sistem > Kullanıcılar)

Bulut sunucusunda (D-21) yönetim paneli (`/admin/`) yalnızca sunucunun kendisinden ve VPN'den açılır
(`INTERNAL_NETWORKS`); VPN henüz kurulmadığı için yönetici kullanıcı açamıyordu. Kullanıcı yönetimi
uygulamaya taşındı (CUMHUR onayı, 2026-10-23: yönetici ekranı, sistem üretimi ilk şifre, ilk girişte
değiştirme zorunlu, yalnızca admin):

- **Yalnızca admin** (`HasRole(ADMIN)`): yeni kullanıcı (`POST /api/v1/users/`), bilgi ve rol güncelleme
  (`PATCH`), `deactivate` / `activate`, `reset-password`; mevcut kilit açma ve 2FA sıfırlama. `PUT` ve
  silme yoktur (kural 6: kullanıcı pasife alınır).
- **İlk şifreyi sistem üretir** (`core.services.generate_temporary_password`): okunaklı dörtlü gruplar
  (`Kp7m-x3Rt-9wQa`), birbirine karışan karakterler (0/O, 1/l/I) yok, şifre politikasına uyar (grup sayısı
  `PASSWORD_MIN_LENGTH`'e göre artar). Yalnızca oluşturma ve sıfırlama yanıtında bir kez döner
  (`{"user", "temporary_password"}`, `Cache-Control: no-store`); saklanmaz, denetim günlüğüne yazılmaz.
- **İlk girişte şifre değiştirme zorunlu**: `User.must_change_password` (göç `core.0004`). İşaretli
  kullanıcı `/api/v1/auth/*`, sağlık ve istemci hatası uçları dışında `403 {"code":
  "password_change_required"}` alır (`core.middleware`; 2FA kapısından önce gelir) ve yönetim paneline
  giremez. `me` yanıtına `password_change_required` eklendi; SPA Güvenlik sayfasına götürür, şifre
  belirlenince (2FA gerekmiyorsa) Görevlerim'e döner. Yeni şifre mevcut şifreyle aynı olamaz
  (`same_password`, her şifre değişikliğinde); değişince işaret kalkar.
- **Kullanıcı adı**: küçük harf, rakam, `.`, `_`, `-`, en az 2 karakter; Türkçe karakter yok (tablette kolay
  yazılır, girişte büyük/küçük harf karışmaz); büyük/küçük harf farkıyla bile tekil (`username_taken`);
  sonradan değiştirilemez (denetim kayıtlarında ve @bahsetmelerde geçer). Ekran ad soyaddan öneri üretir.
  Ad soyad zorunlu; telefon ve e-posta isteğe bağlı. Rolsüz kullanıcı açılabilir (ekran uyarır).
- **Kilitlenmeye karşı**: admin kendini pasife alamaz (`cannot_deactivate_self`), kendi `admin` rolünü
  kaldıramaz (`cannot_remove_own_admin`), kendi şifresini bu ekrandan sıfırlayamaz (`use_security_page`);
  başka aktif yönetici (superuser ya da `admin` rolü) kalmayacaksa yönetici pasife alınamaz ve `admin` rolü
  kaldırılamaz (`last_admin`). Pasif kullanıcının şifresi sıfırlanmaz (`user_inactive`).
- **Oturumlar**: pasife alınan kullanıcının oturumu bir sonraki istekte düşer (kimlik doğrulama arka ucu
  pasif kullanıcıyı tanımaz). Şifre sıfırlamada şifre özeti değiştiği için açık oturumlar kapanır; hatalı
  deneme kilidi de açılır.
- Denetim: oluşturma (`create`, not "Kullanıcı açıldı"), roller, bilgi değişiklikleri, pasife alma /
  etkinleştirme ve "Şifre sıfırlandı" (`custom`) yazılır; şifre yalnızca `***` olarak görünür.

## 2026-10-24 — Yönetim panosu, yönetimin açılış ekranı

- **Karar (CUMHUR, "Yönetici panosu" → taslağa "Evet, uygula" → "Yönetimin açılış ekranı"):** yönetim
  panosu onaylanan taslağa göre yeniden düzenlendi ve yönetim rolünün açılış ekranı oldu.
- **Açılış:** `/` artık bir yönlendirmedir: açıkça yönetim rolü atanmış kullanıcı `/pano`'ya, diğer herkes
  (admin dahil) `/gorevlerim`'e gider; giriş sonrası, logo ve "ana sayfaya dön" bağlantıları da buna
  uyar. Görevlerim'in adresi `/`'den `/gorevlerim`'e taşındı. Menüde "Yönetim panosu" yönetimin ilk
  öğesidir (admin de görür). Planlama aynı panoyu Panolar ve raporlar'da görmeye devam eder; `/pano`
  adresi yönetime özeldir.
- **Pano sırası:** onayınızı bekleyenler (şartlı kabul, limit üstü satın alma siparişi ve TL toplamı,
  açık İSG olayı; TL toplamı yalnızca yönetim ve admin'e döner, D-15), dikkat gerektirenler (önce
  kritik, sonra uyarı; her satır ilgili listeye götürür), bugün, son 14 gün üretim (dökme birim bazında
  ya da mamul adedi; birimler karışmaz, tablo eşi var), stok değeri (türe göre), fire ve duruş, birimlerin
  iş yükü, açık emirler, kritik stok ve SKT listeleri.
- **Eşik (varsayılan, değiştirilebilir):** QC'de 24 saatten uzun bekleyen numune "Uyarı" satırı olur.
  Yalnızca görüntü eşiğidir, bir işlemi engellemez (`QC_WAIT_WARNING_HOURS`, `Dashboards.tsx`).
- **Performans:** yönetim panosunun sorgu tavanı 30'dan 36'ya çıktı; yeni bölümler sabit sayıda sorgu
  ekler, satır sayısıyla artmaz (`test_dashboards_open_fast_on_demo_data`).

## 2026-10-24 — Arayüz DentMesher tasarım dilinde

- **Karar (CUMHUR, "Sistemin kullanıcı arayüzünü DentMesher gibi yapalım"; seçimler "Üst çubuk + sol
  menü", "Gündüz + gece düğmesi", "Role göre", "DentMesher girişi gibi"; plan onayı "Plan uygun;
  başla"):** Inncos ERP'nin arayüzü DentMesher'ın (Desktop\DENTMESHER) tasarım dilini izler. Kaynak:
  DentMesher `static/css/main.css` (renkler, kart, düğme), `admin.css` (üst çubuk), `panel.css` (rol
  renkleri), `templates/auth/login.html` (giriş ekranının gece paleti).
- **Görünüm:** Inter (gövde) ve Manrope ExtraBold (INNCOS söz-işareti) uygulamayla paketlenir; canlıdaki
  CSP dış yazı tipine izin vermez. Vurgu mavisi #3b7eff, kayrak gri yazı ve çizgiler, 10/16 px köşeler,
  hap biçimli ve büyük harfe çevrilmeyen rozetler. Tablet için düğme boyutları değişmedi.
- **Üst çubuk:** rol rengiyle degrade (yönetim altın, planlama mavi, depo turuncu, üretim çivit,
  laboratuvar yeşil, dolum camgöbeği, sevkiyat mor, satın alma pembe, sistem yöneticisi lacivert). Çok
  rollü kullanıcıda öncelik: admin, yönetim, planlama, laboratuvar, üretim, dolum, depo, sevkiyat, satın
  alma. Çubukta panel adı, arama, sorun bildir, bildirim, tema ve profil; sol menü iki temada koyu
  lacivert.
- **Gündüz / gece:** gündüz varsayılan; gece DentMesher'ın kahve zemini ve turuncu ışıması, sayfa
  kutuları yarı saydam. Seçim tarayıcıda saklanır; `public/tema.js` açılışta uygular (CSP satır içi
  betiğe izin vermediği için ayrı dosya).
- **Arama (`/ara?q=`):** lot, mal kabul, üretim emri, şarj, dolum emri ve partisi, satış siparişi,
  sevkiyat, satın alma siparişi, numune ve müşteri iadesi; mevcut listelerin `search` süzgeci, kaynak
  başına 5 kayıt, yalnızca rolün açabildiği listeler. Backend değişmedi.
- **Giriş ekranı:** DentMesher girişi gibi koyu kahve zemin, cam kart, turuncu (#e8622c) giriş düğmesi;
  zeminde ana zincirin sözcükleri süzülür (hareketi azalt tercihinde durur). 22.10'daki mavi marka
  panelli giriş ekranının yerini aldı.

## 2026-10-24 — Açık yönlendirme denetimi (giriş dönüş adresi, sorun bildirimi sayfası)

- **Bulgu:** `npm audit --omit=dev`, react-router-dom 6.30.6 için orta düzey GHSA-wrjc-x8rr-h8h6 (ters
  bölüyle açık yönlendirme, CVE-2025-68470 atlatması) bildiriyor; yamalı sürüm yalnızca 7.x (kırıcı).
  Yerelde `/login?next=` ile ters bölü, çift ters bölü, karışık ve sekme varyantları denendi; yüklü sürüm
  hepsini uygulama içinde tuttu, sömürülemedi.
- **Karar (CUMHUR öneri kartını başlattı; iş bu oturumda yapıldı):** 7.x'e geçilmez, savunma kodda.
  Ortak `auth/safePath.ts` yalnızca bu sitenin yolunu kabul eder (`/` ile başlar, `//` ile başlamaz, ters
  bölü ve kontrol karakteri yok, aynı origin'e çözülür). Giriş sonrası dönüş adresi ve sorun
  bildirimindeki sayfa bağlantısı bundan geçer; geçmeyen adres ana sayfaya düşer ya da düz yazı kalır.
- **Backend:** sorun bildiriminin `page_url` alanı yalnızca uygulama içi yol kabul eder (400
  `validation_error`). Önceden her adres kaydedilip admin ekranında bağlantı olarak gösteriliyordu.
- **Sona erdi (2026-11-04):** react-router 7.18.5'e geçildi; `safePath.ts` denetimi kalır ve
  sıkılaştı. Bkz. "2026-11-04 — react-router 7'ye geçiş".

## 2026-10-25 — İki aşamalı doğrulama canlıda geçici olarak zorunlu değil

- **Karar (CUMHUR, "sisteme girişi şimdilik tek adımlı doğrulama yapalım sonrasında iki adımlı
  doğrulamaya geçeriz"; mevcut kurulum için "Onu da kaldır"):** canlıda giriş şimdilik yalnızca
  şifreyle. Önceki kararın (admin ve yönetim rollerinde 2FA zorunlu, D-21 kurulumu) yerine geçici.
- **Uygulama (kod değişmedi):** canlı `.env.prod` içinde `OTP_REQUIRED_ROLES=` (boş); servisler yeniden
  başlatıldı. `yonetici` hesabındaki doğrulayıcı ve kurtarma kodları sunucu kabuğundan
  `security.reset_otp` ile silindi (denetim günlüğünde "İki aşamalı doğrulama sıfırlandı"). Öncesinde
  `.env.prod.yedek-20261025-093733` ve veritabanı yedeği `20261025T093733` alındı.
- **Etkisi:** kimse 2FA kurmaya zorlanmaz; isteyen kullanıcı Güvenlik sayfasından kendisi açabilir
  (açan her girişte kod girer). Yönetim paneli girişi de şifreyle.
- **Geri dönüş (iki adıma geçildiğinde):** `.env.prod` içinde `OTP_REQUIRED_ROLES=admin,yonetim`, ardından
  `scripts/prod-compose.sh up -d --wait`. Bu rollerdeki kullanıcılar bir sonraki girişte kurulumu yapar
  (Güvenlik sayfası); kontrol listesi madde 22 ve 25 o zaman yeniden işaretlenir.
- **Sona erdi (2026-11-04):** 2FA yeniden zorunlu; bkz. "2026-11-04 — İki aşamalı doğrulama canlıda
  yeniden zorunlu".

## 2026-10-25 — Giriş ekranı PET ERP'deki gibi

- **Karar (CUMHUR, "giriş kısmını pet erp uygulamasında yaptığımız giriş arayüzü gibi olmasını
  istiyorum"; fotoğraflar için "PET'tekiler, preformsuz"):** giriş ekranı PET ERP'nin (PET şişe üretimi
  projesi) giriş arayüzüne geçer. 24.10'daki DentMesher girişinin (koyu kahve zemin, süzülen zincir
  sözcükleri) yerini alır; uygulamanın geri kalanı DentMesher dilinde kalır.
- **Görünüm:** tam ekran ürün fotoğrafları 7 sn'de bir kendiliğinden değişir (yazarken geçiş son tuştan
  4 sn sonraya ertelenir). Kart, düğme ve alt bant rengi her fotoğraftan tarayıcıda çıkarılan palete
  uyar: açık fotoğrafta açık, koyuda koyu kart; yazı ve düğme karşıtlığı en az 4,5:1. Sol üstte INNCOS
  ERP; altta cam bant, duraklat/sürdür düğmesi ve fotoğraf noktaları (WCAG 2.2.2). Hareketi azalt
  tercihinde geçiş duraklatılmış başlar.
- **Fotoğraflar:** PET'teki ürün fotoğraflarından 6'sı (`frontend/public/giris/*.webp`); preform
  fotoğrafları deterjan fabrikasına uymadığı için alınmadı. Fotoğraf değiştirmek için klasöre webp
  koyup `LoginPage.tsx`'teki `SLIDES` listesini güncellemek yeter.
- **Beni hatırla:** yalnızca kullanıcı adı o tarayıcıda saklanır (`localStorage`,
  `inncosKullaniciAdi`) ve sonraki girişte kutuya yazılır. Şifre saklanmaz; oturum süresi ve
  hareketsizlikte kapanma değişmez. Ortak tablette işaretlenmemesi kılavuzda yazıyor.
- **Korunanlar:** iki aşamalı doğrulama adımı (2FA'sı açık kullanıcıda), Caps Lock uyarısı, oturum
  kapandı notu, girişten sonra güvenli dönüş adresi (`safeAppPath`), geçici şifreyle girişte Güvenlik
  sayfası. Backend ve CSP değişmedi (satır içi betik yok; fotoğraf analizi tarayıcıda, dış istek yok).

## 2026-10-25 — Uygulama logosu: Inncos logosu

- **Karar (CUMHUR, "uygulamanın logosu bu olacak"; yerler için "Ekranlar ve simgeler", renk için
  "Zemine göre", dosya için "Yok, resimden çizin"):** gönderilen INNCOS logosu (yuvarlak köşeli
  çerçeve içinde "inn" işareti, altında INNCOS yazısı, lacivert #02225c) uygulamanın logosu olur.
- **Yerler:** giriş ekranının sol üstü (işaret, INNCOS yazısı ve "ERP"), üst çubuk (işaret ve INNCOS
  yazısı, yazının altında panel adı; telefonda yalnız işaret), tarayıcı sekmesi simgesi ve tablette ana
  ekran simgesi. Basılı belgeler (analiz sertifikası, irsaliye, satın alma siparişi) ve Django yönetim
  paneli bu kararın dışında; başlıkları olduğu gibi kalır.
- **Renk:** renkli üst çubukta ve koyu zeminde beyaz, açık zeminde logonun laciverti. Giriş ekranında
  fotoğrafın zeminine hangisi daha okunaklıysa o (ikisinden biri her zeminde en az ~4:1). Sekme ve ana
  ekran simgesinde beyaz zemin üstünde lacivert; koyu sekme çubuğunda da görünür.
- **Çizim:** vektör dosyası olmadığı için logo resmi (1254 px) izlenerek SVG'ye çevrildi; yeniden
  çizilen logo orijinalle piksel bazında %99,6 örtüşüyor. Kaynak `components/brand/InncosLogo.tsx`
  (işaret ve yazı ayrı parçalar, renk `currentColor`). Asıl vektör dosyası gelirse yalnızca bu bileşen
  ve `public/` altındaki simgeler değişir.
- **Temizlik:** yalnızca eski INNCOS yazısı için yüklenen Manrope yazı tipi kaldırıldı.

## 2026-10-25 — Personel kartları (yeni `personnel` modülü)

- **Karar (CUMHUR, "personel kayıtları için bir alan ekleyelim"; kapsam için "Kimlik ve görev", kişiler
  için "Evet, herkes", yetki için "Admin ve yönetim"):** sistemi kullanmayanlar dahil bütün çalışanlar için
  personel kartı tutulur. Eğitim/belge takibi, vardiya ve izin bu kararın dışında.
- **Kart:** ad soyad ve birim zorunlu; sicil no isteğe bağlı, doluysa benzersiz; görev, işe giriş ve çıkış
  tarihi, telefon, acil durumda aranacak kişi ve telefonu. Sistem hesabı olanın kartı kullanıcısına
  bağlanır (bir kullanıcı tek karta; pasif kullanıcı bağlanmaz).
- **Birim:** ayrı ana veri değil, serbest metin; kayıtlı birimler önerilir ve büyük/küçük harf farkı
  (Türkçe i/ı dahil) var olan yazıma çevrilir.
- **Ayrılış:** kart silinmez. "İşten ayrıldı" çıkış tarihiyle kartı pasife alır, "Yeniden işe başladı"
  geri açar (çıkış tarihi silinir, denetim günlüğünde kalır). Bağlı sistem hesabı kendiliğinden kapanmaz;
  kartta uyarı çıkar, hesabı sistem yöneticisi pasife alır. (Güncelleme 2026-10-30: ayrılışta çıkıştan
  sonraki puantaj günleri kaldırılır; bkz. "Puantajda çıkıştan sonraki günler".)
- **Yetki ve gizlilik:** ekran ve API yalnızca admin ve yönetim (diğer roller 403); kartın değişiklik
  geçmişi kendi uç noktasında. `workflow`'un genel geçmiş ve yorum uç noktaları `personnel.employee`
  kaydını kabul etmez; aksi halde her kullanıcı değişiklik geçmişinden kişisel veriyi okuyabilirdi. KVKK
  envanterine iki satır eklendi.
- **Modül:** `apps/personnel` (yalnızca core ve masterdata'ya bağlı); CLAUDE.md modül tablosuna eklendi.

## 2026-10-25 — Kayda bağlı yorum, geçmiş ve eklerde erişim denetimi

- **Bulgu:** kayda bağlı yorum, değişiklik geçmişi ve dosya eki uç noktaları kayıt türünü parametre
  olarak alıyor ve yalnızca girişi denetliyordu. Kaydın kendi ekranında göremeyen kullanıcı (ör.
  başkasının bildirdiği İSG olayı, yalnızca yönetimin gördüğü maliyet) bu uç noktalardan kaydın
  geçmişine, yorumlarına ve eklerine ulaşabiliyordu. Lot maliyeti ve satın alma tutarı, kaydı gören ama
  tutarı göremeyen rollere geçmişte görünüyordu.
- **Karar (CUMHUR, "Kayıt geçmişi ve yorumlardaki erişim düzeltmesini bu oturumda yap"; plan için "Plan
  uygun; başla"):** bu uç noktalar kaydın kendi ekranındaki okuma kuralına uyar.
- **Kural:** `core.records` kayıt defteri. Modüller `AppConfig.ready()` içinde yorum, geçmiş ya da ek
  açılan türlerini kendi okuma kuralıyla kaydeder: roller, kayıt bazlı süzgeç (olay: bildiren ve
  yönetim; sorun bildirimi: bildiren ve admin), geçmişte gizli alanlar. Kayıtlı olmayan tür kabul
  edilmez. Kaydı göremeyene kayıt yokmuş gibi yanıt verilir (`record_not_found`, tek kayıtta 404).
- **Alan gizleme:** lot maliyeti (`unit_cost`, `cost_is_estimated`) yalnızca yönetime (Karar D-15),
  satın alma siparişi tutarları satın alma ve yönetime (sipariş ekranıyla aynı). Yalnızca gizli
  alanları değiştiren geçmiş satırı notuyla birlikte gösterilmez.
- **@bahsetme:** kaydı göremeyen kişi önerilmez; adı yazılırsa bahsedilmiş sayılmaz, bildirim gitmez.
- **Tek kural:** olay ve sorun bildirimi görünürlüğü tek fonksiyonda
  (`hse.services.incidents_visible_to`, `golive.selectors.problem_reports_visible_to`); ekran ve
  kayda bağlı uç noktalar aynı fonksiyonu kullanır.

## 2026-10-25 — Firma ticari bilgileri uygulamada (Ana veriler > Firma bilgileri)

- **Karar (CUMHUR, "şirketin ticari bilgilerini gireceğimiz alan yapalım"; alanlar için "Kimlik ve
  vergi", yetki için "Admin ve yönetim", belgeler için "İrsaliye ve sipariş"):** firmanın ticari
  bilgileri sunucudaki ayar dosyasından (`COMPANY_*`) uygulamadaki tek kayıtlık **Firma bilgileri**
  formuna taşınır.
- **Alanlar:** ticari unvan (zorunlu), adres, vergi dairesi, vergi no, ticaret sicil no, MERSİS no.
  Vergi no 10 haneli VKN ya da şahıs firmasında 11 haneli TCKN; ikisi de kontrol haneleriyle
  denetlenir. MERSİS no 16 hane. Boşluklu yazım kabul edilir, boşluklar atılır. İletişim ve banka
  bilgileri bu kararın dışında.
- **Yetki:** yönetim ve admin değiştirir; okuma giriş yapmış herkese açık, çünkü bilgiler belgelerde
  zaten görünür. Ekran Ana veriler'de (planlama yalnızca okur). Her değişiklik denetim günlüğüne
  yazılır.
- **Kullanıldığı yer:** sevk irsaliyesinde satıcı, satın alma siparişinde alıcı bloğu (sicil ve MERSİS
  satırı dahil); tedarikçiye giden sipariş e-postasının imzası. Analiz sertifikası ve etiketler bu
  kararın dışında: sertifika `COMPANY_NAME` ayarını, etiket Etiket ayarları'ndaki adı kullanmaya devam
  eder.
- **Geçiş:** kayıt ilk açılışta `COMPANY_*` değerleriyle oluşur. Canlıda bu değerler boştu; ilk girişte
  formdan doldurulur.

## 2026-10-29 — Personel özlük bilgileri ve belgeleri

- **Karar (CUMHUR, "Personel listesine personelin doğum tarihi, TC kimlik no, doğum yeri, mezuniyet
  bilgileri, kimlik fotokopisi, bordro, sözleşmeler alanı ekleyelim"; TC kimlik no için "Her zaman
  açık", mezuniyet için "En son mezuniyet", belgeler için "Admin ve yönetim"):** personel kartına
  kimlik ve mezuniyet bilgileri ile özlük belgeleri eklenir. Bilgiler listede sütun değil, kartta durur.
- **Kimlik:** TC kimlik no isteğe bağlı; doluysa 11 hane ve kontrol haneleri tutmalı, iki kartta aynı
  olamaz. Hata mesajında numara tekrarlanmaz. Kartta açık görünür; denetim günlüğüne ve kart geçmişine
  maskeli yazılır (`*******0146`). Doğum tarihi bugünden ileri ya da 1900'den önce olamaz.
- **Mezuniyet:** yalnızca en son mezuniyet tutulur: öğrenim durumu (ilkokul … doktora), okul, bölüm,
  mezuniyet yılı (1940 – bu yıl). Diploma belge olarak eklenir.
- **Belgeler:** kimlik fotokopisi, bordro (dönem: ay ve yıl, zorunlu), sözleşme (başlangıç zorunlu;
  belirsiz süreli sözleşmede bitiş boş), diploma. PDF, JPG ya da PNG; en çok 20 MB. Ayrılan personele de
  belge eklenebilir (son bordro). Belge silinmez: nedeniyle kaldırılır, artık açılamaz.
- **Gizlilik:** belgeler ayrı modelde (`EmployeeDocument`) tutulur ve yalnızca personel uç noktalarından
  admin ve yönetime verilir; genel ek uç noktaları personel kartını kabul etmez. Dosya adı rastgeledir,
  yanıt tarayıcı önbelleğine alınmaz. Ekleme, kaldırma ve her açılış kartın geçmişine yazılır; bu yüzden
  listede küçük resim gösterilmez (her gösterim bir açılış sayılırdı).
- **Açık konular:** belgelerin ve ayrılan personelin özlük bilgilerinin saklama süresi ile eski tip nüfus
  cüzdanındaki din hanesi (özel nitelikli veri) firma İK ve hukuk birimiyle netleşecek (docs/KVKK.md).

## 2026-10-29 — Personel puantajı

- **Karar (CUMHUR, "Uygulamaya personel puantaj sistemi ekleyelim"; kapsam için "Durum ve fazla
  mesai", yetki için "Admin ve yönetim", ay kapama için "Onayla kilitlensin", tatiller için
  "Takvimden otomatik"; plan için "Plan uygun; başla"):** personel bölümüne aylık puantaj ve tatil
  takvimi eklenir (`apps/personnel`; yeni modül açılmadı).
- **Günlük durumlar:** Ç çalıştı, HT hafta tatili, RT resmi tatil, Yİ yıllık izin, Mİ mazeret izni
  (ücretli), Üİ ücretsiz izin, R raporlu, D devamsız. Fazla mesai saat olarak (0–24) yalnızca Ç, HT
  ve RT günlerine girilir; tatilde çalışan kişinin günü HT/RT kalır, çalıştığı saat fazla mesaidir.
  Devamsızlık ve fazla mesai ileri bir güne girilemez; izin ve rapor önceden girilebilir.
  (Güncelleme 2026-11-12: Ç gününe çalışılan saat ve yarım gün (YG) işareti girilebilir; bunlar da
  ileri bir güne girilemez, saati eksik güne fazla mesai girilmez; bkz. "Puantajda günlük çalışma
  saati ve yarım gün".)
- **Varsayılan günler:** ay takvimden dolu açılır: tam gün resmi tatil RT (hafta tatiline denk gelse
  de), varsayılan hafta tatili günü HT (başlangıçta pazar; ayardan değişir), diğer günler (yarım gün
  tatil dahil) Ç. Kişinin işe girişinden önceki ve çıkışından sonraki günler boştur (2026-10-30:
  çıkıştan sonra kayıtlı kalmış günler ayrılışta kaldırılır; bkz. "Puantajda çıkıştan sonraki
  günler"). Açık ayda
  yalnızca değiştirilen günler saklanır; takvim ya da ayar değişirse diğer günler yeniden hesaplanır.
  (Güncelleme 2026-11-12: saat girilmeyen çalışılan gün günlük çalışma saatiyle sayılır; bkz.
  "Puantajda günlük çalışma saati ve yarım gün".)
- **Aralık girişi:** kişi, birim ya da herkes. Yıllık izin, mazeret izni ve devamsızlık HT ve RT
  günlerine yazılmaz (İş Kanunu m.56); rapor ve ücretsiz izin her takvim gününe yazılır.
  (Güncelleme 2026-11-12: aralık girişi saat taşımaz; başka duruma geçen günün saati ve yarım gün
  işareti silinir.)
- **Onay:** ay bitmeden onaylanamaz. Onayda değiştirilmemiş günler varsayılan durumlarıyla yazılır
  (toplu, ayın denetim kaydında sayısıyla) ve ay kilitlenir; gün, aralık ve o aya düşen tatil
  değişmez. Yeniden açma gerekçeyle yapılır; günler onaydaki haliyle kalır. Ay `PU-` numaralı belge,
  durum makinesi Açık ⇄ Onaylandı; geçişler olay yayınlar (`attendance_month.approved`/`.open`).
  (Güncelleme 2026-11-12: ay ilk onayında günlük çalışma saatini alır ve yeniden açılınca korur;
  bkz. "Puantajda günlük çalışma saati ve yarım gün".)
- **Toplamlar:** durum başına gün, eksik gün (Üİ + R + D), fazla mesai iş günü / hafta tatili /
  resmi tatil ayrı. Ücret ve bordro hesaplanmaz; Excel bordroyu hazırlayana verilir. (Güncelleme
  2026-10-29: ücretten personel maliyeti maliyet modülünde hesaplanır, bordro yine hesaplanmaz; bkz.
  "Personel maliyeti".) (Güncelleme 2026-11-12: Ç tam gün çalışılan günleri sayar, yarım gün (YG)
  ayrı sütundadır, eksik gün değişmedi; çalışılan saat toplamı Excel'dedir.)
- **Tatil takvimi:** sabit tatiller (2429 sayılı Kanun) düğmeyle eklenir; Ramazan ve Kurban Bayramı
  günleri her yıl elle girilir, arifeler yarım gün. Tatil silinmez, takvimden kaldırılır.
- **Kapsam dışı:** giriş-çıkış saatleri, vardiya planı, yıllık izin hakkı ve bakiyesi, ücret hesabı,
  birim sorumlusu girişi, yıllık 270 saat fazla mesai sınırı uyarısı. (Güncelleme 2026-11-12: günlük
  çalışma saati toplam saat olarak kapsama girdi; giriş-çıkış saati ve vardiya planı kapsam dışı
  kaldı; bkz. "Puantajda günlük çalışma saati ve yarım gün".)
- **CLAUDE.md:** modül tablosunda `personnel` satırı "özlük bilgileri ve belgeleri, puantaj" ile
  güncellendi (planla onaylandı).

## 2026-10-29 — Personel maliyeti

- **Karar (CUMHUR, "Personel maliyetlerini hesaplayalım. Maliyet alanına ekleyelim."; temel için
  "Brüt ücret + puantaj", kullanım için "Rapor + işçilik önerisi", rapor günleri için "Ücretten
  düşülsün", işveren payı için "%17,75 teşvikli"; plan için "Plan uygun; başla"):** personel maliyeti
  maliyet modülünde (`apps/costing`) hesaplanır; yeni modül açılmadı. `costing`, `personnel`'i okur
  (kartlar ve puantaj tablosu); `personnel` maliyeti bilmez.
- **Ücret:** kişi başına brüt aylık ücret, geçerlilik tarihli (`EmployeeWage`). Zam yeni tarihle
  eklenir; kayıt değiştirilmez ve silinmez, yanlışsa gerekçeyle kaldırılır. Aynı kişi ve tarihte tek
  ücret (kaldırılan hariç). Yazım hatasına karşı başlangıç 2000–2100 arası, tutar en çok
  100.000.000 TL. Ücretler sekmesi çalışanları (çıkışı ileride olanlar dahil) listeler; "Ayrılanları
  da göster" ile raporda görünen eski personelin ücreti de girilir ve düzeltilir. Yeni ücretin
  varsayılan başlangıcı: ilk ücrette işe giriş tarihi (yoksa geçen ayın 1'i), zamda bu ayın 1'i.
  (2026-11-01: ücretler kurallarıyla birlikte Personel > Ücretler'e taşındı; bkz. "Personel
  bordrosu".)
- **Aylık hesap (30 gün usulü):** puantajın günleri kullanılır (açık ayda takvim varsayılanları, onaylı
  ayda kayıtlı günler); yalnızca işe giriş ve çıkış tarihi arasındaki günler sayılır (çıkıştan sonra
  kayıtlı kalmış puantaj günü de sayılmaz). Her gün o gün geçerli ücretle hesaplanır (ay içinde zam).
  Ayın tamamında işte olan 30 gün alır (ay 28, 30 ya da 31 gün olsa da); ay içinde giren ya da
  ayrılan işte olduğu takvim günü kadar alır (brüt / 30 × gün). Ücretsiz izin, devamsızlık ve rapor
  günleri brüt / 30 ile düşülür; yıllık izin ve mazeret izni ücretlidir. Uç durumlar (inceleme
  sonrası, 2026-10-29): hiç ücretli günü olmayan ay ücretsizdir (Şubat'ta 30 − 28 = 2 gün kalmaz);
  30 gün usulü sıfıra düşerken ücretli günü olan (31 çeken ayda 30 gün ücretsiz) ücretli takvim günü
  kadar alır. Ücreti girilmemiş günler sıfır sayılır ve kişi "ücret eksik" diye işaretlenir. Kişi
  tutarı tek bölmeyle bulunur, yarım kuruş yukarı yuvarlanır. (Güncelleme 2026-11-13: puantajda
  yarım gün çalışılan (YG) her gün için günlük ücretin yarısı (brüt / 60) da düşülür; "Brüt ücret"
  bu kesinti düşülmüş haldedir; bkz. "Bordroda yarım gün kesintisi (2. adım)".)
- **Fazla mesai:** saat ücreti brüt / 225. İş günü ve hafta tatilinde 1,5 kat; resmi tatilde çalışılan
  saate ayrıca 1 kat (günün ücreti zaten aylığın içinde). (2026-11-02: resmi tatilde bir günlük ilave
  ücret, 7,5 saati aşan saatler 1,5 kat; bkz. "Personel bordrosu".)
- **İşveren payı:** (brüt ücret + fazla mesai) × oran; varsayılan %17,75 (teşvikli SGK işveren primi ve
  işsizlik sigortası işveren payı), ayardan değişir. Tek ayardır; rapor saklanmadığı için değişince
  geçmiş ayların raporu da yeni oranla hesaplanır, eklenmiş işçilik oranları değişmez. Bordro değildir:
  gelir ve damga vergisi, SGK tavanı, kıdem ve izin karşılığı hesaplanmaz. (2026-11-02: tek oran
  kalktı; kişi maliyeti ön bordro hesabından gelir: SGK matrahının alt ve üst sınırı, 2026 oranları,
  teşvik ve alt sınır farkıyla. Bkz. "Personel bordrosu".)
- **Aşamalar:** personel birimi maliyet aşamasına eşlenir: Üretim (bulk), Dolum (mamul) ya da genel
  gider (eşleştirilmemiş birim). Birim adında Türkçe büyük/küçük harf farkı gözetilmez; bir birim için
  tek eşleştirme kaydı vardır.
- **Rapor saklanmaz:** her açılışta hesaplanır. Geçmiş aylar da (onaylılar dahil) bugünkü ücret
  kayıtları, kişinin bugünkü birimi ile işe giriş ve çıkış tarihi, bugünkü eşleştirme ve bugünkü
  işveren payıyla hesaplanır; ay içinde birim değiştirenin bütün ayı yeni birime yazılır. Kartta tek
  bir çalışma dönemi tutulduğu için yeniden işe alımda işe giriş tarihi ileri alınırsa önceki dönem
  geçmiş aylardan düşer. Ayrılışta çıkıştan sonraki puantaj günleri kaldırıldığı için (2026-10-30,
  "Puantajda çıkıştan sonraki günler") "Yeniden işe başladı" bunları geri getirmez; maliyet yine de
  yalnızca işe giriş ve çıkış arasındaki günleri sayar. Eklenmiş işçilik oranları ve hesaplanmış lot
  maliyetleri değişmez.
  Onay anındaki dağılımı ve çalışma dönemlerini saklamak ayrı bir tasarım konusudur. (2026-11-03:
  bordrosu onaylı ayda (Ekim 2026'dan) kişi satırları ve birimleri onayda saklanır, yeniden
  hesaplanmaz; o ayın satırını değiştiren ücret ve işe giriş tarihi değişikliği bordro yeniden
  açılmadan reddedilir (`payroll_approved`). Aşama eşleştirmesi bugünkü kalır, çalışma dönemleri
  saklanmaz. Bkz. "Personel bordrosu", 4. adım.)
- **İşçilik oranı önerisi:** aşamanın personel maliyeti / o ay üretilen kg (4 ondalık). Kg, lot
  maliyetindeki işçilik tabanıyla aynıdır: üretimde ay içinde biten şarjların kg'a çevrilmiş çıktısı,
  dolumda ay içinde biten partilerde tüketilen bulk (fire hariç); yoğunluğu girilmemiş malzemenin
  üretimi sayılmaz, kaç malzeme olduğu ekranda gösterilir. Öneri yalnızca puantajı onaylı ay için yeni
  işçilik oranı (`CostRate`, tür İşçilik) olarak eklenir; başlangıç tarihi seçilir (varsayılan ertesi
  ayın ilk günü), aynı aşama, tür ve tarihte oran varsa reddedilir. Aşamada ücreti eksik kişi ya da
  kg'a çevrilemeyen malzeme varsa pencere uyarır, oran yine eklenebilir. Lot maliyetinde şarjın ya da
  partinin bittiği gün geçerli oran kullanılır: oran, başlangıç tarihinde ya da sonra biten lotlara
  uygulanır; bunlardan maliyeti önceden hesaplanmış olanlar "Yeniden hesapla" ile güncellenir, daha
  önce biten lotlar eski oranla kalır. Eski oranlar ve hesaplanmış lot maliyetleri kendiliğinden
  değişmez.
- **Yetki:** yalnızca yönetim ve admin (maliyet modülünün kuralı, D-15). Ücretler kişisel veridir
  (docs/KVKK.md).
- **Kapsam dışı:** bordro ve net ücret, prim ve ikramiye, yol ve yemek yardımı, kıdem tazminatı
  karşılığı, bütçe ve plan maliyeti, işveren payının tarihli değişimi, onaylı ayın dağılımının
  saklanması (kısmen 4. adımda: bordrosu onaylı ayın kişi satırları ve birimleri saklanır). (Puantajda çıkış tarihinden sonra kayıtlı kalan günler 2026-10-30'da personel modülünde
  düzeltildi; bkz. "Puantajda çıkıştan sonraki günler". 2026-11-02: prim, ikramiye, nakit yol ve
  yemek bordroda ek ödeme olarak girilir ve SGK işveren payıyla personel maliyetine ve işçilik oranı
  önerisine girer; bkz. "Personel bordrosu", 3. adım.)
- **CLAUDE.md:** modül tablosunda `costing` satırı ve bağımlılık notu güncellendi (planla onaylandı).

## 2026-10-30 — Puantajda çıkıştan sonraki günler

- **Karar (CUMHUR, 2026-10-30; açık aylar için "Onayla kaldırılsın", onaylı ay için "Önce ay yeniden
  açılsın"; plan için "Plan uygun; başla"):** puantajda kişinin çıkış tarihinden sonra kayıtlı günü
  kalmaz. Önceden ayrılış bu günlere dokunmuyordu: ileri tarihe girilmiş izin ya da ayrılıştan önce
  onaylanmış ayın günleri tabloda görünüyor, toplamlara ve Excel'e giriyor ve düzenlenemiyordu
  ("Personel puantajı" kararındaki "çıkışından sonraki günler boştur" kuralına aykırı). Maliyet bu
  günleri zaten saymıyordu.
- **Çıkış tarihi** kişinin son iş günüdür ve kendisi dahildir (`employed_on`); pencerede "Son çalışma
  günü (o gün dahil)" yazar.
- **Açık aylar:** ayrılış kaydedilirken çıkıştan sonraki kayıtlı günler listelenir
  (`attendance_after_exit`; ay ay, durumu, fazla mesaisi ve not işareti aynı ardışık günler aralık
  olarak, ör. "Eylül 2026: 21–23.09 Üİ, 24.09 Ç (2,5 sa FM, notlu); Ekim 2026: 05–06.10 Yİ").
  (Güncelleme 2026-11-12: özet çalışılan saati ve yarım günü de yazar, ör. "24.09 YG (4,5 sa)".)
  "Kaydet ve günleri kaldır" (`remove_attendance`) ayrılışı kaydeder ve günleri aynı işlemde kaldırır.
  Onay o tarih içindir; tarih değişince ya da onaylı kayıt bir iş kuralıyla reddedilince düşer ve
  günler yeniden sorulur. İstek sürerken tarih ve not değiştirilemez. İleri tarihli çıkışta (ihbar
  süresi) da aynı kural geçerlidir.
- **Onaylı aylar:** günlerden biri onaylı bir aydaysa ayrılış kaydedilmez
  (`approved_attendance_after_exit`); mesaj ayları ve günleri listeler, yanıt onaylı ayları da verir
  (`months`, ör. "2026-09") ve pencere ilkine bağlantı verir. Bordroya giden rakam değişeceği için
  mesajda adı geçen her ay önce gerekçeyle yeniden açılır, ayrılış kaydedilir, aylar yeniden onaylanır
  ve yeni Excel bordroya verilir. Onaylı ay sessizce değişmez. Ay onayı penceresi "Bu ay işten ayrılan
  varsa önce çıkışını kaydedin" diye hatırlatır.
- **Silme ve iz (CLAUDE.md §4.6, §4.7):** kaldırılan gün silinir. Çıkıştan sonraki günler çalışma
  dönemi dışındadır (`employed_on`); kayıt kalmayınca tabloda boş görünür. Güne başka kayıt bağlı
  değildir, maliyet bir şey saklamaz. Yeniden açılmış ayda kaldırılan günler onayla yazılmış
  varsayılan günleri de kapsar (önceki Excel'le bordroya gitmişlerdi). Bu, taslak reçete satırındaki
  (2026-10-15) "kullanılmamış veri" yorumundan geniştir; CUMHUR'a ayrıca soruldu ve onayladı (açık ay
  için "Onayla kaldırılsın", onaylı ay için "Önce ay yeniden açılsın"). Her gün silinmeden önce bütün
  alanlarıyla ayın denetim kaydına yazılır (`entry`: [eski, null]; `id` günün kendi kayıtlarına
  bağlar); ayrılışın notuna (kartın geçmişi) tarihli özet eklenir. Silme uç noktası yoktur; silme
  yalnızca ayrılış servisinin içinde olur.
- **Düzeltme ve yeniden işe başlama:** çıkış tarihi "Yeniden işe başladı" ve doğru tarihle "İşten
  ayrıldı" ile düzeltilir. Kaldırılan günler geri gelmez; gerekirse kartın geçmişindeki özetten
  (tarih, durum, fazla mesai) yeniden girilir; notun metni ve bütün alanlar ayın denetim kaydındadır.
  Doğru tarih daha ileriyse ve arada onaylanmış ay varsa, o ayda iki tarih arasındaki günler boş kalır
  (onay yalnızca eski çıkışa kadar yazmıştı; ayrılış bunu yakalamaz): ay gerekçeyle yeniden açılıp
  yeniden onaylanır (eksik günler yazılır) ve yeni Excel bordroya verilir.
- **Eşzamanlılık:** kilit sırası kart → ay → gün. Gün ve aralık girişi ile ay onayı önce kartları
  kilitler ve güncel çıkış tarihini okur; aynı anda kaydedilen ayrılış çıkıştan sonraya gün bırakamaz.
  Kilitten sonra tabloya yeni bir kart girerse (ör. o sırada yeniden işe başlatılan) onay geri alınır
  (`attendance_cards_changed`, "ayı yeniden onaylayın").
- **Mevcut veri:** canlıda (6 kart, ayrılan yok, tek açık ay) ve yerelde çıkıştan sonra kayıtlı gün
  yoktu; göç ya da temizlik betiği gerekmedi.
- **Kapsam dışı:** işe giriş tarihinden önce kayıtlı günler (yeniden işe alımda önceki dönem ya da
  ileri alınan giriş tarihi) bugünkü gibi kalır; ileri tarihli çıkışta kart yine hemen "Ayrıldı"
  görünür; ayrı çalışma dönemleri ayrı bir tasarım konusudur.

## 2026-11-01 — Personel bordrosu (ön bordro)

- **Karar (CUMHUR, 2026-11-01, "Personel modülüne maaş puantaj bilgilerine göre personelin işverene
  maliyetini gösteren tablo yapalım. bordroyu yapalım ve çıktı alabilelim"; bordro türü için "Ön
  bordro", başlangıç için "Ekim 2026", ek kalemler için "Kesinti (BES, avans, icra)", "Ek ödeme
  (prim, yol, yemek)" ve "Özel durumlu çalışan", resmî tatil için "Günlük ücret"; plan için "Plan
  uygun; başla"):** personel modülünde aylık bordro (brütten nete) ve işverene maliyet tablosu
  yapılır; çıktılar PDF (işveren maliyeti tablosu, bordro listesi, ücret hesap pusulaları) ve Excel.
  İş dört adımda yapılır (docs/PROGRESS.md).
- **Ön bordro:** SGK (e-Bildirge, APHB) ve vergi (MUHSGK) bildirimini mali müşavir yapmaya devam
  eder; ERP bordrosu ilk aylarda mali müşavirin bordrosuyla kalem kalem karşılaştırılır. Çıktılarda
  "Ön bordrodur; SGK ve vergi bildirimi yerine geçmez" notu ve maskeli TC kimlik no bulunur; SGK
  işyeri sicil no ve resmî bordro imza düzeni yoktur.
- **Ücretler personel modülünde (adım 1):** ücretler (`EmployeeWage`) maliyet modülünden personel
  modülüne taşındı; ekran Personel > Ücretler (eski Maliyet > Personel ücretleri adresi oraya
  yönlenir, "Ayrılanları da göster" süzgeciyle). Yalnızca Django'nun model durumu taşındı: tablo ve
  kısıt adları (`costing_employeewage`, `costing_wage_*`) değişmedi, kayıtlar ve kimlikleri yerinde
  kaldı; içerik türü personele aktarıldığı için ücretlerin denetim geçmişi korunur (geçişler
  costing/0003, personnel/0004; geri alınabilir). Personel modülü yine yalnızca `core` ve
  `masterdata`'ya bağlıdır; `costing` ücretleri (ve bordroyu) `personnel`'den okur. Birimlerin
  maliyet aşaması ve işveren payı Maliyet > Personel maliyeti sekmesinin altına geçti (2. adımda işveren
  payı ayarı kalktı; bordro parametrelerinden gelir). Ücret kuralları değişmedi ("Personel
  maliyeti").
- **Hesap (2026 değerleri, parametreli):** yasal değerler vergi yılına bağlı tarihli parametre
  setinde tutulur; bir yılın değerleri başka yıla uygulanmaz. 2026: asgari ücret brüt 33.030,00 TL
  (net 28.075,50); SGK matrahı alt sınırı günlük 1.101,00, üst sınırı günlük 9.909,00 (9 kat); işçi
  payı SGK %14 ve işsizlik %1; işveren payı SGK %21,75 eksi 5510 s. Kanun m.81/ı teşviki (imalat
  işyerinde 5 puan, 2026 sonuna kadar) ve işsizlik %2, toplam %18,75; gelir vergisi dilimleri
  190.000 / 400.000 / 1.500.000 / 5.300.000 TL (%15 / 20 / 27 / 35 / 40), yıl içinde kümülatif;
  asgari ücret gelir ve damga vergisi istisnası; damga vergisi binde 7,59. Değerler ekranda hazır
  gelir, mali müşavirle kontrol edilip kaydedilir; teşvik puanı işyerine göre seçilir.
- **SGK günü ve alt sınır:** tam ayda 30 gün; eksik gün varsa takvim günü eksi eksik gün; ay içinde
  giriş ya da çıkışta takvim günü. Ücret SGK matrahı alt sınırının altında kalırsa (ör. 31 çeken ayda
  ücretsiz izin) farkın primini işçi payı dahil işveren öder (5510 s. Kanun m.82); işçinin kesintisi
  ücretinden hesaplanır.
- **Resmî tatil ("Günlük ücret"):** tatilde çalışana bir günlük ilave ücret (brüt / 30) ödenir, kısa
  çalışsa da; 7,5 saati aşan saatler saat ücretinin 1,5 katı. Yarım gün tatilde (28 Ekim, arifeler)
  öğleden sonra çalışana yarım günlük ilave ödenir; puantaja bunun için işaret eklenir. Önceki kural
  (çalışılan saat × brüt / 225 × 1) bırakılır; personel maliyeti de aynı kuralı kullanır. Mali
  müşavirle ilk karşılaştırmada teyit edilir.
- **Rapor, ücretsiz izin, devamsızlık:** bugünkü gibi brüt / 30 ile düşülür ("Personel maliyeti",
  "Ücretten düşülsün"). (Güncelleme 2026-11-13: yarım gün çalışılan (YG) her gün için günlük ücretin
  yarısı (brüt / 60) düşülür, pusulada ayrı satırdır, SGK günü değişmez; bkz. "Bordroda yarım gün
  kesintisi (2. adım)".)
- **Ek ödeme ve kesinti:** her ay kişiye elle ek ödeme (brüt; prim, ikramiye, yol, yemek; SGK'ya ve
  vergiye tabi) ve net kesinti (avans, icra ya da nafaka, diğer) girilir; pusulada her biri ayrı
  satırdır (İş Kanunu m.37). BES otomatik katılımı kartta işaretlenir; kesinti her ay SGK matrahının
  %3'üdür. İstisnalı yemek ve yol kartı ilk sürümde yoktur.
- **Özel durumlu çalışan:** emekli (SGDP), engelli, kısmi süreli, net ücretle anlaşılmış ya da başka
  işyerinde de çalışan kişi kartta "Bordrosu mali müşavirde" diye işaretlenir ve ERP bordrosunda
  hesaplanmaz. İşveren maliyeti tablosu eksik kalmasın diye o ay için mali müşavir bordrosundaki brüt
  ve işveren maliyeti elle girilir. İşaretin nedeni yazılmaz (engellilik sağlık verisidir, KVKK m.6).
- **Başlangıç Ekim 2026:** Ocak–Eylül'de çalışan herkes için Eylül sonu kümülatif gelir vergisi
  matrahı mali müşavirin Eylül bordrosundan bir kez girilir (devir); asgari ücret istisnasının
  uygulandığı ay sayısı işe giriş tarihinden önerilir. Bordro dönemi hak ediş ayıdır (Ekim ücreti
  Kasım'da ödense de Ekim bordrosudur); ödeme tarihi onayda girilir.
- **Onay (Puantaj'daki gibi):** bordro her ay canlı hesaplanır (taslak). Puantaj onaylandıktan sonra
  onaylanır, BR- numarası alır ve satırlar o anki haliyle saklanır; çıktılar artık değişmez. Onaylıyken
  o ayın puantajı yeniden açılamaz, o aya etki eden ücret, parametre, devir, ek ödeme ve kesinti
  değiştirilemez. Düzeltme: bordro gerekçeyle yeniden açılır, düzeltilir ve yeniden onaylanır (eski
  onay saklanır). Aylar sırayla onaylanır, sondan başa açılır. Taslak çıktılar "TASLAK" damgalıdır;
  ücret hesap pusulası yalnızca onaylı bordrodan alınır.
- **Maliyet aynı hesaba geçer:** Maliyet > Personel maliyeti bordro hesabını kullanır (onaylı ayda
  saklanan satırlar, diğer aylarda aynı hesapla tahmin); tek %17,75 ayarı kalkar (2025 oranıydı;
  2026'da imalat işyerinde %18,75). SGK alt sınırı ve 2026 oranı yüzünden rakamlar artar; eklenmiş
  işçilik oranları ve hesaplanmış lot maliyetleri değişmez.
- **Yetki ve KVKK:** yalnızca yönetim ve admin. Çıktılar tarayıcı önbelleğine alınmaz, her açılış kayda
  geçer. Canlıda ücret ve bordro girilmeden önce yönetim ve admin için iki aşamalı doğrulamanın
  yeniden zorunlu yapılması önerildi (2026-10-25 kararı geçicidir).
- **Kapsam dışı:** SGK ve MUHSGK bildirgeleri, banka ödeme dosyası, kıdem ve ihbar tazminatı ile
  çıkış ayındaki kullanılmamış izin ücreti (çıkış ayında uyarı verilir), netten brüte hesap, 5 puan
  dışındaki teşvikler ve asgari ücret desteği, istisnalı yemek ve yol kartı, devamsızlık olan haftada
  hafta tatili ücretinin kesilmesi (İş Kanunu m.46), aynı kişinin yeniden işe alınması, SGK
  tavanını aşan prim ve ikramiyenin izleyen iki aya devri (5510 m.80; 2026-11-02 "3. adım
  kararları", uyarılır).
- **CLAUDE.md:** modül tablosunda `personnel` ve `costing` satırları ile bağımlılık notu güncellendi
  (planla onaylandı).
- **2. adım (2026-11-02): hesap, parametreler, işveren maliyeti.**
  - Hesap motoru (`personnel.payroll`) yalnızca Python standart kitaplığını kullanır (Django yok);
    yayımlanmış 2026 örnekleri (ÇSGB asgari ücret maliyeti, 50.000 TL'lik yıllık zincir, SGK tavanı,
    ay ortasında giriş, alt sınır farkı, Eylül devri, istisna dilimleri) testlerle sabitlendi. Her
    kalem ayrı yuvarlanır; işveren SGK'sı "SGK işveren − teşvik" iki yuvarlanmış kalemdir.
  - Parametre setleri (`PayrollParameterSet`): bir ayın ilk gününden geçerli, yalnızca kendi yılına
    uygulanır; aynı aydan iki geçerli set olamaz; oranlar 0–100, teşvik SGK işveren payını aşmaz, dilim
    sınırları artar. Silinmez, gerekçeyle kaldırılır. Kayıtlı set yoksa hesap o yılın yasal
    değerleriyle yapılır (ekranda "Parametreler kaydedilmedi"); yasal değeri sistemde olmayan yılda
    en yakın yılın değerleriyle tahmin gösterilir (kırmızı uyarı). Onay (4. adım) o yılın kayıtlı
    setini ister.
  - Yarım gün tatil çalışması puantajda gün başına işarettir (`holiday_half_worked`): yalnızca
    takvimde yarım gün tatil olan, bugün ya da geçmiş, çalışılan güne (Ç) girilir; aralık girişi
    çalışılmayan duruma geçen günün işaretini sıfırlar. Tatil sonradan kaldırılırsa işaret hesapta
    sayılmaz. Excel'de "Ç½". (2026-11-12: yarım gün çalışma (YG) ayrı bir işarettir ve aynı
    sayılma kuralına uyar; saati eksik güne Ç½ girilmez; bkz. "Puantajda günlük çalışma saati ve
    yarım gün".)
  - Ücreti girilmemiş günü olan kişide SGK alt sınırı uygulanmaz (ücretsiz görünen kişiye prim
    yazılmasın); satır "ücret eksik" uyarısı taşır.
  - Kart işaretleri: "Bordrosu mali müşavirde" (`payroll_external`) ve "BES'e dahil"
    (`bes_enrolled`); değişiklikleri kartın geçmişindedir. Mali müşavirde hesaplanan kişinin ay
    rakamları (`ExternalPayrollFigure`: brüt toplam, işverene maliyet ≥ brüt) yalnızca işaretli ve o
    ay işte olan kişiye girilir; tekrar girilince düzeltilir (denetim kaydıyla).
  - İşveren maliyeti tablosu: ekran (Personel > Bordro), PDF (A4 yatay; birim ara toplamları, genel
    toplam, parametre ve durum satırı, her sayfada ön bordro notu ve Sayfa x/y; onaya kadar çapraz
    "TASLAK" damgası) ve Excel ("İşveren maliyeti", "Parametreler"). Dosyalar tarayıcı önbelleğine
    alınmaz; her açılış denetim günlüğüne "Bordro çıktısı açıldı" diye yazılır (onaylı bordro
    kaydı 4. adımda gelene kadar kayda bağlı olmadan).
  - Maliyet > Personel maliyeti aynı hesaptan beslenir; tek işveren payı ayarı (uç, ekran) kalktı.
    `PersonnelCostSettings` modeli ve tablosu geçmiş kayıtlar silinmesin diye durur (CLAUDE.md §4.6),
    okunmaz.
  - İnceleme sonrası (2026-11-02): Excel de onaya kadar taslaktır (başlıkta, ilk not satırında ve
    Parametreler sayfasında "TASLAK"). Maliyet > Personel maliyeti Excel'i kişi başına ön bordro
    rakamı taşıdığı için bordro çıktıları gibi önbelleğe alınmaz ve açılışı kayda geçer; Excel'de
    "Ücret eksik" ile "Mali müşavir rakamı girilmedi" ayrıdır. "Asgari ücretin altında" uyarısı
    ücretli günlerde geçerli aylık ücretlere bakar (ay içinde zamda zamdan önceki ücrete de), ay
    içinde giriş ve çıkışta da verilir. Yarım gün tatil işareti tatil kaldırılınca ya da tam güne
    çevrilince tabloda da görünmez (saklı işaret durur, tatil geri gelince yeniden sayılır). Mali
    müşavir rakamları 0 / 0 olabilir (ayın tamamı raporlu ya da ücretsiz izinli kişi); notuna özel
    durumun nedeni yazılmaz. Yasal değeri bilinmeyen yılın parametre penceresi kırmızı uyarıyla
    açılır, düğme en yakın yılı söyler.
- **3. adım kararları (CUMHUR, 2026-11-02; tasarım eleştirisinin açtığı sorular, hepsinde önerilen
  seçenek):**
  - **Devir her ay girilebilir** ("Her ay devir girilebilsin"): ERP ile mali müşavirin kümülatif gelir
    vergisi matrahı ayrışırsa mali müşavirin kümülatifi o aya devir olarak girilir, ERP oradan sürer.
    Önceki ayların ERP hesabının yerine geçtiği için ayrıca onay ister ve kayda geçer. Gerekçe:
    paralel çalışılan aylarda her ay yalnızca o ayın farkı görünsün.
  - **Neti aşan kesinti** ("Uyarsın, onayı engellesin"): satırda uyarı; bordro bu haliyle onaylanmaz
    (4. adım). Kalan kendiliğinden devretmez, yönetici sonraki aya girer.
  - **SGK tavanını aşan prim ve ikramiye** ("Uyarsın, hesaplamasın"): tavanı aşan kısmın izleyen iki
    aya devri (5510 m.80) hesaplanmaz; satırda "mali müşavirle kontrol edin" uyarısı. Kapsam dışına
    eklendi.
  - **Nakit yemek parası** ("Parametreli istisna olsun"): yemek ek ödemesinin çalışılan gün × günlük
    sınıra kadarki kısmı SGK matrahına girmez, gelir vergisine tabi kalır. Günlük sınır bordro
    parametrelerindedir; mali müşavirden alınıp girilene kadar 0'dır (kaynaklar 2026 için 158 TL ve
    300 TL diyor; 2026-11-01 kararındaki "SGK'ya ve vergiye tabi" yemek için bu kadar değişti).
- **3. adım (2026-11-02): brütten nete bordro, devir, ek ödeme ve kesinti, bordro listesi.**
  - Brütten nete hesap Ekim 2026'dan başlar; önceki aylarda yalnızca işveren maliyeti hesaplanır,
    net alanları boştur. Kümülatif zincir 2026'da Ekim'den, sonraki yıllarda Ocak'tan başlar.
  - Zincir saklanmaz, her açılışta kurulur: kişinin o ay ya da önceki bir aydaki en son etkin
    devrinden (yoksa zincirin ilk ayından sıfırla) başlar, aradaki ERP aylarının gelir vergisi ve
    asgari ücret istisna matrahları eklenir. Mali müşavirde hesaplanan ay (o ay etkin mali müşavir
    rakamı olan) zinciri koparır; kişinin giriş ayı o aydan sonraki ilk aydır. **Devir eksik**:
    giriş ayından önce bu yıl bu işyerinde çalışmış, giriş ayında ya da sonrasında devri olmayan
    kişi (gelir vergisi kümülatifsiz, düşük hesaplanır). **Zincir eksik**: zincirdeki bir ayda ücret
    eksik ya da parametre tahmini.
  - Devir (`PayrollOpeningBalance`) Şubat–Aralık ayına girilir; Ocak'ta ve o aydan önce bu yıl bu
    işyerinde çalışmamış kişiye girilmez. İstisna ay sayısı işe girişten bu yana ay sayısını aşamaz
    (giriş ayı tam sayılır). İstisna matrahı kayıt anında, devir ayından önceki son N ayın kendi
    parametrelerindeki istisna matrahları toplanarak yazılır. Önceki ay ERP'de hesaplandıysa devir
    eşitlemedir ve onaysız kaydedilmez. Devir silinmez, gerekçeyle kaldırılır; zincir bir önceki
    devirden ya da ilk aydan yeniden kurulur. Devir penceresi toplu kaydeder: bir satır reddedilirse
    hiçbiri kaydedilmez, hatalar satırın altında yazar; değişmeyen devir yeniden gönderilmez.
  - Ek ödeme ve kesinti (`PayrollItem`): türü kategoriden gelir ve sonradan değişmez; "Diğer"de
    açıklama zorunludur; tutar sıfırdan büyük, en çok 100 milyon TL. Kalem birlikte ödendiği ücretin
    bordro (hak ediş) ayına girilir ve gelir vergisi o aya göre hesaplanır (mali müşavirle ilk
    karşılaştırmada teyit edilecek varsayım). Başlangıç ayından önceki ya da gelecek bir aya, o ay
    işte olmayan ya da bordrosu mali müşavirde olan kişiye girilmez. Kalem silinmez, gerekçeyle
    kaldırılır. Kartın geçmişine özet yazılır ("Ek ödeme eklendi: Ekim 2026 · Prim 5.000,00 TL"),
    açıklama yazılmaz (icra dosyası). Toplu ekleme ve geçen aydan kopyalama hepsi ya da hiçbiridir.
  - Kişinin işte olmadığı aya düşecek kalem ya da devir varsa işe giriş tarihi ileri alınamaz,
    ayrılış o aydan önceye kaydedilemez; önce kalem ya da devir gerekçeyle kaldırılır (kalem başka
    bir aya aitse o aya yeniden girilir; ay değiştirilemez). Devrin istisna ay sayısı yeni işe giriş
    tarihine göre fazla kalacaksa da işe giriş tarihi değiştirilemez; önce devir düzeltilir. Önceden girilmiş kalem
    kişi o ay işte değilse hesaba girmez; ekranda ve ay hazırlığında ayrıca listelenir, kalem
    toplamlarına katılmaz.
  - Değişmeyen devir ya da kalem yeniden kaydedilirse kayıt ve kart notu yazılmaz. Mali müşavir
    rakamı da gerekçeyle kaldırılabilir.
  - Uyarılar satırda ve bordro listesinde harfle: devir eksik (D), zincir eksik (Z), ücret eksik
    (Ü), kesinti netten fazla (N), tavanı aşan prim ya da ikramiye (P); alt sınır (A), tavan (T).
  - Bordro listesi PDF'i (A4 yatay, onaya kadar TASLAK): kişi başına günler, kazançlar, SGK, gelir
    vergisi (hesaplanan, istisna, kesilen), damga vergisi, kesintiler (kategori toplamıyla,
    açıklamasız), net, ödenecek ve işverene maliyet; birim ara toplamları ve genel toplam; TC kimlik
    no maskeli. Bordrosu mali müşavirde olanlar ayrı blokta, toplamlara katılmadan; son sayfada
    icmal.
  - Excel (net aylarda): "Bordro", "İşveren maliyeti", "Karşılaştırma" (mali müşavirin rakamları
    yapıştırılınca fark formülle hesaplanır, 0,01'den büyük fark kırmızı), "Eksik gün" (ücretsiz
    günlerin sayısı, tarihleri ve SGK neden kodu önerisi: 01 istirahat, 15 devamsızlık, 21 diğer
    ücretsiz izin, 12 birden fazla neden; bildirimdeki gün ve kodu mali müşavir belirler),
    "Parametreler" (nakit yemek günlük sınırı dahil). Başlangıçtan önceki aylarda "İşveren
    maliyeti", "Eksik gün" ve "Parametreler".
  - Maliyet > Personel maliyeti brütten nete hesabı kullanmaz (işveren maliyeti devirden
    bağımsızdır). Ek ödemeler SGK işveren payıyla toplam maliyete ve işçilik oranı önerisine girer;
    ayrı sütunda ve özette görünür. Kesintiler ve gelir vergisi maliyeti değiştirmez.
  - İnceleme sonrası (2026-11-02, ekranlar):
    - Devir penceresine Excel'den yapıştırma: yalnızca tutar ya da tutar ve istisna ay (0–11)
      satırları yapıştırılan kutudan aşağı ekrandaki sırayla dolar; aradaki boş hücre o kişiyi
      atlar (değerler kaymaz). Başka biçimli sekmeli satırlar (sicil no ve tutar, araya ad soyad)
      sicil no ile eşleşir, sıra önemsizdir: büyük-küçük harf ve i / İ farkı, yalnızca rakamlı sicil
      no'da baştaki sıfırlar önemsenmez; eşleşmeyen sicil no'lar ve tutarı bulunamayan satırlar
      listelenir, hiçbir sicil eşleşmezse hiçbir kutu dolmaz, başlık satırı atlanır. Tutarın
      sağındaki hücre tam sayıysa istisna ay sayısıdır. Sicil no ile eşleşmede tutar sütunu satır
      satır değil bir kez seçilir (sicil no'dan sonra 0–11 dışında sayı taşıyan tek sütun): boş tutar
      hücresi o kişiyi atlar ve listelenir, yanındaki ay hücresi tutar sayılmaz; birden çok sayı
      sütunu varsa (TC kimlik no, gün) hiçbir kutu dolmaz. Aynı sicil no farklı değerle birden çok
      satırda geçerse o kişi doldurulmaz, listelenir. Okunamayan tutar (ör. "290.000 X", "#YOK",
      "yok") kutuya yazılır ve tek "Kaydet"i durdurur; tutarın başında ya da sonunda TL / ₺ olabilir.
      "Yalnızca girilmeyenler" gönderilecek, okunamayan ya da reddedilen satırı ve süzgeç açıkken
      düzenlenen satırı gizlemez.
    - Pencerede kaldırılan devrin değerleri taslakta kalmaz; pencerenin ayı açılırken sabitlenir.
      Sunucu bir satır için eşitleme onayı isterse onay kutusu o satır için de çıkar. Satır kişinin
      bu yılki bütün devirlerini taşır: önceki ayın penceresi o ayın devrini (sonraki ayda devri olsa
      da) girilmiş gösterir.
    - Ay hazırlığında devri eksik kişiler giriş ayına göre ayrı satırlardadır; her satır kendi
      ayının devir penceresini açar. Kaydedildikten sonra parametreleri değişen devirler de ayına göre
      ayrı satırdadır ("Devri yeniden kaydet"); pencere onları listeler ve değiştirilmeden kaydeder.
    - Döküm: üstünde pencere açıkken Esc ve ok tuşları o pencereye aittir. "Yalnızca uyarılı
      kişiler" adreste tutulur (`?uyarili=1`) ve döküm aynı kişileri gezer. Ay değişince açık
      pencereler kapanır, o aya dönünce kendiliğinden açılmaz. O ay ya da sonra işe girene eşitleme
      devri önerilmez.
    - Bordrosu mali müşavirde olan kişiye girilmiş kalem ERP bordrosunda hesaplanmaz: kalemler
      görünümünde rozetle, kalem toplamlarının dışında ve ay hazırlığında ayrıca gösterilir. Gelecek
      ayda kalem ekleme düğmeleri kapalıdır. Geçen aydan kopyalamada bu ayda zaten olan kalemler
      (aynı kişi, kalem, tutar ve açıklama) işaretsiz gelir; iki liste de her açılışta yeniden
      okunur, okunana kadar seçim yapılamaz. Kalem düzeltilirken kişi değişmez.
      Nakit yemek ipucu parametrelerdeki günlük sınırı söyler; sınır 0 ise istisna uygulanmadığını
      uyarır.
  - İnceleme sonrası (2026-11-02, kurallar ve çıktılar):
    - ~~Mali müşavir rakamı, o aya ERP'de girilmiş etkin ek ödeme ya da kesinti varken ilk kez
      girilemez (`payroll_items_external`).~~ 4. adım incelemesinde kaldırıldı (2026-11-03,
      "Onaylansın, listede yazsın" kararının gereği): rakam ancak kişinin o ayı zaten mali
      müşavirdeyken girilir, kalemler de zaten hesaplanmaz; kural yalnızca onayı kilitliyordu.
      Kartı sonradan işaretlenen kişiye girilmiş kalemler bordro listesinde mali müşavir bloğunun
      notunda kalem toplamlarıyla (açıklamasız) yazılır. Kart işaretinin sonradan açılması için kural
      aşağıdaki 2026-11-03 kararıdır.
    - Gelecek aya devir girilmez (`future_month`): bir önceki ayın kümülatifi o ay bitince belli
      olur; kalemlerdeki kuralla aynı. Ekranda gelecek ayın devir düğmeleri kapalıdır, ay hazırlığı
      "ay gelince girilir" yazar.
    - Devrin istisna matrahı kayıtta saklı kalır; kapsadığı aylardan birinin parametreleri tahminse
      ya da devirden sonra değiştiyse satır "zincir eksik" (Z) uyarısı alır, döküm devrin yanında
      nedenini yazar ("parametre tahmini" / "parametreler değişti"). Parametreler devirden sonra
      değiştiyse devir (değiştirilmeden de) yeniden kaydedilince istisna matrahı bugünkü
      parametrelerle yeniden yazılır, uyarı kalkar. Tahminde yeniden kaydetmek uyarıyı kaldırmaz:
      önce o yılın parametre seti kaydedilir; değerler tahminle aynıysa uyarı kendiliğinden kalkar,
      farklıysa devir "parametreler değişti" olur ve yeniden kaydedilir.
    - İşe giriş tarihi değişirken kart önce kilitlenir (bordro kayıtlarının kilit sırası): aynı anda
      girilen kalem ya da devir işe giriş denetimini atlatamaz.
    - Bordro listesinde kişi başına "Ödenecek / işverene maliyet" alt alta yazılır (birim ve genel
      toplamlarda da); tablo A4 yatay sayfanın çerçevesine sığar.
    - Kalem açıklaması ve kaldırma nedeni denetim günlüğünde eski → yeni değerleriyle kalır; kaldırma
      nedeni kartın geçmişine de yazılır. Pencereler buna göre uyarır (dosya numarası ya da kişi adı
      yazılmaz).
    - **Karar (CUMHUR, 2026-11-03, "Onaylılar korunsun"):** kartta "Bordrosu mali müşavirde"
      işareti sonradan açılınca onaylı aylar saklı satırlarıyla korunur, işaretten etkilenmez (4.
      adım). Onaysız aylar işarete uyar (yeniden açılan ayda son onayda bulunan kişiler "Kartı
      izle"ye kadar onaydaki işaretlerle kalır; bkz. 4. adım kararları); işaret açılırken kişinin
      onaysız aylardaki ek ödeme, kesinti ve devirleri kartın geçmişine (açıklamasız) yazılır ve
      ekranda uyarılır (yeniden açılan ayda ERP'de kalan kayıt bunu yazar). Diğer
      seçenekler ("İşaretin başlangıç ayı olsun", "Kalem varken açılamasın") seçilmedi.
- **4. adım kararları (CUMHUR, 2026-11-03; tasarım eleştirisinin açtığı sorular, hepsinde önerilen
  seçenek):**
  - **Ücret hesap pusulası iç belgedir** ("İç belge"): başlığı "Ücret hesap pusulası (ön bordro,
    bilgi amaçlı)", imza satırı yoktur. Resmî pusula mali müşavirinkidir; paralel aylarda iki farklı
    imzalı belge oluşmaz.
  - **Onayı engelleyen uyarılar** ("İkisi engellesin"): devir eksik, zincir eksik, ücret eksik, mali
    müşavir rakamı girilmedi ve kesinti netten fazlaya ek olarak "asgari ücretin altında" ve "SGK
    günü olmadan ödeme" de onayı engeller. "Ay içinde çıkış" ve "tavanı aşan prim" onay penceresinde
    kişi adlarıyla listelenir, "okudum" işaretiyle onaylanır.
  - **Mali müşavirdeki kişinin ERP kalemleri** ("Onaylansın, listede yazsın"): onayı engellemez;
    bordro listesinin mali müşavir bölümünde kalem toplamlarıyla (açıklamasız) yazılır, onay
    penceresinde uyarı olarak gösterilir.
  - **Yeniden açılan ay onaydaki durumu korur** ("Onaydaki durum korunsun"): önceki onayda bulunan
    kişiler o onaydaki "Bordrosu mali müşavirde" ve "BES'e dahil" işaretleriyle hesaplanır. Kartı
    değişen kişiler pencerede listelenir; bir kişiyi kartın bugünkü durumuna geçirmek ayrıca seçilir
    ve kayda geçer. Önceki onayda olmayan kişiler kartı izler.
  - **Ödeme tarihi gerekçeyle düzeltilir** ("Gerekçeyle düzeltilsin"): onaylı bordroda yalnızca
    ödeme tarihi gerekçeyle değiştirilebilir; tutarlar değişmez, ay kilitli kalır, eski → yeni
    denetim günlüğüne yazılır.
  - **İşçilik oranı onaylı bordrodan** ("Onaylı bordro gereksin"): Ekim 2026 ve sonrasında Maliyet >
    Personel maliyeti'nden işçilik oranı yalnızca bordrosu onaylı aydan eklenir; oranın notuna BR
    numarası yazılır. Ekim öncesinde bugünkü gibi onaylı puantaj yeter. Rapor ve Excel ayın onaylı
    ya da tahmin olduğunu gösterir.
- **4. adım (2026-11-03): bordro onayı, ay kilitleri, ücret hesap pusulası.**
  - Kayıtlar (göç 0007): `PayrollRun` (BR-, numara bordronun yılından: Aralık bordrosu Ocak'ta
    onaylansa da BR-<Aralık'ın yılı>), `PayrollApproval` (onay anındaki parametreler, firma
    bilgisi, puantaj numarası, motor sürümü, ödeme tarihi, toplamlar ve okunan uyarılar; yeniden
    açılınca kim, ne zaman, neden yazılır ve saklanır) ve `PayrollSlip` (kişi bilgisi, TC kimlik no
    yalnızca maskeli; hesapta kullanılan "mali müşavirde" ve "BES" işaretleri; hesap satırı, ek
    ödeme ve kesintiler açıklamasıyla, mali müşavir rakamı, uyarılar, kümülatifin kuruluşu ve ay
    sonu kümülatifi). Satır değiştirilmez, silinmez; onaylı kayıt varken göç geri alınamaz.
  - Onay koşulları "4. adım kararları"ndakilerdir; ayrıca o ay işte olmayan kişiye girilmiş kalem ve
    bordroda hiç kişi olmaması engeller. Onay penceresi hesabın özetini gönderir: pencere açıldıktan
    sonra hesap değiştiyse onay reddedilir (`payroll_changed`), yenilenen hesap incelenir. Ödeme
    tarihi bordro ayının ilk gününden üç ay sonrasının son gününe kadardır; ay sonundan 20 günden
    sonrası ekranda uyarılır. Onay tüm ay için verilir (birim süzgeçli ekranda denetim yoktur).
  - Kilitler: kalem, devir ve mali müşavir rakamı; ücret (geçerli olacağı günler, bir sonraki
    ücrete kadar, kişinin ERP'de hesaplanan satırı olan onaylı bir aya düşerse); parametre seti
    (onaylı bir ayın geçerli değerleri değişecekse; not ve kaynak düzeltmesi serbest); puantajın
    yeniden açılması; işe giriş tarihi (onaylı satırı olan ayın işte olunan günlerini
    değiştirirse). Yeni kart ve yeniden işe başlatma onaylı ayı değiştirmez (onaylı puantaj yalnızca
    kayıtlı günlerdir). Ayrılışta onaylı puantaj günü varsa hata önce bordronun, sonra puantajın
    yeniden açılmasını söyler. Onay ayın kartlarını, puantaj ayını, bordro yılını (PostgreSQL
    danışma kilidi; parametre yazımı da alır) ve önceki ile bu bordro ayını kilitler; kart kilidiyle
    yazılan kayıtlar onayla sıraya girer.
  - Onaylı ay saklı satırlardan okunur: ekran, çıktılar ve personel maliyeti (kişinin adı ve
    birimi onaydaki; aşama eşleştirmesi bugünkü). Kalem, devir ve mali müşavir rakamı ay kilitli
    olduğu için kayıtlardan okunur (kimin girdiği görünür). Yeniden açılmış eski onayın çıktıları
    (`?approval=<sıra>`) saklanan kalem ve rakamlardan kurulur, "GEÇERSİZ" damgalıdır; Excel'in
    Eksik gün sayfası bugünkü puantajdandır ve bunu yazar.
  - Zincir: onaylı aylar yeniden hesaplanmaz; sonraki ayın kümülatifi kişinin yılın onaylı
    aylarındaki son satırının ay sonu kümülatifinden kurulur. Onaylı satırdan sonraki aya girilen
    devir onun yerine geçer (mali müşavirle eşitleme, onayla); mali müşavirdeki onaylı satır
    zinciri keser (sonraki ilk ERP ayı devir ister).
  - Yeniden açma yalnızca en son onaylı ayda; onay "geçersiz" olarak saklanır, yeniden onayda
    numara aynı kalır, onay sırası artar. Yeniden açılan ayda son onayda bulunan kişiler onaydaki
    işaretlerle hesaplanır (onayda da bu haliyle saklanır); "Kartı izle" kişiyi kartın bugünkü
    işaretlerine geçirir, bordro kaydına ve kartın geçmişine yazılır. Kalem, devir ve rakam
    girişleri de bu işaretlere uyar.
  - Çıktılar: onaylı ayda TASLAK yok; başlıkta BR numarası ve onay sırası, durum satırında onay
    zamanı, onaylayan ve ödeme tarihi; firma bilgisi onaydaki. Ücret hesap pusulası A4 dikey, kişi
    başına bir sayfa: firma, dönem, BR numarası, ödeme tarihi; kişi (maskeli TC); günler; kazançlar
    (saat ve gün ayrıntısıyla, ek ödemeler açıklamasıyla); SGK; gelir ve damga vergisi (hesaplanan,
    istisna, kesilen; kümülatif matrah); net; kesintiler (BES, açıklamasıyla); ödenecek; alt sınır
    ve tavanı aşan prim açıklaması; imza satırı yok. Bordrosu mali müşavirde olanlar son sayfada
    adlarıyla. Açılış bordro kaydının geçmişine (onay sırasıyla), tek kişinin pusulası kartın
    geçmişine de yazılır.
  - Personel maliyeti: rapor ve Excel bordronun onaylı mı tahmin mi olduğunu yazar; Ekim 2026'dan
    işçilik oranı onaylı bordrodan eklenir (`payroll_not_approved`), notunda BR numarası.
  - Kart: "Bordrosu mali müşavirde" açılınca onaylanmamış aylardaki ek ödeme, kesinti ve devirler
    (açıklamasız) kartın geçmişine yazılır, kayıt yanıtı ekrana uyarı olarak döner.
  - Demo verisi: geçen ay başlangıç ayı ya da sonrasıysa o yılın parametre seti (yasal değerler),
    zincirin ilk ayına devirler (ücretten tahmini) ve geçen aya üç kalem; bordro onaylanmaz, onaylı
    aya yazılmaz, tekrar çalıştırmak eklemez.
  - İnceleme sonrası (2026-11-03; yedi eksenli çok ajanlı inceleme, her bulgu ayrı ajanla
    çürütülmeye çalışıldı; 27 bulgu doğrulandı, 5'i çürütüldü):
    - Kartına göre işte olduğu bir ayda bordroda satırı olmayan kişide (kart onaydan sonra açıldı
      ya da işe giriş tarihi onaylı aya çekildi; onaylı puantajda günü yok) o ayın kümülatifi
      bilinmez: zincir kopar (döküm "Bordroda satırı yok"), sonraki ilk açık ay devir ister. Devirin
      giriş ayı hiçbir zaman onaylı (kilitli) bir ay olmaz.
    - Zincirde önceki açık ayın mali müşavirde sayılması o ayın kendi satırının kuralıyla aynıdır
      (yeniden açılan ayda onaydaki işaret, kartı izleyen kişide kartın işareti).
    - Mali müşavir rakamı ERP'de girilmiş kalem varken de girilir (yukarıdaki 2026-11-02 kuralı
      kalktı); onay kalemleri bilgi olarak listeler.
    - Bordro yazımları (kalem, devir, mali müşavir rakamı) bordro yılı kilidini paylaşımlı alır:
      onayın kilitlemediği (o ay günü olmayan) karta yazılan kayıt da onayla sıraya girer. Onaylı
      aya yazımda önce bordro kilidi söylenir (`payroll_approved`); ayrılışta önce onaylı puantaj
      denetlenir.
    - Onay penceresi: "okudum" denetiminin bütün kişileri listelenir; işaret kişiler değişince
      kalkar; yeniden açılan ayda kartı değişen kişiler pencerede de yazar; red yalnızca sorunlu
      denetimleri taşır. Ödeme tarihi düzeltmesinde de 20 gün uyarısı vardır.
    - Pusula her durumda tek sayfadır (sığmazsa küçültülür); tablolar çerçeveye sığar. Eski onayın
      çıktısı onaydaki devirle kurulur (devir onayda saklanır). Saklı ayda puantaj tablosu birim
      süzgeçsiz kurulur. Çıktıların dosya adı durumu söyler (taslak, onay sırası, geçersiz); tek
      kişinin pusulasında onaydaki sicil no.
  - İkinci inceleme (2026-11-03; her düzeltme ayrı ajanla denetlendi, düzeltmelerin açtığı yeni
    hatalar arandı):
    - Zincir ve ayın kendi görünümü "kişi o ay bordroda" için aynı kuralı kullanır: kartına göre
      işte olduğu bir günde puantajda durumu var. İşe giriş tarihi sonradan ileri alınan kişinin
      eski günlerinin kaydı sayılmaz (o ay mali müşavirde de sayılmaz); kartı değişenler listesinde
      yalnızca o ay bordroda olanlar yazar.
    - Onay penceresi her kişinin onayda hangi işaretlerle saklanacağını yazar (kartı izleyende
      kartınki, diğerinde onaydaki).
    - Sığmayan pusula bütünüyle küçültülür ve ortalanır (tablolar ve notlar aynı hizada).
    - Onaylı aydaki devir yeni işe giriş tarihine sığmıyorsa hata önce o ayın bordrosunun yeniden
      açılmasını söyler; yeniden açılan ayda onaydaki haliyle ERP'de olan kişiye mali müşavir rakamı
      girilmek istenirse hata "Kartı izle"yi gösterir.
    - İşe giriş tarihi geri alınınca kişi, satırı olmayan onaylı bir ayda (ya da 2026'da ERP
      bordrosundan önceki Ocak–Eylül'de) işte sayılmaya başlıyorsa ve aynı yılın sonraki ilk
      onaylı satırı ERP'de, zinciri o aydan sonraki bir devirle başlamıyorsa değişiklik o
      satırın kümülatifini değiştirir: reddedilir
      (`payroll_approved`; önce o ayın bordrosu yeniden açılır, açılan ayda zincir kopar ve devir
      istenir). Onaylı satır değişmez kuralının uygulamasıdır.
    - "Önceki ay ERP'de" (devrin eşitleme sayılması) açık ayda da "kişi o ay bordroda" kuralıyla
      bakılır: puantajı onaylı ayda günü olmayan kişinin sonraki ay devri eşitleme onayı istemez.
      Giriş ayı kişinin kesintisiz ERP zincirinin ilk ayıdır: eşitleme devrinde (önceki ay ERP'de)
      devirden önceki giriş kalır, ekran devri düzeltirken de onay ister; devirden önceki ay ERP'de
      değilse (zincir devirden önce kopmuş olsa da) giriş ayı devir ayıdır.
    - Kart değişikliği onayda saklanacak hali sunucudan alır: o aya girilmiş mali müşavir rakamı
      kişiyi işaretlerden bağımsız mali müşavirde tutar ve satırında yazar.
    - Kart "mali müşavirde" işaretlenince yeniden açılan ayda onaydaki haliyle ERP'de kalan
      kayıtlar ayrıca yazılır ve "Kartı izle" gösterilir; diğer ayların kayıtları için "mali
      müşavire bildirin" denir. O aya mali müşavir rakamı girilmişse kişi o ayda mali
      müşavirdedir (ERP'de kalıyor denmez).
    - Aynı yıl içinde ayrılıp yeniden işe başlatılan kişide kart aradaki boşluğu tutmaz: aradaki
      onaylı ayda satırı olmadığından zincir kopar ve ilk açık ayda devir istenir (güvenli yön;
      yeniden işe alım kapsam dışı).

## 2026-11-04 — İki aşamalı doğrulama canlıda yeniden zorunlu

- **Karar (CUMHUR, "İki adımlı doğrulamayı yönetim ve admin için yeniden zorunlu yapayım mı?"
  sorusuna "Evet, zorunlu yap"):** ön bordro canlıya alındıktan sonra, bordro ve ücret verisi
  girilmeden önce admin ve yönetim rollerinde 2FA yeniden zorunlu. 2026-10-25'teki geçici kararın
  yerine geçer; D-21 kurulumundaki duruma dönülür.
- **Uygulama (kod değişmedi):** canlı `.env.prod` içinde `OTP_REQUIRED_ROLES=admin,yonetim`, ardından
  `scripts/prod-compose.sh up -d --wait`. Öncesinde `.env.prod.yedek-20261104-092817` alındı.
- **Etkisi:** bu rollerde doğrulayıcısı kurulu olmayan kullanıcı bir sonraki işleminde Güvenlik
  sayfasına yönlendirilir ve kurulumu bitirmeden başka işlem yapamaz (telefonda bir doğrulayıcı
  uygulaması gerekir; kurtarma kodları saklanır). Kontrol listesi madde 22 ve 25, kurulumlar
  bitince işaretlenir.
- **Geri dönüş:** `.env.prod` içinde `OTP_REQUIRED_ROLES=` (boş) ve aynı yeniden başlatma.
- **Sona erdi (2026-11-04):** 2FA yine geçici olarak zorunlu değil; bkz. "2026-11-04 — İki aşamalı
  doğrulama canlıda yine geçici olarak zorunlu değil".

## 2026-11-04 — react-router 7'ye geçiş

- **Karar (CUMHUR, "react-router'ı 7.x'e yükseltmeye başlayayım mı?" sorusuna "Evet, başla"; plan
  için "Evet, uygula"):** `react-router-dom` 6.30.6'dan 7.18.5'e geçer; 2026-10-24'teki "7.x'e
  geçilmez" kararının yerine geçer. Gerekçe: npm audit'in iki orta düzey uyarısı 7.18'de kapanır
  (GHSA-wrjc-x8rr-h8h6, bağlantı ve yönlendirmede ters bölüyle açık yönlendirme, tek sayfalı
  uygulamayı da kapsar; GHSA-337j-9hxr-rhxg, yalnızca sunucu tarafı çizimde). 8.x React 19 istediği
  için kapsam dışı; 7.x React 18 ile çalışır ve bakımdadır.
- **İçe aktarmalar değişmedi:** `react-router-dom` 7, `react-router`'ı ve DOM `RouterProvider`'ı
  yeniden dışa aktarır.
- **Sayfa geçişleri 6'daki zamanlamada:** v7 yönlendirici güncellemelerini varsayılan olarak React
  transition'ı içinde çizer. Uygulama ve testler ortak `AppRouterProvider`'ı (`useTransitions={false}`)
  kullanır. Gerekçe: uygulamada Suspense yok, transition bir şey kazandırmaz; açık olsaydı kaydedip yeni
  sayfaya geçen formlar (mal kabul, emirler, siparişler, iadeler) geçiş çizilene kadar bir an daha
  tıklanabilir kalırdı. Ayar kaldırılırsa `App.test.tsx`'teki "giriş yapınca istenen sayfaya döner"
  testi kırılır.
- **Uygulama içi adres denetimi sıkılaştı:** girişten sonraki dönüş adresi ve sorun bildirimindeki
  sayfa bağlantısı, çözüldükten sonra başka siteye gidebilecek yolları da reddeder; sunucu da sorun
  bildiriminin sayfa adresinde "." ve ".." bölümlerini kabul etmez. v7'nin kendi denetimi (dış adrese
  yönlendirme hata verir) ek bir katmandır; uygulamanın denetimi kalır.
- **Bilinen, kabul edilen:** tarayıcı paketi yaklaşık 10 KB (gzip) büyür. v7 paketinin dışa aktarma
  haritası üretimde de geliştirme yapısını seçer; üretim paketinde birkaç geliştirici uyarısı metni
  kalır, uygulamanın kullandığı yollarda çalışmaz.

## 2026-11-04 — İki aşamalı doğrulama canlıda yine geçici olarak zorunlu değil

- **Karar (CUMHUR, "iki aşamalı doğrulamayı kaldıralım"; kapsam sorusuna "Herkesten", kayıt için
  "Geçici"):** canlıda giriş şimdilik yine yalnızca şifreyle; ileride yeniden zorunlu yapılacak.
  Aynı günün "İki aşamalı doğrulama canlıda yeniden zorunlu" kararının yerine geçer;
  2026-10-25'teki düzene dönülür.
- **Uygulama (kod değişmedi):** canlı `.env.prod` içinde `OTP_REQUIRED_ROLES=` (boş), ardından
  `scripts/prod-compose.sh up -d --wait`. Kurulu doğrulayıcılar için kullanıcıya soruldu; seçimine
  göre sunucu kabuğundan `security.reset_otp` kullanıldı (denetim günlüğünde "İki aşamalı doğrulama
  sıfırlandı"). Öncesinde `.env.prod.yedek-20261104-151959` ve veritabanı yedeği `20261104T152000`
  alındı.
- **Etkisi:** kimse 2FA kurmaya zorlanmaz; isteyen kullanıcı Güvenlik sayfasından kendisi açabilir
  (açan her girişte kod girer). Yönetim paneli girişi de şifreyle. Bordro ve ücret verisine de
  yalnızca şifreyle erişilir.
- **Geri dönüş:** `.env.prod` içinde `OTP_REQUIRED_ROLES=admin,yonetim` ve aynı yeniden başlatma. Bu
  rollerdeki kullanıcılar bir sonraki işleminde Güvenlik sayfasında kurulumu yapar; kontrol listesi
  madde 22 ve 25 o zaman yeniden işaretlenir.

## 2026-11-04 — Kodlama sistematiği

- **İstek (CUMHUR):** "tüm kod gerektiren kısımlara iso standartlarına göre kod ekleyelim. Ayrıca
  kodlama sistematiği için ayar ekranı ekleyelim". Plan: `docs/plan/kodlama-sistematigi.md`.
- **Kararlar (CUMHUR, 2026-11-04, soruların yanıtları):**
  - Kapsam: ana veri kodları, belge ve lot numaraları, çıktılarda doküman kodu, barkodlar (GS1).
  - Kod üretimi: "Sistem önersin"; kullanıcı kodu değiştirebilir, ama kod biçime uymalıdır.
  - Mevcut kodlar: "Yeni sistematiğe geçsin"; eski kod kayıtta kalır ve aranabilir. Verilmiş belge
    ve lot numaraları değişmez.
  - Ayar yetkisi: "Yalnız admin"; her değişiklik denetim günlüğüne yazılır.
  - Varsayılan biçimler: "Bugünkü düzeniniz", yani canlıda kullanılan `MLZ-0000001`, `KAT-0001`,
    `DEPO-00001`, `LOKASYON-0001`, `TANK-00001`, `TED-000001`, `REC-0000001` düzeni.
  - Kod kilidi: kayıt açıldıktan sonra kodu "Yalnız admin" değiştirir.
  - Lot tarihi: "ISO 8601" (`H-20261104-001`); D-2'deki `YYMMDD` düzeninin yerini alır.
  - Uygulama: iki paket sırayla; push ve PR her paketin sonunda sorulur.
- **Planla onaylanan, ayrıca sorulmayan kurallar** (değiştirilebilir):
  - Kullanılmış bir kod aynı türde başka bir kayda hiçbir zaman verilmez; kayıt kendi eski koduna
    dönebilir.
  - Önerilenden en çok 10 ileri yazılan numara sayacı ilerletir; daha ilerisi kabul edilir ama
    sayacı ilerletmez.
  - İrsaliye numarası (SV) yasal belge numarası olduğu için ekrandan değiştirilemez.
  - Belge ya da lot öneki değişince yeni önekte sayaç 1'den başlar; eski önek başka türe verilmez.
  - Ana veri biçimleri kapalı gelir; admin ekrandan etkinleştirir.
  - Canlıda kaydı olmayan türler için önekler: müşteri `MUS`, yazıcı `YAZICI`, stok tankı `STOK`,
    terazi `TERAZI`, diğer ekipman `EKIPMAN`.
- **ISO notu:** ISO 9001 belirli bir kod biçimi istemez; benzersiz tanımlama (md. 8.5.2) ve
  doküman kontrolü (md. 7.5) ister. Tarihlerde ISO 8601, barkodlarda GS1 uygulanır. Bu çalışma tek
  başına ISO 9001 uygunluğu sağlamaz; denetimde kanıt olarak kullanılabilir.
- **CLAUDE.md:** kural 10'un metni geçerliliğini korur; değişiklik gerekmedi. Numara hâlâ
  `next_document_number` ile, yıl bazında ve kilitli üretilir; `UE-2026-00001` varsayılan biçimdir.
- **D-18:** değişmedi. Kartlar bu sistemde açılır ve muhasebeye bu kodlarla gider.
- **İnceleme sonrası netleşen kurallar** (2026-11-05, bağımsız incelemenin doğrulanmış bulguları):
  - Sayaç penceresi önerilen koddan ölçülür: önerilen kod ya da ondan en çok 10 ileri numara
    sayacı ilerletir. Böylece sayacın üstünde dolu numaralar varken sayaç takılı kalmaz.
  - Sayaç düzeltmede sıradaki numara en çok 15 hanedir (veritabanında ve ön yüzde tam sayı kesin
    kalsın; gerçekte bu kadar kayıt olmaz).
  - Paket 1'den önceki kod değişiklikleri `backfill_code_history` komutuyla denetim günlüğünden
    eski kod geçmişine yüklenir (canlıya alma adımı). Komut tekrar çalıştırılınca bir şey yazmaz.
    Eski kod şu an başka bir kaydın koduysa (sistematikten önce o kayda verilmişti) eski kod olarak
    yazılmaz ve özette listelenir: o kaydın kodu ona aittir, göçü geri alınabilir.
  - Kilit çakışması (bekleme süresi doldu ya da kilitlenme) sunucu hatası sayılmaz: istek geri
    alınır, 400 `busy` ("birkaç saniye sonra yeniden deneyin"); kod göçünde `recode_busy`.
  - Yetki hatalarında (403) servisin Türkçe mesajı döner (ör. kod kilidi); mesajsız hatada genel
    metin.
  - Göç öncesi yedek uyarısı göçü engellemez; ekran son yedeği gösterir, son 24 saatte başarılı
    yedek yoksa uyarır.
- **Paket 2, çıktı doküman kodları: ayrıca sorulmayan kurallar** (değiştirilebilir):
  - Çıktılar kapalı gelir (bugünkü gibi basılır). Bant, doküman no, ilk yayın tarihi ve en az bir
    revizyon girilince açılabilir. Doküman no çıktılar arasında tektir (A-Z, 0-9, -, . ve /; en çok
    32 karakter). Öneri kodları (`FR-KAL-001`, `LS-RAP-001` gibi) yalnızca örnektir.
  - İlk revizyonun numarası seçilebilir: kalite sisteminde Rev. 03'te olan form sisteme 03 ile
    girilir (varsayılan 00). Sonraki revizyonlar birer artar; revizyonlar değiştirilemez ve
    silinemez.
  - Revizyon onaylandıktan sonra yürürlüğe girer: onay tarihi yürürlük tarihinden sonra olamaz.
    Tarihler ileri olamaz; yürürlük tarihi önceki revizyondan ve ilk yayın tarihinden önce olamaz.
  - Belge kendi tarihindeki bantla basılır, yeniden basımda da (aşağıda sahibin "İlk basımdaki
    gibi" kararı). İlk revizyondan ve bandın açıldığı günden önceki tarihli belge bantsız basılır
    (o gün de bantsızdı).
  - Kodlar da belgenin tarihindeki haliyle basılır: irsaliyede ürün ve müşteri kodu sevk anındaki,
    analiz sertifikasında ürün kodu karar anındaki, siparişte malzeme ve tedarikçi kodu siparişin
    gönderildiği andaki.
- **Paket 2, GS1: ayrıca sorulmayan kurallar** (değiştirilebilir; GS1 standardından ya da
  okutulabilirlikten çıkan sonuçlar):
  - GS1 ayarlarını yalnız admin değiştirir, not zorunludur. Firma öneki değişince sıradaki ürün
    referansı silinir (aynı istekte verilmedikçe): referans önekle birlikte anlam taşır, yeni
    önekte ilk boş referans yeniden girilir.
  - SSCC seri no, önek ya da uzantı değişince o önekle basılmış en büyük seri no + 1'den sürer;
    basılmış SSCC hiçbir zaman yeniden verilmez. Palet koli sayısı en çok 99.999.999'dur.
  - GTIN tekilliği 14 haneli normal biçimde, ürün ve koli GTIN'lerinin tamamında, pasif kayıtlar
    dahil denetlenir. Koli ayrı bir ticari üründür: malzemenin koli GTIN'i kendi ürün GTIN'i
    olamaz; tanımlı ama geçersiz koli GTIN'inde etikete ürün GTIN'i basılmaz.
  - Lot kilidi yalnız geçerli GTIN'de: geçersiz eski GTIN (okutulamayan) düzeltilebilir; aynı
    GTIN'i başka uzunlukta yazmak (8690000000012 → 08690000000012) değişiklik sayılmaz.
  - Önerilen GTIN ya da ondan en çok 10 ileri ürün referansı sayacı ilerletir (kodlardaki sayaç
    penceresi gibi, önerilen referanstan ölçülür).
  - Etikete yalnız okutulabilen GS1 barkodu basılır: GTIN geçerli; lot no en çok 20 karakter,
    GS1 karakter kümesinde ve parantez ya da > içermiyor (ZPL'in GS1 kipi bunları ayırıcı sayar);
    koli sayısı en çok 8 hane. Değilse firma içi `LOT:` barkodu basılır. Türkçe harf ve >
    çizgi barkoda yazılmaz (Code128 Türkçe harfi taşımaz, ZPL'de > kip önekidir): o lotta ve
    lokasyonda çizgi barkod yerine "QR kodu okutun" notu basılır. İçe aktarılan Türkçe harfli lot
    numaraları reddedilmez. Türkçe harfli QR'ın Zebra'da okunduğu deneme baskısıyla sınanacak;
    okunmazsa kod etiketten elle girilir.
  - ZPL alan verisindeki ^, ~ ve ters bölü onaltılık kaçışla (`^FH\`) gönderilir; ^FB metin
    bloğunda ters bölü ayrıca ikilenir.
  - Okumada eski etiketler için tek gevşeklik (10) alanındadır: en çok 64 basılabilir ASCII
    karakter. Öteki alanlar GS1'e tam uyar; tanınmayan AI kabul edilmez.
  - GS (FNC1), okutulan verinin neresinde olursa olsun (başta, ortada, sonda) veriyi GS1 yapar.
    Okutulan kodun kenarındaki boşluk karakterleri (NBSP, dikey sekme dahil) hiçbir kodda veri
    sayılmaz ve atılır; kenardaki GS de atılır ama GS1 işareti sayılır. Bu yüzden üretim, dolum
    ve sevkiyatın lot alanları API'de kırpılmaz; kırpmayı lot çözümü yapar.
  - Tarihte gün 00: son kullanma ve son satış tarihlerinde (15, 16, 17) ayın son günü; üretim,
    paketleme ve ödeme tarihlerinde (11, 12, 13) gün yok sayılır, tarih gösterilmez.
  - Koli GTIN'i pasif dönüşümdeyse okutma malzemeyi ve lotu bulur, koli içi miktar önermez.
- **Paket 2, standart kodlar: sahibin kararı (CUMHUR, 2026-11-05):** koli birimi `XCT`, palet
  `XPX` (UN/ECE Rec 21 ambalaj kodunun başına X; GİB UBL-TR birim listesi v1.42'de ambalaj birimi
  yok). e-Belge entegrasyonunda (Faz 5) mali müşavir ya da entegratörle doğrulanır.
- **Paket 2, standart kodlar: ayrıca sorulmayan kurallar** (değiştirilebilir):
  - UN/ECE kodu biçimle denetlenir (2-3 büyük harf ya da rakam); Rec 20 listesinin tamamı
    denetlenmez. Ülke ve dil kodları ISO listesiyle denetlenir.
  - Excel'de boş ülke kodu TR, GBF'de boş dil tr sayılır.
  - GBF dilinin eski serbest metin değerleri göçte (hse 0003) koda çevrilir: baştaki ve sondaki
    boşluk atılır, genel ve Türkçe kurala göre küçük harf yapılır (İ → i, I → ı); yaygın üç
    harfli kodlar ve sütuna (8 karakter) sığan Türkçe ya da İngilizce adlar koda çevrilir (tur,
    türkçe, ingiliz, almanca, fransız, ispanyol, italyan, arapça, rusça …); boş değer tr olur.
    Yalnız geçerli bir ISO 639-1 koduna karşılık gelen değer yazılır; tanınmayan değer olduğu
    gibi kalır (küçük harfe çevrilmez, silinmez). Göç hiçbir değerde hata vermez (inceleme
    arka-1).
  - Yönetim panelinde (Django admin) cari ülke kodu, birimin UN/ECE kodu ve sembolü salt
    okunurdur: panel kaydı servisteki ISO ve biçim denetimini atlar (GTIN gibi); bu alanlar
    uygulamadan girilir (ülke kodu Excel'den de). Kullanılan birimin türü ve katsayısı da
    panelde salt okunurdur (servis kuralı `unit_in_use`; katsayı değişseydi o birimle
    çevrilen her miktar sessizce değişirdi).
- **Paket 2, GS1: sahibin kararları (CUMHUR, 2026-11-05, soruların yanıtları):**
  - Koli içi adet: "Yeni koli GTIN'iyle". Lotu olan mamulde koli içi miktar ancak aynı kayıtta yeni
    koli GTIN'i girilerek değişir. Eski koli GTIN'i eski miktarıyla arşivlenir, bir daha kimseye
    verilmez; depodaki eski koliler okutulunca eski miktar önerilir. Gerekçe: GS1'de ticari birimin
    içeriği değişince yeni GTIN gerekir.
  - GTIN kilidi: "Yalnız mamulde". Hammadde, ambalaj ve yarı mamulde tedarikçi GTIN'i lot olsa da
    düzeltilebilir; biçim ve tekillik kuralları her türde geçerlidir.
  - Tür kilidi: "Lot varken değişmesin". Lotu olan malzemenin türü mamulden ya da mamule
    değiştirilemez (ekran, Excel aktarımı ve yönetim paneli); yanlış türde açılmış kart için yeni
    kart açılır. Gerekçe: GTIN kilidi, koli içi miktar kuralı ve eski koli GTIN'leri mamule
    bağlıdır.
  - İrsaliyede koli sayısı: "Lotun koli düzeniyle". Koli sayısı lotun açıldığı gün geçerli koli içi
    miktarla hesaplanır; sevk edilmiş irsaliyenin yeniden basımı değişmez.
- **Bu kararlardan çıkan, ayrıca sorulmayan kurallar** (değiştirilebilir):
  - Lotun koli düzeni (koli içi miktar ve koli GTIN'i) lot açılırken lota yazılır; lotun koli ve
    palet etiketleri ve irsaliyedeki koli sayısı bununla basılır: eski lotun yeniden basılan
    etiketi eski GTIN'i taşır (uygulaması aşağıda, "Lotun koli düzeniyle").
  - Arşivdeki GTIN aynı malzemeye de yeniden verilmez.
  - Okutmada önce ürün GTIN'i, sonra güncel koli GTIN'i ((02)'de önce koli GTIN'i), en son arşiv
    aranır; arşivdeki miktar dönüşüm pasif olsa da kullanılır.
  - Sıfır ya da eksi koli içi miktarı alan doğrulaması reddeder; koli GTIN'i kuralları bu değerde
    ayrıca hata vermez.
- **Paket 2, çıktılar: sahibin kararı (CUMHUR, 2026-11-05, "Yeniden basım" sorusuna "İlk
  basımdaki gibi"):** yeniden basılan belge kendi tarihinde basıldığı bandı taşır. Doküman no ve
  yayın tarihi revizyonla birlikte saklanır; numara değişikliği yeni revizyonla yapılır. Bant
  açılmadan önceki tarihli belge bantsız basılır; bant sonradan kapatılsa da açıkken tarihli
  belgenin yeniden basımı bantlı kalır. "Belge kendi tarihindeki kodlarla basılır" kuralının
  devamıdır.
- **Bu karardan çıkan, ayrıca sorulmayan kurallar** (değiştirilebilir):
  - İlk revizyon doküman no ve ilk yayın tarihiyle girilir (ikisi zorunlu). Ondan sonra ikisi
    ekrandan değiştirilmez (`output_doc_locked`): yeni revizyonla değişir ve o revizyonla basılır.
    Yanlış numaralandırma da böyle düzeltilir; çıktı kendi eski numarasına yeni revizyonla
    dönebilir.
  - Revizyon, yürürlük tarihinden ve girildiği günden (hangisi sonraysa) itibaren basılır.
    Geriye tarihli girilen revizyon girildiği günden önceki tarihli belgelere basılmaz: o
    belgelerin yeniden basımı ilk basımdaki gibi kalır. Kalite sisteminin geçmiş revizyonları yine
    girilebilir.
  - Bandın açılıp kapanması gün olarak saklanır, o günden itibaren geçerlidir. Gün düzeyindedir:
    aynı gün birden çok değişiklikte sonuncusu geçer, aynı gün girilen revizyon o günkü belgelere
    basılır.
  - Bir çıktının revizyonlarına yazılmış doküman no (bant kapalıyken girilmiş, hiç basılmamış
    olsa da) başka bir çıktıya verilmez.
  - Çıktı tarihleri (ilk yayın, yürürlük, onay) 01.01.2000'den önce olamaz: iki haneli yıl yazım
    hatası (ör. 0026) revizyon silinemediği için düzeltilemezdi. Bantta yıl dört hanedir.
  - Göç (core 0008): var olan revizyonlara çıktının o anki doküman no ve ilk yayın tarihi
    yazılır; bugün bandı açık çıktı, ilk revizyonunun yürürlük tarihinden (revizyon yoksa kaydın
    açıldığı günden) beri açık sayılır.
  - Ekranda kilitli çıktının üstteki doküman no ve ilk yayın tarihi kapalıdır; revizyon formunda
    kayıttakilerle gelir, boş bırakılamaz, yalnız değişeni gönderilir. Kayıt sürerken pencere
    kapatılır ya da başka çıktı açılırsa sonuç açık pencereye yazılmaz: liste güncellenir, sonuç
    bildirimle söylenir.
- **"Lotun koli düzeniyle" kararının uygulaması** (inceleme sonrası; ayrıca sorulmayan,
  değiştirilebilir):
  - Lotun koli düzeni (koli içi miktar ve koli GTIN'i) lot açılırken lota yazılır ve değişmez.
    İrsaliyedeki koli sayısı ve lotun koli ve palet etiketleri bunu kullanır. Koli GTIN'i olsun
    olmasın her mamulde geçerlidir: koli içi miktar değişse, koli GTIN'i sonradan ilk kez girilse,
    kilitli koli GTIN'i yeni GTIN'le değişse, koli dönüşümü pasife alınsa ya da Excel'den
    güncellense de önceden açılmış lotun etiketi ve sevk edilmiş irsaliyenin yeniden basımı
    değişmez.
  - O gün koli GTIN'i olmayan lotun etiketine ürün GTIN'i basılır; malzemeye sonradan girilen
    koli GTIN'i yalnız sonra açılan lotlara basılır. KOLI dönüşümü pasifken açılan lotta koli içi
    miktar yoktur (irsaliyede koli sayısı boş); pasif dönüşümün koli GTIN'i etikete basılır
    (okutmadaki gibi). Kontrol hanesi yanlış koli GTIN'iyle açılmış lot GS1'siz basılır;
    düzeltilen GTIN sonra açılan lotlara basılır.
  - Lot açılırken mamulün KOLI dönüşümü işlem sonuna kadar kilitlenir: lot açan işlem (dolum
    başlangıcı, mal kabul, açılış stoku içe aktarması) sürerken KOLI dönüşümünde kaydedilen
    değişiklik işlemin bitmesini bekler ve açılan lotu görür; süren değişikliği de lot bekler ve
    yeni düzeni alır. Koli GTIN'i kilitli satırdan, koli içi miktardan önce okunur: lot
    açılırken KOLI dönüşümü yoksa o sırada kaydedilen dönüşümün koli GTIN'i lota yazılmaz; lot
    en çok o dönüşümün koli içi miktarını alır, etiketine ürün GTIN'i basılır.
  - Var olan mamul lotları göçte (inventory 0008) açıldıkları andaki düzenle doldurulur (lotun
    açıldığı andan sonraki ilk arşiv satırı, yoksa bugünkü KOLI dönüşümü; temel birimi koli olan
    mamulde 1).
  - "Yeni koli GTIN'iyle" kuralı koli GTIN'i tanımlı mamulde geçerlidir. Koli GTIN'i olmayan
    mamulde koli içi miktar doğrudan değişir; arşivlenecek GTIN yoktur, eski lotlar etkilenmez.
  - Etiket penceresinde "Koli içi adet" lotun koli içi miktarıyla gelir (temel birimi adet olan
    mamulde). Lot koli GTIN'i taşıyorsa farklı adet yazılınca sarı uyarı çıkar, engellenmez
    (eksik son koli gibi durumlar).
- **İnceleme sonrası ayrıca** (2026-11-05; ayrıca sorulmayan, değiştirilebilir):
  - "Koli GTIN'i öner" yalnız mamulde: hammadde, ambalaj ve yarı mamulün GTIN'i tedarikçinindir
    (GS1'de koli GTIN'ini marka sahibi verir); tedarikçinin koli GTIN'i koli etiketinden girilir.
  - GS1 ve çıktı ayarlarındaki değişikliklerin notu denetim günlüğüne yazılır; Kodlama
    sistematiği > Geçmiş yalnız biçim değişikliklerini ve kod göçlerini listeler.
  - Kılavuz: tedarikçinin koli barkodu (GS1) lotu bulmaz, çünkü barkoddaki lot numarası
    tedarikçinindir. Lot etiketiyle okutulur. Tedarikçi lot numarasıyla eşleştirme ayrı bir
    özelliktir, istenirse sahibe sorulur.

## 2026-11-10 — Kişiye özel yetkiler

- **İstek (CUMHUR):** "kullanıcılara yetkinlik atamak istiyorum. modülleri görüntüleye bilme ve
  değiştirebileceği bir sistem geliştirelim". Plan: `docs/plan/kisi-yetkileri.md` (CUMHUR onayladı,
  2026-11-11: "Onaylıyorum").
- **Kararlar (CUMHUR, 2026-11-10, soruların yanıtları):**
  - Yapı: "Rol + kişiye ek/çıkar". Roller varsayılan yetki paketidir; admin kişiye yetki ekler ya
    da rolünden geleni kaldırır. İlk gün herkesin erişimi bugünküyle aynıdır.
  - Ayrıntı: "Modül ve alt bölüm"; düzeyler Görür, Değiştirir, Onaylar.
  - Onaylar ayrı yetkidir: lot serbest bırakma ve ret, şartlı kabul, emir ve reçete onayı, D-13
    limitiyle satın alma onayı, sevk onayı, puantaj ve bordro onayı.
  - Hassas veri: "Fiyatları görür" ve "Maliyetleri görür" ayrı haklardır. Personel ve bordro
    yalnız yönetim rolündekilere verilebilir (KVKK); bugünkü kural sürer.
  - Görevler: "Gelmesin". Görevler role gider; rolde olup görevin gerektirdiği yetkisi kaldırılan
    kişi görevi ve bildirimini almaz, göremez, üstlenemez. İşi yapabilecek kimse kalmazsa yetki
    kaydedilirken uyarı çıkar.
  - Fiyatlar: "Yalnız alış fiyatları". Fiyatları görür; mal kabul fiyat ve masraflarını, satın alma
    tutarlarını ve sipariş PDF'ini kapsar. Satış siparişi fiyatlarını bugünkü gibi siparişi gören
    herkes görür.
  - Onaylar'ın kapsamı: "Evet, Onaylar'a bağlı". Satış siparişinde "Onayla ve rezerve et", sayım
    düzeltmede "Kaydet ve stoka al" ve onaylanmış bir belgeyi iptal etme ya da yeniden açma da
    Onaylar'dır. Modül ayarları (onay limiti, bakım ve İSG ayarları) ve canlı başlangıç tarihi ayrı
    "Ayarlar" satırında Değiştirir'dir.
  - Rol paketleri: "Hayır, sürümle değişsin". Ekranda salt okunur; değişiklik testle ve DECISIONS
    kaydıyla yeni sürümde gelir.
  - KVKK: "İkisi de yalnız yönetime". "Olaylar ve kazalar" ve "Denetim günlüğü" de yalnız yönetim
    rolündekilere verilebilir.
  - Görev ayrılığı: "Şartlı kabulde zorla, diğerlerinde uyar". Şartlı kabulü öneren kişi onu
    onaylayamaz (admin dahil). Diğer riskli birleşimlerde yetki kaydedilirken uyarı çıkar.
  - İki aşamalı doğrulama: "Admin ve yönetime zorunlu". Yetki ekranı canlıya alınmadan önce admin
    ve yönetim için yeniden zorunlu olur.
  - Açık okumalar: "Evet, ayrı bir adımda". Bugün giriş yapan herkesin okuyabildiği kayıtlar ilk
    sürümde aynen kalır; bir kişi için kapatılabilir, lot sayfası ve seçim listeleri çalışmaya
    devam eder. Sonra ayrı bir adımda (Faz B) yalnız Görür yetkisi olanlara kapatılır.
- **Planla önerilen, ayrıca sorulmayan kurallar** (plan onayıyla kesinleşti, 2026-11-11):
  - Değiştirir ve Onaylar, Görür düzeyi olan bölümlerde Görür'ü verir. Onaylar Değiştirir'i,
    Değiştirir Onaylar'ı kapsamaz. Görür'ü olmayan işlem bölümleri menüde modül açmaz.
  - İlk gün erişimin aynı kaldığını bugünkü koddan üretilen sözleşme testi kanıtlar. Anlık görüntü
    yalnız planın §8'indeki maddeler kadar değişir; başka her fark sahibin onayını ve DECISIONS
    kaydını ister.
  - Herkese açık ve kişiden kaldırılamaz: stok sorgu ve lotlar (analiz sertifikası dahil), palet
    listesi (herkes); tehlike bilgileri, arıza bildirimi ve olay bildirimi (rolü olan herkes).
  - İlk sürümde kişiden kapatılamayan okumalar: ana veri kartları (müşteri ve tedarikçinin vergi,
    adres ve iletişim bilgileri hariç), birimler, yazıcılar, etiket ayarları ve firma bilgileri
    (herkes); duruş kayıtları (rolü olan herkes). Seçimler ve etiket basımı bunlara bağlıdır.
  - Açık okumalı bölümde Görür'ü kaldırmak yalnız ekranı kapatır. Kayıtları da kapatmak için
    modülün "Açık kayıtlar" satırında "Kayıtları okur" kaldırılır; kişi o zaman modülün
    kayıtlarını yalnız Görür'ü olan bölümlerden okur. Lot sayfasının kalite bölümü, üretim emri
    formundaki reçete seçimi, mal kabulün lot etiketleri, analiz sertifikası ve seçim listeleri
    açık kalır.
  - Ana veriler'de kapatılınca vergi, adres ve iletişim bilgileri; tedarikçi kartında Ana veri
    kartları: Görür'ü, müşteri kartında Ana veri kartları ya da Satış siparişleri: Görür'ü
    olmayan kişiye boş döner (sade kart); arama da yalnız kod, eski kod ve adda yapılır.
    Sevkiyat'ın Müşteriler sekmesi ve müşteri kartı, siparişleri gören kişide tam kalır.
  - Yalnız Görür'ü olan da yorum yazar, @bahseder ve dosya ekler. Baskı ve dışa aktarım bölümün
    okumasına bağlıdır: açık okumalı bölümlerin çıktıları açık okumayı izler; lot, mal kabul ve
    lokasyon etiketi basma ile yazıcı denemesi herkese açıktır; fiyatlı belgeler Fiyatları görür'ü
    de ister.
  - Ön koşullar: Maliyetleri görür, Fiyatları görür'ü ister (hammadde lotunun maliyeti alış
    fiyatıdır). Bordro, Ücretler: Görür'ü ister. Personel maliyeti; Maliyetleri görür, Ücretler:
    Görür ve Bordro: Görür'ü ister.
  - Panodaki onay bekleyen satın alma siparişi toplamı Fiyatları görür'e (karar 6), stok değeri
    Maliyetleri görür'e bağlıdır. Toplamı bugün yalnız yönetim görüyor; fark 1. adımda ortaya
    çıktı. CUMHUR plandaki kuralı onayladı (2026-11-11): 6. adımdan sonra panoyu açabilen ve
    Fiyatları görür'ü olan kişi de toplamı görür (ör. planlama ve satın alma rollerini birlikte
    taşıyan, yönetimde olmayan kişi; tutarları satın almada zaten görüyor). İlk gün değişikliği
    olarak plan §8'e eklendi.
  - Personel ayarları (bordro parametreleri, hafta tatili günleri) ve canlı başlangıç tarihi kendi
    "Ayarlar" satırlarındadır (karar 7). Onaylı bordronun ödeme tarihini düzeltmek Onaylar'dır.
  - Var olan kullanıcının rolleri ve yetkileri yalnız admin tarafından, Sistem > Kullanıcılar >
    Yetkiler ekranında, gerekçe yazılarak değiştirilir; kullanıcı düzenleme uç noktası rol almaz.
    Yeni kullanıcının ilk rolleri açılış penceresinde verilir. Kişi kendi kişiye
    özel yetkilerini değiştiremez; kendi rollerini değiştirebilir, kendi admin rolünü kaldıramaz.
    Admine kişiye özel yetki tanımlanmaz; admin rolü ya da süper kullanıcı verilince etkin
    ayarlar biter. Geçmiş silinmez. Django panelinde roller, süper kullanıcı ve panele giriş
    işaretleri salt okunurdur. "Kim neyi görür" yalnız admine açıktır. Denetim günlüğünde
    kişiye özel yetkilerin önce ve sonra hâli ve yetki değişikliğinin gerekçesi yalnız admine
    görünür; rol değişiklikleri, giriş kayıtları ve sorun bildirimleri yönetime bugünkü gibi
    görünür.
  - Görevi üstlenen kişi gereken yetkisini ya da rolünü kaybederse görevi görmez ve tamamlayamaz;
    yetkili başka bir üye tamamlar. "Tüm birimlerin görevleri" başka rollerin görevlerini
    bugünkü gibi gösterir; kişinin kendi rollerinin görevlerinde karar 5 geçerlidir.
  - Bildirimler, kuralın bölümünde Görür'ü olan rol üyelerine gider. Tartım sapması ve ara kontrol
    reddi, hedeflerine karar verilene kadar bugünkü gibi gider.
  - Rolsüz kullanıcıya kişiye özel yetki verilebilir; görev almaz, ekranda uyarı çıkar.
  - Yetkisi ya da rolü değişen kişiye bildirim gider; gerekçe gösterilmez.
  - Pano ve rapor yetkileri ayrıdır; bir bölümü kaldırmak panodaki özetini kaldırmaz. Rapor
    dosyası indirilirken raporun yetkisi yeniden denetlenir.
  - Kişinin açamayacağı sayfaya giden kayıt bağlantıları düz metin görünür; "Kayda git"
    gösterilmez.
  - Kayıt geçmişindeki ve denetim günlüğündeki tutar içeren notlar ve silinen satır kayıtlarının
    içindeki fiyatlar da fiyat ve maliyet yetkisine bağlanır. Personel maliyetinden açılan yeni
    gider oranının notunda yalnız bordro numarası yazar.
  - Yetki paketlerinin kopyası her sürümde saklanır ve denetim günlüğüne yazılır.
- **İlk gün değişiklikleri:** planın §8'indeki tam liste.
- **CLAUDE.md:** kural 12, §3, §5 ve §7 için metin (plan §11) planla birlikte onaylandı. 1. adımda
  kural 12 (geçiş cümlesiyle), §3, §5'in ilk kısmı ve §7 yazıldı; rol değiştirme cümlesi 9. adımda
  yazılır, geçiş cümlesi 8. adımda silinir.

## 2026-11-11 — Kişiye özel yetkiler: 1. adımın sahip kararları

- **Bağlam:** 1. adımın sözleşme testi (plan §5.5) iki yerde sahibin kararını istedi.
- **Panodaki bekleyen satın alma toplamı:** plandaki kural uygulanır ("plana uy"). 6. adımdan sonra
  yönetim panosunu açabilen ve Fiyatları görür'ü olan kişi de toplamı görür (ör. planlama ve satın
  alma rollerini birlikte taşıyan kişi). Gerekçe: bu kişi tutarları satın almada zaten görüyor.
  Plan §8'e ilk gün değişikliği olarak eklendi.
- **İzin listesinin planın eklediği kalemleri:** §5.5'in listesine, uç noktaların yanında planın
  eklediği iki kayıt türü (kişiye özel yetki ve paket sürümü) ve Sistem > Rol yetkileri sekmesi de
  girer. İki kayıt türü 1-5. adımlarda denetim günlüğünde bugünkü gibi yönetime de görünür (bu
  adımlarda yalnız paket sürümü kaydı yazılır), 6. adımdan sonra yalnız admine. Gerekçe: üçü de
  planın kendi getirdiği şeylerdir; sözleşme testi onları yeni fark olarak görür.
- **İzin listesinin yazımı:** liste 1. adımda bütün maddeleriyle yazıldı, hücre başına; yeni değeri
  plan sabitlemiyorsa açık bırakıldı ve adımı açılınca gözlenen değere sabitlenir (daraltmak onay
  istemez, genişletmek ister).

## 2026-11-12 — Partisi bitmemiş lot serbest bırakılamaz

- **Durum:** Bir dolum lotu, partisi bitmeden elle açılan son kontrol numunesiyle serbest
  bırakılabildi; içinde henüz ürün yokken karar verilmiş oldu. Parti sonra bitirilmek istenince
  sistem son kontrol numunesini serbest lota açamadığı için parti bitirilemiyordu.
- **Karar (CUMHUR, 2026-11-12, "Evet, engelle"):** Dolum partisinin ya da üretim şarjının açtığı
  lot için, parti (şarj) bitmeden:
  - lot serbest bırakılamaz: kalite kararıyla da, adminin elle serbest bırakmasıyla (D-5) da;
  - lota şarj sırası numunesi dışında numune açılamaz; son kontrol numunesi parti bitince
    kendiliğinden açılır;
  - lotu değiştiren kalite kararı (serbest, şartlı kabul, ret, yeniden işleme) verilemez. Kural
    yürürlüğe girmeden açılmış numune de karara gidemez.

  İptal edilen partinin (şarjın) lotu da serbest bırakılamaz; içinde ürün yoktur. Hata kodu
  `lot_output_unfinished`; mesaj lotu, emri ve partiyi söyler.
- **Açık kalan:** Lotu bloke etmek (laboratuvar) serbesttir. Kuraldan önce erken serbest bırakılmış
  bir lotta yol budur: lot bloke edilir, parti bitirilir, son kontrol numunesi açılır ve karar
  verilir.
- **Uygulama:** `inventory.services.register_output_check` / `unfinished_output`; dolum
  (`unfinished_run_reason`) ve üretim (`unfinished_batch_reason`) kendi denetimlerini `apps.py`'de
  kaydeder (bağımlılık yönü: depo modülü onları tanımaz). Denetimi `quality.open_sample`,
  kalite kararı ve `inventory.release_lot` kullanır.

## 2026-11-12 — Puantajda günlük çalışma saati ve yarım gün

- **İstek (CUMHUR):** "PUANTAJ KISMINA GÜNLÜK ÇALIŞMA SAATLERİNİ KAYDETMEMİZ GEREKİYOR. GÜNLÜK
  ÇALIŞMA SAATİNİ MANUEL BELİRLEYELİM SONRASINDA EKSİK GÖRÜNEN GÜNLERİ YARIM GÜN OLARAK KAYIT
  EDELİM". "Personel puantajı" kararında kapsam dışı bırakılan saat kaydı, toplam saat olarak
  kapsama girer.
- **Kararlar (CUMHUR, 2026-11-12, soruların yanıtları; plan için "Onaylıyorum, başla"):**
  - Kayıt biçimi: "Toplam saat". Güne tek sayı yazılır (ör. 9 ya da 4,5). Saat girilmeyen çalışılan
    gün standart saatle çalışılmış sayılır; yalnız farklı günler girilir. Fazla mesai bugünkü gibi
    ayrı alanda kalır.
  - Standart: "Tek değer, ayardan". Herkes ve her iş günü için aynı saat. Yönetim Personel > Tatil
    takvimi'ndeki ayara kendisi girer ve istediğinde değiştirir; onaylı aylar değişmez.
  - Yarım gün: "Sistem önersin, ben onaylayayım". Saat standardın altındaysa gün penceresinde
    "Yarım gün" işaretli gelir. İstenmeyen günde (ör. yarım saat erken çıkış) işaret kaldırılır;
    saat yine kayıtlı kalır.
  - Ücret: "Yarım günlük ücret kesilsin". Her yarım gün için günlük ücretin yarısı (brüt / 60)
    düşülür, pusulada ayrı satır olur. SGK günü değişmez; mali müşavirle teyit edilir. Kayıt
    kısmından sonra ayrı adım olarak yapılır.
- **Planla onaylanan, ayrıca sorulmayan kurallar** (değiştirilebilir):
  - Çalışılan saat yalnız çalışılan güne (Ç), bugün ya da geçmiş bir güne yazılır; 0'dan büyük ve en
    çok o günün çalışma saati kadardır. Fazlası fazla mesaidir.
  - Günün çalışma saati günlük çalışma saatidir; takvimde yarım gün tatil olan günde (arife, 28
    Ekim) yarısıdır.
  - Hiç çalışılmayan gün bugünkü durumlarla (D, Üİ, R, Yİ, Mİ) girilir; 0 saat yazılmaz.
  - Saati eksik güne fazla mesai girilmez.
  - Günlük çalışma saati belirlenmeden güne saat yazılamaz.
  - Kod YG ("Yarım gün çalıştı"). `½` ve `Ç½` yarım gün tatil anlamını korur. Toplamlarda ayrı YG
    sütunu vardır; Ç tam gün çalışılan günleri sayar; Eksik (Üİ + R + D) değişmez.
  - Yetki değişmez: yalnız admin ve yönetim.
  - Excel'e "Çalışma saatleri" sayfası, YG sütunu ve kod açıklaması eklenir; "Puantaj çizelgesi"
    (FR-IK-001) şablon sürümü 2 olur.
- **Tasarımda eklenen, sahibe ayrıca gösterilmeyen kurallar** (değiştirilebilir):
  - Yarım gün işaretini yalnız kullanıcı koyar; sunucu kendiliğinden yarım gün yazmaz. Öneri gün
    penceresindedir ("ben onaylayayım").
  - Girilen saat günün çalışma saatine eşitse saat kaydedilmez (tam gün). Kayıtlı saat her zaman
    "kaydedildiği gün eksikti" demektir.
  - Saati eksik güne "Öğleden sonra da çalıştı (yarım gün tatil)" işareti de girilmez.
  - Sayılma kuralı (Ç½ işaretindeki kural gibi): kayıtlı saat ve yarım gün işareti silinmez; ama
    tatil takvimi ya da günlük çalışma saati sonradan değişir ve kayıtlı saat artık günün çalışma
    saatinin altında kalmazsa o gün tam gün sayılır. Değişiklik geri alınırsa kayıt yeniden
    sayılır; gün yeniden kaydedilince kayıtlı saat temizlenir. Gerekçe: arifeler her yıl elle
    girilir; sonradan eklenen arife, o gün öğlene kadar çalışanı yarım gün bırakmamalıdır.
  - Günlük çalışma saati bir kez belirlendikten sonra boşaltılamaz, yalnız değiştirilir (boşalırsa
    saati girilmiş günler yeniden kaydedilemez).
  - Ay ilk onayında o anki günlük çalışma saatini alır ve yeniden açılınca da korur ("günler
    onaydaki haliyle kalır"); hiç onaylanmamış ay güncel ayarı kullanır. Bu karardan önce
    onaylanmış ay onaylıyken "kayıtlı değil" gösterir; yeniden açılınca güncel ayarı kullanır ve
    yeniden onayda onu alır.
  - Aralık girişi saat taşımaz: Ç kalan günün saati ve işareti korunur, başka duruma geçen günün
    saati ve işareti silinir.
  - Günlük çalışma saati yalnız puantajda kullanılır; bordrodaki brüt / 225, 7,5 saat ve 3,75 saat
    kuralları değişmez.
  - Bordrosu mali müşavirde olan kişilere de saat ve yarım gün girilebilir (puantaj tektir).
  - Gün kaydı tam değiştirir: istekte saat ya da işaret yoksa silinir. Güncellemeden sonra açık
    sekmeler yenilenmelidir.
- **İnceleme sonrası (2026-11-12, kod yazılmadan önce dört açılı tasarım eleştirisi):** planın
  "standart ya da tatil takvimi sonradan değişse de kayıtlı günler değişmez" cümlesi sayılma
  kuralıyla daraltıldı: kayıt değişmez, ama artık eksik olmayan gün yarım gün sayılmaz. Günlük
  çalışma saatinin boşaltılması, yeniden açılan ayın güncel ayara geçmesi, sunucunun yarım günü
  kendiliğinden yazması ve tam saatin sayı olarak saklanması tasarımdan çıkarıldı.
- **1. adımda bordro etkisi yok:** YG günü bordroda ve personel maliyetinde tam gün ödenir ve
  çalışılan gün sayılır. Ekranda, Excel'de ve kılavuzda bu yazar; 2. adımda kaldırılır.
  (2026-11-13: 2. adımla kalktı; YG günü bordroda ve personel maliyetinde yarım günlük ücret keser,
  çalışılan gün ve SGK günü değişmez; ekran, Excel ve kılavuz metinleri değişti. Bkz. "Bordroda
  yarım gün kesintisi (2. adım)".)
- **2. adım (yapılmadı):** karar verildi: yarım gün başına brüt / 60, pusulada ayrı satır, SGK
  günü değişmez. Açık kalan: kesintinin başlayacağı ay (sahibe sorulacak) ve mali müşavirin aynı
  kuralı uygulaması (karşılaştırma sayfası buna bağlı). (2026-11-13: yapıldı. Başlangıç sahibe
  soruldu: ayrı başlangıç ayı yok, bordrosu onaylanmamış bütün aylar; mali müşavire henüz
  sorulmadı, ilk karşılaştırmada teyit edilecek. Bkz. "Bordroda yarım gün kesintisi (2. adım)".)
- **Kapsam dışı:** giriş-çıkış saati, kişiye ya da güne göre standart, toplu saat girişi, yarım gün
  ücretli izin.
- **CLAUDE.md:** değişiklik gerekmedi.

## 2026-11-13 — Bordroda yarım gün kesintisi (2. adım)

- **İstek (CUMHUR, 2026-11-12, "Yarım günlük ücret kesilsin"):** puantajda yarım gün çalışılan (YG)
  her gün için günlük ücretin yarısı (brüt / 60) düşülür, pusulada ayrı satır olur, SGK günü
  değişmez; mali müşavirle teyit edilir. Kayıt kısmı 1. adımda yapıldı ("Puantajda günlük çalışma
  saati ve yarım gün"); bu adım kesintidir.
- **Kararlar (CUMHUR, 2026-11-13, soruların yanıtları; plan için "Onaylıyorum, başla"):**
  - Başlangıç: "Onaylanmamış bütün aylar (Önerilen)". Ayrı başlangıç tarihi ya da ayarı yoktur.
    Bordrosu onaylı olmayan her ay (açık, yeniden açılmış ve Ekim 2026'dan önceki personel maliyeti
    ayları) canlı hesapta kesintiyi alır; onaylı bordronun saklı satırları değişmez.
  - Mali müşavir: "Henüz sormadım, böyle ilerle (Önerilen)". Kural mali müşavirle ilk
    karşılaştırmada teyit edilecek (aşağıdaki sorular).
- **Eleştiri sonrası sorulan (CUMHUR, 2026-11-13):**
  - Arifede (yarım gün resmî tatil) YG: "Kesilsin, işaret bende (Önerilen)". Normal günle aynı
    kural, kesinti vardır. Gerekçe: öğleden sonrası zaten tatildir; günün çalışma saati yarıdır ve
    işareti kullanıcı verir (öğlene kadarki süreden az çalışılmışsa önerilir, istenmezse
    kaldırılır).
  - Takvimde hafta tatili ya da tam gün resmî tatil olan güne elle Ç yazılmış günde YG: "Kesilmesin,
    yalnız kayıt (Önerilen)". Kesinti yoktur; YG puantajda yine görünür. Gerekçe: o gün çalışılmasa
    da ücretlidir; yarım çalışan, hiç gelmeyenden az almamalıdır (tam gün resmî tatilde tatil ücreti
    çalışılmasa da ödenir, İş Kanunu m.47).
- **Hesap (planla onaylandı):**
  - Kesinti o günkü ücretle hesaplanır: yarım gün çalışılan her gün için 3,75 saat × saat ücreti (brüt / 225), yani
    günlük ücretin yarısı (brüt / 60). Aylık toplam tek kez yuvarlanır (yarım gün tatil ilavesinin
    aynası). Ücreti girilmemiş günde YG sayılır ama tutar yoktur.
  - Kesinti normal ücreti aşamaz (tavan). Brüt toplam = normal ücret − yarım gün kesintisi + fazla
    mesai ve tatil + ek ödemeler. SGK matrahı, vergiler, net, BES ve işveren maliyeti düşük brütten
    hesaplanır.
  - Normal ücret, ücretli gün, SGK günü ve fiilen çalışılan gün (nakit yemek istisnası dahil)
    değişmez: YG günü çalışılan gündür, eksik gün değildir. Excel'in "Eksik gün" sayfası değişmez.
  - Kesinti, sayılan YG'ye bağlıdır (1. adımın sayılma kuralı) ve günün takvim varsayılanı
    çalışılan gün olmalıdır: hafta tatili ve tam gün tatilde kesinti yoktur, arifede vardır.
    Bordrodaki YG sayısı "kesintiye giren YG günü"dür; puantajın YG toplamından az olabilir.
  - Bordrosu mali müşavirde olan kişide tutar hesaplanmaz (ERP tutarı kullanılmaz). ERP bordro
    çıktıları bu kişide YG sayısı ya da kesinti göstermez; mali müşavirin kaynağı puantaj Excel'idir
    (YG sütunu ve Kodlar açıklaması). Bordro listesi PDF'inde bu kişinin notuna "Puantajda n YG günü
    (yarım gün kesintisi mali müşavirce)" yazılır. Personel maliyeti bu kişide mali müşavir
    rakamından gelir, değişmez.
  - Sayılma kuralı yüzünden günlük çalışma saati ya da tatil takvimi değişince bordrosu
    onaylanmamış aylardaki kesinti de değişir (sonraki ayların kümülatif gelir vergisi matrahı
    dahil); onaylı aylar değişmez. Günlük çalışma saati girilene kadar YG olmadığı için kesinti de
    çıkmaz.
- **Örnekler (2026 değerleriyle, motorla hesaplandı):**
  - 45.000 TL, 1 YG: kesinti 750,00. 50.000 TL, 1 YG: 833,33.
  - Asgari ücret 33.030,00 TL, 1 YG: kesinti 550,50, brüt 32.479,50. SGK günü 30 kaldığı için
    matrah alt sınıra (33.030,00) çıkarılır; alt sınır farkının primini işveren öder (82,57; 5510
    m.82). Net 28.075,50'den 27.607,57'ye düşer (−467,93); işverene maliyet de 467,93 azalır
    (550,50 − 82,57). Gelir ve damga vergisi istisna yüzünden 0 kalır; BES (dahilse) alt sınırdan
    %3, 990,90. Yani asgari ücretlide YG, işverene göründüğünden az tasarruf sağlar.
  - Tavan: 31 çeken ay, tek ücret 45.000 TL, 29 gün devamsız + 2 YG: normal ücret 1.500,00, kesinti
    1.500,00, brüt 0, SGK günü 2; matrah alt sınıra çıkar ve işçi payı dahil primini işveren öder
    (alt sınır farkı 330,30). Tek ücretle kesinti normal ücreti aşmaz, bu uçta ona eşitlenir. Tavan
    yalnız ay içi zamda gerçekten keser (YG günleri 45.000, zamdan sonraki devamsız günler 46.000:
    normal ücret 1.468,82 < 1.500,00, kesinti 1.468,82). Sessizdir (uyarı yok).
- **Çıktılar:**
  - Etiketler: sayı "Yarım gün çalışılan (YG)", tutar "Yarım gün kesintisi" (pusula, icmal, Excel,
    döküm). "Yarım gün (YG)" kullanılmaz; yarım gün tatil ile karışır. Kısa biçim yalnız dar
    yerlerde: bordro listesi PDF'inde "YG −…" (açıklamada "YG: yarım gün kesintisi") ve ekran
    tablosunda "YG kesintisi". Kesinti kazançların içinde her yerde eksi gösterilir.
  - Pusula, bordro listesi ve icmal satırları koşulludur: kesinti satırı tutar 0 ise, YG gün
    satırı YG sayısı 0 ise yoktur. Bu yüzden
    önceki motorla (2026.2) onaylanmış ayların PDF'leri aynı kalır.
  - Ön bordro Excel'inin "Bordro" sayfasına "Yarım gün çalışılan (YG)" (Genel toplamda toplanır,
    para biçimi yok) ve "Yarım gün kesintisi (TL)" sütunları eklenir. Kesinti negatif yazılır ki
    Normal + YG + fazla mesai ve tatil + ek ödemeler = Brüt toplam tutsun. 2026.2 ile onaylanmış
    ayın yeniden basımında bu iki sütun yoktur (eski sütun düzeni aynen).
  - Puantaj Excel'inin Kodlar açıklaması (FR-IK-001, sürüm 2 kalır) her ay için doğru olacak
    biçimde yazıldı: kesinti bordrosu onaylanmamış aylarda yapılır, hafta tatili ve tam gün tatile
    Ç yazılan günde yapılmaz, bordrosu mali müşavirde olan kişide mali müşavir uygular.
  - "Ön bordro (bordro listesi)" (FR-IK-002) ve "Ücret hesap pusulası" (FR-IK-004) şablon
    sürümleri 2 olur; "İşveren maliyeti tablosu" (FR-IK-003) 1 kalır.
  - Karşılaştırma sayfası brüt toplamı karşılaştırır, değişmez. Mali müşavir kuralı uygulayana dek
    YG'li kişide brütte ve ondan hesaplanan tutarlarda fark çıkar; bu beklenir.
- **Personel maliyeti:** "Brüt ücret" = normal ücret − yarım gün kesintisi; brüt toplam ve toplam
  maliyet bordroyla aynı kalır. Sütun, API ve Excel düzeni değişmez; "Personel maliyeti" şablon
  sürümü artmaz. Kurallar listesinde YG maddesi vardır.
- **Mali müşavirle ilk karşılaştırmada teyit edilecek:**
  - Kural: YG başına günlük ücretin yarısı (brüt / 60), SGK günü değişmez.
  - (1) Mali müşavir iki YG'yi bir eksik gün olarak bildiriyor mu? Öyleyse SGK günü ve alt sınır
    ERP'den farklı olur.
  - (2) Aynı haftada YG ve fazla mesai: haftalık 45 saat mahsubu yapılıyor mu? ERP aynı günde
    engeller, aynı haftada engellemez.
- **Uygulama:** hesap motoru sürümü `2026.3`; `payroll.Day.short_day`, sonuçta `short_days` ve
  `short_day_deduction` (eski sürümle saklanmış satırlar 0 okunur). Köprü
  `personnel.selectors._month_input` yalnız kesintiye giren günü işaretler. Göç yoktur. Hesap
  satırına yeni alanlar eklendiği için güncellemeden önce açılmış onay penceresi bir kez "onay
  penceresi açıldıktan sonra değişti" der (`payroll_changed`); hesap yenilenip yeniden onaylanır.
- **CLAUDE.md:** değişiklik gerekmedi.

## 2026-11-14 — Dolum emrini geri alma

- **İstek (CUMHUR):** DO-2026-00008 ve DO-2026-00009 dolum emirleri sistemde başlatıldı, ama dolum
  fabrikada fiilen yapılmadı. Bugün başlamış emir iptal edilemiyor (yalnız kaydı olmayan parti
  iptal edilir); emirlerin stok hareketleri, partileri ve numuneleri geri alınmalı.
- **Kararlar (CUMHUR, 2026-11-14, soruların yanıtları; plan için "Onaylıyorum, başla"):**
  - Ne yapılacak: "Hiç yapılmadı, tamamen geri al (Önerilen)". Emrin bütün stok hareketleri ters
    kayıtla geri alınır: mamul stoktan düşer, tüketilen bulk kendi lotuyla tanka, tüketilen ve
    hazırlanan ambalaj depoya döner. Partiler ve açık numuneler iptal edilir, emir İptal olur.
    Kayıt silinmez.
  - Ambalaj: "Ambalaj malzemeleri depoya dönsün (Önerilen)". Hatta tüketilmiş görünen ambalaj önce
    hatta geri gelir, sonra hazırlık transferi ters kayıtla alındığı lokasyona döner.
  - Plan: yalnız admin ve yönetim yapar, neden zorunludur, tek işlemdir; mamul sevk edilmiş ya da
    başka yerde kullanılmışsa reddedilir. Yanıt: "Onaylıyorum, başla".
- **Kurallar:**
  1. Tek işlem: ya hepsi ya hiçbiri. Bütün denetimler ilk yazmadan önce yapılır; arada hata
     çıkarsa her şey geri alınır.
  2. Sıra (bakiye eksiye düşmesin): önce tüketim ve fire hareketleri (stok geri gelir), sonra
     bitmiş partilerin mamul girişi (çıktı lotu 0 olur), en son iade edilmemiş ambalaj
     hazırlıkları (hattan depoya; transferin iki bacağı birlikte). Hazırlığa iade zamanı yazılır.
     Daha önce elle ters kaydı yapılmış hareket atlanır; hazırlığa yine iade zamanı yazılır.
  3. Sonunda emre bağlı, ters kaydı olmayan bir hareket kalırsa işlem reddedilir
     (`unreversed_movement`) ve hiçbir şey değişmez.
  4. Parti iptali `filling_run.cancelled`, emir iptali `filling_order.cancelled` yayınlar; iş
     akışı emre bağlı açık görevleri iptal eder, planlamaya bildirim gider. Denetim günlüğüne
     neden ve ters kaydedilen hareket sayısı yazılır. Var olan "Partiyi iptal et" de artık
     `filling_run.cancelled` yayınlar (CLAUDE.md kural 5).
- **Reddedilen durumlar (hata kodları):**
  - Emir Ambalaj hazır, Dolumda ya da Analiz bekliyor değilse `order_not_revertible`; neden boşsa
    `cancel_reason_required`.
  - Çıktı lotu (iptal partilerinki dahil) için tek kural: lot serbest bırakılmışsa ya da lotta bu
    emrin kendi hareketleri ve onların ters kayıtları dışında hareket varsa (sevk, elle transfer,
    serbest bırakmadaki depo transferi, iade) `output_lot_used`. Serbest bırakılıp sonra bloke
    edilen lot da bu yüzden reddedilir. Başka hareketi olmayan karantina, bloke ya da red
    durumundaki lot kabul edilir.
  - Çıktı lotundan başka lot üretilmişse `output_lot_consumed`; lotta etkin rezervasyon varsa
    `output_lot_reserved`; lotun onay bekleyen numunesi varsa `sample_awaiting_approval`.
  - Ambalaj lotu aynı hatta başka bir emirde tüketildiği için geri çekilecek kadar stok hatta
    yoksa `packaging_used_elsewhere`; mesaj lotu, hattı ve önce geri alınması gereken emri söyler.
  - Stok alacak lokasyonlardan biri (tank, hat, mamul deposu, ambalajın alındığı yer) pasifse
    işlem bunu söyleyen mesajla reddedilir; önce lokasyon etkinleştirilir.
  - Geri çekilecek stok başka bir nedenle yoksa (ör. ambalaj hattan elle taşınmış) `negative_stock`.
  - İade edilmiş ambalaj hazırlığı olan emir geri alınmaz (`unreversed_movement`). Olağan akışta
    olmaz: hazırlık yalnız iptal edilen emirde iade edilir.
  - Ambalajı tüketen öteki emir geri alınamaz durumdaysa (ör. tamamlanmış) ileti onu geri almayı
    önermez; geri alma yapılamaz.
- **Tasarımda eklenen, sahibe ayrıca gösterilmeyen kurallar** (değiştirilebilir):
  - Ambalajı hazır (MATERIAL_READY) emir de geri alınabilir: partisi yoktur, yalnız ambalaj depoya
    döner. Bugün bu durumdaki emir hiç iptal edilemiyordu.
  - Serbest bırakılmış mamul lotu geri alınmaz (yukarıdaki tek kural).
  - Soy ağacı (`LotLink`) silinmez, geçmiş olarak kalır; ters kayıtlarla miktarlar net sıfırdır.
    İzlenebilirlikte çıktı lotu 0 stoklu, partisi iptal edilmiş lot olarak görünür.
  - Bulk lotlarının ve çıktı lotlarının durumu değişmez: çıktı lotu bulunduğu durumda (genellikle
    karantinada) 0 stokla kalır
    (iptal partinin lotu serbest bırakılamaz; bkz. "Partisi bitmemiş lot serbest bırakılamaz");
    bulk lotu bugünkü durumunda (ör. bloke) kalır.
  - Yetki ayrı bölümdür: Dolum > "Dolum emrini geri alma" (`filling.revert`, yalnız Değiştirir).
    Yönetim rol paketine verilir (paket yeni sürümle değişir), admin her zaman yapar. Kişiye özel
    yetkiyle başkasına da verilebilir; bölüm Dolum emirleri: Görür'ü ister. Planlamanın "Emri
    iptal et"i ve emir ile partinin durum tabloları değişmez; geri alma kendi tablosuyla ilerler.
  - Maliyet modülü değişmez: iptal parti maliyet raporlarından düşer, lot bakiyesi 0'dır.
- **İnceleme sonrası (2026-11-14, kod yazılmadan önce iki açılı tasarım eleştirisi):**
  - Aynı hatta iki emir aynı ambalaj lotunu kullandıysa geri alma sırası önemlidir; ön denetim
    eklendi (`packaging_used_elsewhere`). Canlıda önce DO-2026-00009, sonra DO-2026-00008 geri
    alınır.
  - Laboratuvarın "Mamul kontrolü: D-…" görevi geri almada kendiliğinden kapanır (`finished_qc`
    kuralı `filling_run.cancelled` ile de kapanır). Görev "tamamlandı" görünür; tamamlayan, geri
    almayı yapan kişidir.
  - Sözleşme testinin anlık görüntüsü (`endpoints.json`) yeniden yazılmaz. Yeni uç nokta
    `POST /api/v1/filling/orders/{id}/revert/` izin listesine 4. adımın kaydı olarak eklenir
    (anonim ve pasif kullanıcı 401; POST'ta admin, süper kullanıcı ve yönetim izinli, öteki
    roller 403; OPTIONS görünümün okuma iznini izler, giriş yapan herkese açık) ve bu karara
    bağlanır. Sahibin onayladığı plan bu uç noktayı tanımlar ("yalnız admin ve yönetim"); kayıt o
    onaya dayanır.
  - Ön yüzde düğme sunucunun verdiği `can_revert` alanına bağlıdır, rol denetimi yapılmaz;
    kişiye özel ayar düğmeye de yansır.
- **Önceki kayıtlara not:** "Dolum ve ambalaj (Faz 2, Adım 2.2)" kaydının parti iptali, yetki, olay
  sözleşmesi ve iş akışı maddelerine tarihli not düşüldü.
- **CLAUDE.md:** değişiklik gerekmedi.
