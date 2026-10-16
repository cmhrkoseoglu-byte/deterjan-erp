# İlerleme

## Faz 0 — Altyapı ve çekirdek

| Adım | Durum | Not |
|---|---|---|
| 0.1 Depo yapısı | Tamamlandı (2026-10-15) | Klasör yapısı, ayarlar (django-environ), `.gitignore`, `.env.example` |
| 0.2 Docker Compose | Tamamlandı (2026-10-15) | 7 servis, nginx tek origin, `GET /api/v1/health/` + testler |
| 0.3 `core` uygulaması | Tamamlandı (2026-10-15) | User/roller, BaseModel/MasterDataModel/DocumentModel, AuditLog, belge numarası, olaylar, durum makinesi, `seed_roles`, `create_demo_users` |
| 0.4 API temeli | Tamamlandı (2026-10-15) | DRF ayarları, auth uç noktaları, `users`, `audit-log`, `/api/schema/`, `/api/docs/` |
| 0.5 Frontend iskeleti | Tamamlandı (2026-10-15) | React + TS + Mantine iskeleti, giriş, role göre menü, Türkçe biçimler; gerçek backend ile uçtan uca denendi |
| 0.6 Kalite araçları ve CI | Tamamlandı (2026-10-15) | pre-commit, servis katmanında zorunlu tip ipucu, GitHub Actions (backend, frontend, Docker Compose duman testi), README ve CLAUDE.md §9 |

### Adım 0.2 doğrulaması

- `docker compose up -d` ile 7 servis ayağa kalktı; backend, db, redis sağlık kontrolleri yeşil.
- `http://localhost/api/v1/health/` → 200 `{"status":"ok","db":"ok","redis":"ok"}`; Redis durdurulunca 503.
- `http://localhost/` frontend yer tutucusu, `/admin/` ve admin statik dosyaları nginx üzerinden açılıyor.
- `pytest` 4 test geçti; `ruff check`, `ruff format --check`, `mypy` temiz.

### Adım 0.3 ve 0.4 doğrulaması

- `pytest` 142 test geçti (konteynerde `docker compose exec backend pytest` dahil); `ruff check`,
  `ruff format --check`, `mypy` temiz; OpenAPI şeması uyarısız üretiliyor.
- Kabul kriterleri: 20 eşzamanlı `next_document_number` çağrısı tekrarsız
  (`test_document_number_concurrent_calls_are_unique`); test modeliyle oluşturma/güncelleme eski/yeni
  değerlerle günlükte (`test_save_with_audit_*`); geri alınan transaction'da handler çağrılmıyor
  (`test_handler_not_called_when_transaction_rolls_back`); yasak geçişte `BusinessRuleError`
  (`test_forbidden_transition_raises_business_rule_error`); yetkisiz rol 403
  (`test_users_list_forbidden_for_other_roles` ve diğerleri).
- `docker compose up` sonrası nginx üzerinden: `migrate`, `seed_roles`, `create_demo_users`;
  demo kullanıcıyla `csrf → login → me → logout` akışı, `/api/docs/` 200, giriş sınırı (sahte
  `X-Forwarded-For` ile de) 10 denemeden sonra 429.
- Bağımsız bir kod incelemesi yapıldı (5 açıdan, her bulgu ikinci bir gözle doğrulandı); doğrulanan
  bulgular düzeltildi ve her biri için test eklendi.

### Kurulumdan sonra (geliştirme)

```bash
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py seed_roles
docker compose exec backend python manage.py create_demo_users   # şifre: .env DEMO_USER_PASSWORD
```

Demo kullanıcı adları rol kodlarıdır: `admin`, `yonetim`, `planlama`, `depo`, `uretim`,
`laboratuvar`, `dolum`, `sevkiyat`, `satin_alma`. `admin` yönetim paneline de girer.

- **Adım 0.3'ten önce `migrate` çalıştırmayın.** Özel `User` modeli (`AUTH_USER_MODEL = "core.User"`)
  ilk migration'dan önce tanımlanmalı. Yanlışlıkla çalıştırıldıysa: `docker compose down -v`.

### Adım 0.5 doğrulaması

- `npm test` 25 test geçti (biçimler, role göre menü, giriş/çıkış/yönlendirme, 401'de oturum düşürme,
  açılışta CSRF, `csrf_failed` sonrası yenileyip tekrar deneme, 403 ve 404 sayfaları). Tipler DECISIONS.md'deki auth sözleşmesine göre yazıldı.
- `npm run lint`, `npm run format:check`, `npm run typecheck`, `npm run build` temiz.
- 390, 768 ve 1280 px genişlikte ekran görüntüsüyle kontrol edildi (sahte API ile); 768 px ve üstünde
  menü sabit, altında hamburger menü.
- Gerçek backend ile uçtan uca denendi (Adım 0.3–0.4 dalı + bu frontend, `docker compose up`, demo
  kullanıcılar): `/depo` → giriş ekranına yönlendirme, hatalı şifrede backend mesajı, `depo` girişinde menü
  yalnızca Görevlerim + Depo ve stok, `/kalite` → "Yetkiniz yok", çıkış sonrası `me` 401, `admin` tüm menüyü
  görüyor, sayfa yenilenince oturum korunuyor.

### Adım 0.6 doğrulaması

- `pre-commit run --all-files` temiz (ruff lint + biçim, Prettier, ESLint, YAML/TOML/JSON, büyük dosya,
  gizli anahtar kontrolleri). ruff sürümü `backend/pyproject.toml` ve `.pre-commit-config.yaml`'da 0.17.0'a sabit.
- `mypy`: `services.py`, `selectors.py`, `state.py` için tip ipucu zorunlu; tip ipucusuz bir fonksiyon
  eklenince hata verdiği denendi.
- `scripts/smoke_test.sh` yerelde `docker compose up` üzerinde geçti; yanlış şifreyle çalıştırılınca
  "depo girişi başarısız" diye düşüyor.
- Tarayıcıyla (Playwright) giriş: `depo` menüsü Görevlerim + Depo ve stok, `admin` tüm menü.

## Faz 0 kabul kriterleri

| Kriter | Durum | Kanıt |
|---|---|---|
| `docker compose up` sonrası `/` giriş ekranı, `/api/docs/` çalışıyor | ✓ | CI duman testi (`scripts/smoke_test.sh`) |
| Demo kullanıcılarla giriş; menü role göre değişiyor | ✓ | Duman testi (giriş + `me` rolleri), frontend testleri (`menu.test.ts`), tarayıcı denemesi |
| `next_document_number` 20 eşzamanlı çağrıda tekrarsız | ✓ | `test_document_number_concurrent_calls_are_unique` |
| Oluşturma/güncelleme `AuditLog`'a eski/yeni değerlerle | ✓ | `test_save_with_audit_*` |
| `core.events`: geri alınanda handler yok, commit'te var | ✓ | `test_handler_not_called_when_transaction_rolls_back`, `test_handler_called_after_commit` |
| `StateMachine` yasak geçişte `BusinessRuleError` | ✓ | `test_forbidden_transition_raises_business_rule_error` |
| Yetkisiz rol 403 | ✓ | `test_users_list_forbidden_for_other_roles` vb., duman testinde `depo` → `/api/v1/users/` 403 |
| CI yeşil; `ruff check`, `ruff format --check`, `mypy` temiz | ✓ | GitHub Actions `CI` iş akışı |
| `docs/PROGRESS.md` güncel | ✓ | Bu dosya |

## Faz 1 — Ana veriler, reçete, stok/lot, üretim ve iş akışı

| Adım | Durum | Not |
|---|---|---|
| 1.1 `masterdata` | Tamamlandı (2026-10-15) | Birim, kategori, malzeme, malzemeye özel dönüşüm, depo, lokasyon, ekipman, tedarikçi, müşteri; `convert_quantity`; Excel/CSV içe aktarma (önizleme + onay) ve şablonlar; API ve ekranlar |
| 1.2 `recipes` | Tamamlandı (2026-10-15) | Sürümlü reçete, satır, proses adımı; onay (tek onaylı sürüm, eskisi geçersiz), kopyalama, ölçekleme; API ve ekranlar (sürüm karşılaştırma dahil) |
| 1.3 `inventory` | Tamamlandı (2026-10-15) | Lot, değişmez hareket defteri, bakiye, lot soy ağacı (geri/ileri), mal kabul (karantina → lot onay), transfer, ters kayıt, sayım düzeltme, açılış stoku içe aktarma, lot etiketi (PDF), SKT ve minimum stok kontrolleri; API ve ekranlar |
| 1.4 `production` | Tamamlandı (2026-10-15) | Üretim emri (taslak → onay → malzeme hazırlama → hazır → üretim → analiz bekliyor → tamam), reçete ölçekleme, lot okutarak malzeme hazırlama (FEFO önerisi), şarja bölme (D-4), tartım ve tolerans/sapma, şarj bitişi ve verim, çıktı lotu serbest kalınca emrin kapanması; API ve ekranlar |
| 1.5 `workflow` (+ 1.6 API, 1.7 ekranlar) | Tamamlandı (2026-10-15) | Görev, bildirim, yorum; 11 satırlık kural tablosu; WebSocket + 30 sn yoklama; 07:00 zamanlaması; Görevlerim, bildirim zili, Bildirimler sayfası, kayıt yorum paneli |
| 1.6 API | Tamamlandı (2026-10-15) | `/api/v1/masterdata/…`, `/api/v1/recipes/…`, `/api/v1/inventory/…`, `/api/v1/production/…`, `/api/v1/workflow/…` |
| 1.7 Ekranlar | Tamamlandı (2026-10-15) | Ana veriler (sekme başına liste + form + içe aktarma), Reçeteler, Depo (stok sorgu, lotlar, mal kabul, lot onay, sayım; lot detayı ve soy ağacı), Üretim (emirler, malzeme hazırlama tableti, şarj/tartım tableti), Görevlerim, Bildirimler |
| 1.8 Demo verisi ve uçtan uca test | Tamamlandı (2026-10-15) | `seed_demo` (15 hammadde, 2 bulk ürün, onaylı 2 reçete, 2 tank, lokasyonlar, 3 tedarikçi, açılış stoku); `apps/production/tests/test_e2e_production.py` |

### Adım 1.1 ve 1.2 doğrulaması

- `pytest` 285 test geçti (masterdata ve recipes için 143 yeni test); `ruff check`, `ruff format --check`,
  `mypy` temiz; OpenAPI şeması uyarısız.
- Kabul kriteri "onaylı reçete sürümü değiştirilemiyor; kopyalanıp yeni sürüm onaylanınca eski sürüm
  OBSOLETE": `test_new_approval_makes_previous_obsolete`, `test_approved_version_cannot_be_changed`,
  `test_approve_copy_and_obsolete_flow` (API).
- Kabul kriteri "malzeme Excel'den önizlemeli içe aktarılabiliyor": `test_preview_reports_row_errors_and_writes_nothing`,
  `test_run_import_with_errors_writes_nothing`, `test_import_preview_then_confirm` (API),
  `test_template_round_trip_is_valid` (indirilen şablon hatasız geçer). Açılış stoku içe aktarma Adım 1.3'te eklendi.
- Karar D-1: `test_water_is_an_ordinary_stocked_ingredient`.
- Durum makinesi: izinli tüm geçişler ve yasak geçişler (`test_state_machine_*`). Yetkisiz rol 403
  (`test_other_roles_cannot_write`, `test_write_endpoints_forbidden_for_other_roles`,
  `test_approve_forbidden_for_other_roles`).
- Frontend: `npm test` 47 test, `lint`, `format:check`, `typecheck`, `build` temiz.
- Tarayıcıyla (Playwright, gerçek backend) `planlama` kullanıcısıyla denendi: hatalı Excel önizlemede satır
  hataları ve kapalı "aktar" düğmesi, düzeltilmiş dosyayla 7 malzemenin aktarımı, depo → tank lokasyonu →
  tank (lokasyonsuz tank kuralı formda görünüyor), reçete → sürüm → satırlar (su işaretli) → ölçekleme →
  onay → kopyala → değiştir → v1 ile karşılaştır → v2 onayı → v1 "Geçersiz". 768 px genişlikte kontrol edildi.

### Adım 1.3 doğrulaması

- Backend: `pytest` 451 test geçti (inventory: 83); `ruff check`, `ruff format --check`, `mypy` temiz;
  OpenAPI şeması uyarısız.
- Stok değişmezleri: stoka dokunan her inventory testi `assert_stock_invariants()` ile biter
  (bakiye = hareket toplamı, negatif bakiye yok, tüketen her hareketin lot bağı var).
- Değişmez defter: `StockMovement`/`LotLink` güncelleme ve silme hem ORM'de hem ham SQL'de reddediliyor
  (tetikleyici testleri). Negatif stok, serbest olmayan lot, SKT'si geçmiş lot kural ihlali testleri var.
- Durum makineleri (lot, mal kabul, sayım): izinli tüm geçişler ve yasak geçişler testli. API testleri
  yetkisiz rolün 403 aldığını doğruluyor (depo dışı stok yazımı, laboratuvar dışı lot kararı).
- Soy ağacı: çok seviyeli geri ve ileri izleme testleri (`lot_trace`).
- Açılış stoku: hatalı satırda hiçbir şey yazılmıyor; önizleme + onay ve şablon sütunları testli.
- İş akışı: `goods_receipt.posted` ile laboratuvara giriş kontrolü görevi açılıyor, lot kararıyla
  kapanıyor; `system.daily_check` SKT ve minimum stok olaylarını yayınlıyor.
- Frontend: `npm test` 78 test (depo: 9), `lint`, `format:check`, `typecheck`, `build` temiz.

### Adım 1.5 doğrulaması

- Backend: `pytest` 225 test geçti (workflow: 83); `ruff check`, `ruff format --check`, `mypy` temiz;
  OpenAPI şeması uyarısız. Frontend: 46 Vitest testi, lint, biçim, tip denetimi ve derleme temiz.
- Kural tablosunun her satırı için açılış ve kapanış testi (`apps/workflow/tests/test_rules.py`); olaylar
  doğrudan yayınlanıyor, lot/emir yerine test modeli kullanılıyor. Stok ve Üretim adımları olayları
  DECISIONS.md'deki sözleşmeyle yayınlayacak.
- Görev durum makinesi: izinli tüm geçişler ve kapalı görevde yasak geçiş testli. API testleri giriş
  yapılmamışsa 401, başka rolün görevinde 404/403 durumlarını içeriyor.
- WebSocket: `test_websocket_receives_new_notification` (gerçek ASGI uygulaması, oturum çereziyle).
  Tarayıcıda (Playwright, 768 px) uvicorn + Vite ile denendi: `depo` girişinden sonra yayınlanan
  `production_order.approved` olayının görevi ve bildirimi sayfa yenilemeden düştü; üstlenme çalıştı;
  `production_order.material_ready` ile görev kendiliğinden kapanıp listeden kalktı.
- 07:00 kontrolü zamanlandı (`CELERY_BEAT_SCHEDULE`); SKT ve minimum stok sorguları Adım 1.3'te
  `system.daily_check` olayına bağlandı.

### Adım 1.4 ve 1.8 doğrulaması

- Backend: `pytest` 528 test geçti (production: 76); `ruff check`, `ruff format --check`, `mypy` temiz;
  OpenAPI şeması uyarısız. Stoka dokunan her üretim testi `assert_stock_invariants()` ile biter.
- Uçtan uca: `test_goods_receipt_to_completed_order` mal kabul → lot onay → emir → onay → hazırlama →
  malzeme hazır → şarj → tartım → bitiş → çıktı lotu onayı → emir tamam zincirini; her adımda açılan ve
  kapanan görevleri, bildirimleri ve geri/ileri izlemeyi doğrular. `test_split_order_two_batches_low_yield_and_completion`
  (D-4, düşük verim bildirimi), `test_cancelled_order_cancels_open_tasks`, `test_events_follow_contract`.
- Durum makineleri (emir, şarj): izinli tüm geçişler ve yasak geçişler testli. API testleri her yazma
  ucunda yetkisiz rolün 403 aldığını doğrular (emir planlama, hazırlama depo, şarj üretim).
- Frontend: `npm test` 89 test (üretim: 11), `lint`, `format:check`, `typecheck`, `build` temiz.
- Tarayıcıda (Playwright, 768 px, uvicorn + Vite, `seed_demo` verisi) tam akış denendi: planlama 3.000 kg
  emir açıp onayladı; depo yanlış lot okutunca hata gördü, 9 satırı öneriden hazırlayıp "Malzeme hazır"
  dedi; üretim 2.000 kg'lık ilk şarjı başlattı (emirde 1.000 kg kaldı), suyu %5 fazla tartınca sapma notu
  istendi, tüm satırları tartıp şarjı bitirdi. Bu denemede hesaplanan miktarların JSON'da sayı döndüğü
  bir hata bulundu ve düzeltildi (artık metin, test eklendi).

## Faz 1 kabul kriterleri

| Kriter | Durum | Kanıt |
|---|---|---|
| Uçtan uca test yeşil; stok testlerinden sonra `assert_stock_invariants()` geçiyor | ✓ | `test_e2e_production.py` (4 test); stok testleri değişmez denetimiyle biter |
| Negatif stoka düşürecek tartım reddediliyor | ✓ | `test_consumption_cannot_go_negative` |
| Karantinadaki lot hazırlamada seçilemiyor (test + arayüz) | ✓ | `test_quarantine_lot_cannot_be_picked`, `test_quarantine_lot_scan_is_rejected` (API); öneri listesi yalnızca serbest stok gösterir; okutma hatası ekranda (Vitest "karantinadaki lot okutulunca hatayı gösterir") |
| Onaylı reçete sürümü değiştirilemiyor; yeni sürüm onaylanınca eski OBSOLETE | ✓ | Adım 1.2 testleri (yukarıda) |
| Bulk lotun geri izlemesi hammadde lotlarını miktarlarıyla, hammadde lotunun ileri izlemesi şarjları gösteriyor | ✓ | `test_goods_receipt_to_completed_order` (iki yönde `lot_trace`); ekran: lot detayındaki soy ağacı (Adım 1.3) |
| Görevler kural tablosuna göre açılıp kapanıyor | ✓ | `apps/workflow/tests/test_rules.py` (her satır) ve uçtan uca test |
| Yeni görev WebSocket ile sayfa yenilemeden düşüyor | ✓ | `test_websocket_receives_new_notification`; tarayıcı denemesi (Adım 1.5) |
| Malzeme ve açılış stoku Excel'den önizlemeli içe aktarılıyor | ✓ | Adım 1.1 ve 1.3 testleri |
| Tablet ekranları (hazırlama, tartım) 768 px'te rahat kullanılıyor | ✓ | Playwright denemesi (yukarıda); büyük dokunma alanları, okutma kutusunda Enter ile kayıt |
| `docs/PROGRESS.md` ve `docs/DECISIONS.md` güncel | ✓ | Bu dosya ve DECISIONS.md "Üretim (Adım 1.4)" |

## Faz 2 — Kalite, dolum, etiket ve ekler

Plan: `docs/plan/FAZ-2-kalite-dolum.md`. Kararlar D-5…D-8 ve Adım 2.1 ayrıntıları `docs/DECISIONS.md`
"Kalite kontrol (Faz 2, Adım 2.1)"; Adım 2.2 ayrıntıları "Dolum ve ambalaj (Faz 2, Adım 2.2)".

### Adım 2.1 doğrulaması (kalite kontrol)

- Backend: `pytest` 596 test geçti (quality: 55, yeniden işleme: 4); `ruff check`, `ruff format --check`,
  `mypy` temiz; OpenAPI şeması uyarısız; `makemigrations --check` temiz. Kalite testlerinin hepsi
  `assert_stock_invariants()` ile biter (autouse fixture).
- Kurallar: `test_decision_requires_all_mandatory_tests`, `test_out_of_spec_result_blocks_release`,
  şartlı kabul onay/ret, REWORK'ün lotu bloke edip planlamaya görev açması, IN_PROCESS numunenin lotu
  değiştirmemesi, sonuç düzeltme geçmişi, spesifikasyon sürümleri ve kilidi; numune ve spesifikasyon durum
  makinelerinin izinli tüm geçişleri ve yasak geçiş.
- Lot kararı yalnızca kalite kararıyla: `test_release_and_reject_only_through_quality_decision`,
  `test_admin_manual_release_requires_reason_and_is_audited` (D-5), `test_manual_release_is_admin_only`,
  `test_reject_endpoint_removed`.
- Otomatik numune ve görev: mal kabulde giriş numunesi + "Giriş kontrolü" görevi (inventory testleri),
  şarj bitişinde son numune + "Numune analizi" görevi (`test_e2e_production.py`, lot artık kalite
  kararıyla serbest bırakılıyor).
- Yeniden işleme (`apps/production/tests/test_rework.py`): düzeltme listesiyle ve reçeteyle harmanlama,
  sabit lotun hazırlanamaması, bloke olmayan lotun reddi, soy ağacında eski lot, yeniden işleme emri
  bitince asıl emrin tamamlanması.
- CoA: `test_coa.py` (içerik satırları, şartlı kabul gerekçesi ve onaylayan), API'de `coa.pdf` PDF döner;
  karar verilmemiş numunede 400.
- API: her yazma ucunda yetkisiz rol 403 (laboratuvar dışı), şartlı kabul onayı yalnızca yönetim.
- D-7: `seed_quality_demo` 16 onaylı örnek spesifikasyon yazar (`test_seed.py`).
- Frontend: `npm test` 102 test (kalite: 10, yeniden işleme formu: 2), `lint`, `format:check`,
  `typecheck`, `build` temiz.
- Tarayıcıda (Playwright, 1024 ve 768 px, uvicorn + Vite, `seed_demo` verisi): SLES mal kabulünde açılan
  numune kuyrukta göründü; aktif madde 66,5 girilirken kırmızıya döndü, kaydedilince "Spesifikasyon dışı"
  işaretlendi; "Serbest bırak" kapalıydı, şartlı kabul gerekçeyle verildi; yönetim onaylayınca lot
  serbest oldu ve CoA PDF'i indi; lot detayında numune listelendi, laboratuvara yalnızca "Bloke et"
  göründü. Bu denemede otomatik numunede "numuneyi alan" boş kalıyordu; artık ilk sonucu girenle doluyor.

### Faz 2 kabul kriterleri (Adım 2.1, 2.3 ve 2.4'e düşenler)

| Kriter | Durum | Kanıt |
|---|---|---|
| Spec dışı sonuçla `RELEASE` verilemiyor; zorunlu test eksikken karar verilemiyor | ✓ | `test_out_of_spec_result_blocks_release`, `test_decision_requires_all_mandatory_tests`, API `test_decision_errors_return_codes` |
| Mal kabul ve şarj bitişinde numune otomatik açılıyor, laboratuvara görev düşüyor | ✓ | inventory mal kabul testi, `test_goods_receipt_to_completed_order`, `test_rules.py` numune kuralları |
| CoA PDF'i doğru bilgilerle üretiliyor | ✓ | `test_coa.py`, `test_sample_flow_via_api` |
| Lot etiketi PDF ve ZPL üretiliyor; okutma bileşeni tüm tablet ekranlarında çalışıyor | ✓ | `test_lot_label_pdf_a4_zpl`; `ScanInput` depo, üretim hazırlama ve tartım, dolum hazırlama ve hat ekranlarında (`components.test.tsx`, `production.test.tsx`, `filling.test.tsx`) |
| Stok değişmezleri tüm yeni testlerde geçiyor | ✓ | quality ve rework testleri `assert_stock_invariants()` ile biter |

### Adım 2.2 doğrulaması (dolum ve ambalaj)

- Backend: `pytest` 659 test geçti (filling: 56); `ruff check`, `ruff format --check`, `mypy` temiz;
  OpenAPI şeması uyarısız; `makemigrations --check` temiz. Stoka dokunan dolum testleri
  `assert_stock_invariants()` ile biter.
- Ortak hazırlama servisi (`inventory.picking`): üretim testleri değişmeden geçti; dolum aynı kuralları
  kullanır (`test_pick_rules`: karantina lot, yanlış malzeme, iki katı aşan hazırlama, yetkisiz rol).
- Servis testleri (`apps/filling/tests/test_services.py`): üç durum makinesinin izinli ve yasak geçişleri;
  ambalaj reçetesi sürümü ve kilidi; onayda fire payı ve adet yuvarlaması (şişe 1020, koli 85); hazırlamada
  fire payı hariç ihtiyaç; iptalde geri transfer; D- lotunun karantinada açılması; bulk tüketimi ve
  `LotLink`; yanlış malzeme / hat başında olmayan lot; üç tür fire; bitişte ambalaj tüketimi, mamul girişi,
  `FINAL` numune; eşik üstü `filling.bulk_variance`; mamul lotu serbest kalınca emrin tamamlanması; rapor.
- API testleri: her yazma ucunda yetkisiz rol 403 (planlama / depo / dolum ayrımı), okutma ile hazırlama
  (`LOT:` önekli etiket içeriği dahil), tablet akışı, rapor.
- İş akışı: yeni yedi kural `test_rules.py` içinde.
- Demo verisi: `seed_filling_demo` (seed_demo sonunda) 6 ambalaj malzemesi, 2 mamul (koli / palet
  dönüşümüyle), DH-01 dolum hattı, AMB-DEPO / DOLUM-1 / MAMUL-DEPO, onaylı ambalaj reçeteleri, mamul `FINAL`
  spesifikasyonları ve ambalaj açılış stoku yazar (`test_seed_demo.py`).
- Frontend: `npm test` 113 test (dolum: 11), `lint`, `format:check`, `typecheck`, `build` temiz. Ekranlar:
  dolum emirleri, emir detayı (ihtiyaç, hazırlanan lotlar, partiler, rapor), ambalaj hazırlama tableti,
  dolum hattı tableti (bulk lot seçimi / okutma, ambalaj lotu okutma, hızlı fire düğmeleri, parti bitişi),
  ambalaj reçeteleri.

### Faz 2 kabul kriterleri (Adım 2.2'ye düşenler)

| Kriter | Durum | Kanıt |
|---|---|---|
| Uçtan uca: bulk lot serbest → dolum emri → ambalaj hazırlama → dolum (fire dahil) → mamul QC → mamul lot serbest | ✓ | `apps/filling/tests/test_e2e_filling.py` (üretim emri iki şarja bölünür, iki bulk lottan dolum; görev, bildirim ve stok değişmezleri her adımda) |
| Mamul lotunun geri izlemesi: bulk lotlar + ambalaj lotları + bulkun hammadde lotları | ✓ | aynı test, adım 7 (`lot_trace_backward` çok seviyeli ağaç; ileri izlemede hammadde → mamul iki seviye) |
| Teorik / gerçek bulk ve ambalaj tüketim raporu doğru | ✓ | `test_consumption_report`, e2e adım 8, API `test_filling_tablet_flow` |
| Stok değişmezleri tüm yeni testlerde geçiyor | ✓ | dolum testleri `invariants` fixture'ı ya da `assert_stock_invariants()` ile biter |
| Okutma bileşeni tüm tablet ekranlarında | ✓ | Dolum tabletleri de ortak `ScanInput` kullanır (Adım 2.3, aşağıda) |

### Adım 2.3 ve 2.4 doğrulaması (etiket, barkod ve ekler)

- Backend: `pytest` 632 test geçti (dolumla birleşince 695) (etiket ve okutma: 27, ekler: 8); `ruff check`, `ruff format --check`,
  `mypy` temiz; OpenAPI şeması uyarısız; `makemigrations --check` temiz.
- D-6: `test_case_label_is_gs1_128_when_material_has_gtin` (ZPL mod D, `(01)…(17)…(10)…`),
  `test_case_label_without_gtin_uses_internal_code`, `test_pallet_label_requires_gs1_prefix`,
  `test_label_settings_and_sscc` (18 haneli SSCC, kontrol hanesi, seri artışı).
- D-8: `test_render_zpl_uses_203_dpi_dots_and_utf8` (100 × 150 mm = 799 × 1199 nokta, `^CI28`),
  `test_render_zpl_barcode_fits_its_width`, `test_render_pdf_label_and_a4`, lot/mal kabul/lokasyon
  etiketlerinin PDF, A4 ve ZPL çıktıları.
- Yazıcı: sahte TCP yazıcıyla (`fake_printer`) deneme etiketi, lot, koli, mal kabul ve lokasyon etiketi
  gönderimi; ulaşılamayan ya da pasif yazıcıda hata kodu; yazıcıyı yalnızca admin tanımlar.
- Okutma: `test_scan_prefixes` (`LOT:`, `LOC:`, `MAT:`, düz lot no), `test_scan_gs1_case_and_pallet`
  (AIM öneki, GS ayırıcısı, SSCC), `test_parse_gs1_rejects_malformed`, anonim 401.
- Ekler: lot, mal kabul, numune ve yoruma yükleme, listeleme, oturumla indirme, gerekçeli kaldırma;
  yasak uzantı, boyut, bilinmeyen kayıt türü, başkasının yorumu ve başkasının ekini kaldırma reddedilir.
- Frontend: `npm test` 114 test (dolumla birleşince 128) (okutma alanı: 4 + hazırlamada yanlış malzeme; ek paneli: 2; etiket
  penceresi: 2; yazıcı ve etiket ayarları: 3), `lint`, `format:check`, `typecheck`, `build` temiz.
- Tarayıcıda (Playwright, 768 px, uvicorn + Vite, `seed_demo` verisi, 9100'de sahte yazıcı): admin GS1
  önekini girdi, "SSCC palet etiketi açık" göründü; yazıcı tanımlandı, deneme etiketi ve lokasyon
  etiketi yazıcıya ulaştı; depo kullanıcısı `LOT:ACILIS-KORUYUCU` okutunca lot detayı açıldı, lot
  etiketi PDF olarak indi (200, application/pdf) ve yazıcıya gitti, analiz sertifikası eklendi;
  tanınmayan kodda kırmızı hata göründü. Bu denemede 3 nokta yuvarlanan dar çubuğun ZPL barkodunu 1,6 mm
  taşırdığı görüldü; artık çubuk genişliği alana sığacak şekilde seçiliyor.
- Dolumla birleştirme (PR #10 sonrası): dolum ambalaj hazırlama, bulk tüketimi, ambalaj lotu okutma ve
  fire lotu `ScanInput` kullanır (beklenen malzeme: hazırlamada satırın malzemesi, bulkta bulk ürün,
  ambalajda reçetedeki kalemler); yanlış malzeme sunucuya gitmeden kırmızı uyarı verir, sunucunun reddi
  okutma alanında gösterilir. Parti ekranında "Koli etiketi" düğmesi çıkan mamul lotunun koli etiketini
  (D-6, `finished_product_gtin`) önce seçili açar. Testler: `filling.test.tsx` (hazırlamada yanlış
  malzeme, ambalaj okutma, reçete dışı ambalaj, koli etiketi), `test_filling_tablet_flow`.
- Satışla birleştirme (PR #11 sonrası): göçler `masterdata/0004_labels_printers` ve
  `inventory/0004_pallet_labels` olarak yeniden numaralandı (satışın 0003'lerinden sonra). `pytest` 749,
  `npm test` 136 test geçti; `makemigrations --check` temiz.
- İade ve izlenebilirlikle birleştirme (PR #12 sonrası): çakışmasız; `pytest` 787, `npm test` 148 test geçti.


## Faz 3 — Satış siparişi, sevkiyat ve izlenebilirlik

Plan dosyası: `docs/plan/FAZ-3-satis-sevkiyat.md`. Kararlar D-9 (fiyat bu sistemde, fatura muhasebede),
D-10 (her sevkiyat tek siparişe bağlı), D-11 (müşteri bazında asgari kalan raf ömrü) `docs/DECISIONS.md`'de.

### Adım 3.1 doğrulaması (satış siparişi ve rezervasyon)

- Backend: `pytest` 713 test geçti (sales: 45, inventory rezervasyon: 9); `ruff check`, `ruff format
  --check`, `mypy` temiz; OpenAPI şeması uyarısız; `makemigrations --check` temiz. Stoka dokunan satış
  testleri `invariants` fixture'ı ile `assert_stock_invariants()` çağırır.
- Rezervasyon (`apps/inventory/tests/test_reservations.py`): kullanılabilir = bakiye − aktif rezervasyon;
  aynı stok iki kez rezerve edilemez; karantina, SKT'si geçmiş lot ve karantina lokasyonu rezerve edilmez;
  rezerve stok üretime çıkış, transfer, fire ve sevkiyatla eritilemez, sayım düzeltmesi engellenmez;
  bırakma; tam ve kısmi kullanma (bölme); toplama önerileri rezerve stoğu atlar.
- Satış servisleri (`apps/sales/tests/test_services.py`): adet / koli / palet çevrimi; yalnızca mamul;
  taslakta satır eşitleme ve onaydan sonra kilit; para birimi bazında toplam (D-9); onayda FEFO
  rezervasyonu ve sevkiyata görev; rezerve stoğun başka siparişe ayrılmaması; eksikte planlamaya görev ve
  tamamlanınca görevin kapanması; D-11 raf ömrü (istenen teslim tarihine göre); elle lot seçimi ve bırakma;
  iptal ve kapanışta rezervasyonların bırakılması; bloke edilen lotun rezervasyonlarının bırakılıp eksiğin
  yeniden açılması; rezerve lotların SKT uyarısı; durum makinesinin izinli ve yasak geçişleri.
- API (`test_api.py`): oluştur, onayla, listele (durum, müşteri, eksik filtresi), aday lotlar
  (`meets_shelf_life`), elle rezervasyon, bırakma, eksikleri rezerve etme, iptal; planlama ve depo yalnızca
  okur (yazmada 403), ilgisiz roller 403, giriş yapmamış 401/403; stok `available` ucunda rezerve miktar.
- Üretim ve dolum toplama testleri değişmeden geçti (`available_lots` artık rezerve stoğu düşer).
- Demo verisi: `seed_sales_demo` (seed_demo sonunda) iki müşteri (zincir market 180 gün), mamul açılış
  stoku ve iki sipariş (biri onaylı ve FEFO rezervasyonlu, 120 günlük lot raf ömrü şartı yüzünden atlanır;
  biri taslak) yazar (`apps/sales/tests/test_seed_demo.py`).
- Frontend: `npm test` 121 test (sevkiyat: 8), `lint`, `format:check`, `typecheck`, `build` temiz. Ekranlar:
  Sevkiyat menüsünde satış siparişleri listesi (durum, eksik filtresi), sipariş oluşturma / düzenleme,
  sipariş detayı (satır başına rezerve, sevk, eksik; toplam; rezervasyonlar; lot seçme ve bırakma;
  "Eksikleri rezerve et"; kayıt paneli), müşteriler ve müşteri kartı (asgari raf ömrü, sipariş geçmişi).
  Ana verilerdeki müşteri formunda asgari kalan raf ömrü alanı.

### Faz 3 kabul kriterleri (Adım 3.1'e düşenler)

| Kriter | Durum | Kanıt |
|---|---|---|
| Rezerve stok başka siparişe ayrılamıyor; `available` hesabı doğru | ✓ | `test_reserved_stock_is_not_given_to_another_order`, `test_reserved_stock_cannot_be_reserved_twice`, API `test_stock_balances_show_reserved_quantity` |
| Raf ömrü yetersiz lot (müşteri şartı) rezerve edilmiyor | ✓ | `test_shelf_life_requirement_skips_short_lots`; toplamada engel `test_unshippable_lots_cannot_be_picked` (Adım 3.2) |
| Stok değişmezleri tüm yeni testlerde geçiyor | ✓ | sales testleri `invariants` fixture'ı, rezervasyon testleri `assert_stock_invariants()` |

### Adım 3.3 ve 3.4 doğrulaması (iade, izlenebilirlik, geri çağırma)

- Backend: `pytest` 751 test geçti (returns + traceability: 38; satış siparişi PR #11 ile birlikte); `ruff check`, `ruff format --check`,
  `mypy` temiz; `makemigrations --check` temiz. Stoka dokunan iade testleri `assert_stock_invariants()` ile
  biter.
- İade servis testleri (`apps/returns/tests/test_services.py`): durum makinesinin izinli ve yasak
  geçişleri; kabulde `RETURN` hareketi, lotun bloke edilmesi ve iade numunesi; serbest bırakma →
  yeniden sevke uygun ve mamul deposuna dönüş; red → imha görevi, `SCRAP` hareketi ve iadenin
  sonuçlanması; `REWORK` → planlama görevi; `FINAL` spesifikasyona düşme; `REWORK`un iade dışında hâlâ
  yalnızca bulk lota verilmesi; yetkisiz roller.
- İzlenebilirlik testleri (`apps/traceability/tests`): geri izleme tedarikçi, tedarikçi lot no ve mal
  kabul belgesine iner; ileri izleme stok, sevk (ters kayıt düşülmüş) ve iade miktarlarını verir; geri
  çağırma özeti, Excel ve PDF; yetkisiz rol 403.
- Performans: 5 seviyeli, 10.050 hareketli veride geri çağırma simülasyonu yerel çalıştırmada 0,3–0,42 sn
  (hedef < 1 sn).
- Frontend: `npm test` 133 test (iade 7, izlenebilirlik 5), `lint`, `format:check`, `typecheck`, `build`
  temiz. Ekranlar: İadeler (liste, oluştur, kabul, imha, kayıt paneli), İzlenebilirlik (geri / ileri izleme
  ağacı, geri çağırma simülasyonu, Excel/PDF). Numune ekranı iade numunesinde "Yeniden işleme" kararını
  gösterir.

### Faz 3 kabul kriterleri (Adım 3.3 ve 3.4'e düşenler)

| Kriter | Durum | Kanıt |
|---|---|---|
| İade karantinaya giriyor ve QC kararıyla yönleniyor | ✓ | `apps/returns/tests/test_services.py` (serbest / red / yeniden işleme) |
| Hammadde lotunun ileri izlemesi doğru müşteri ve miktarları veriyor; geri izleme tedarikçiye iniyor | ✓ (Adım 3.2 ile) | Miktarlar ve tedarikçi `apps/traceability/tests/test_selectors.py`; müşteri ayağı `test_customer_leg_from_shipments` ve uçtan uca test |
| Geri çağırma simülasyonu 10.000 hareketlik veride 1 sn altında | ✓ | `test_recall_performance_on_deep_wide_data` (10.050 hareket, ~0,4 sn) |
| İade blokajı rezervasyonu bırakır, eksik yeniden açılır | ✓ | `test_return_hold_releases_reservations_and_reopens_shortage` |
| Stok değişmezleri tüm yeni testlerde geçiyor | ✓ | iade testleri `invariants` fixture'ı ile biter |

### Adım 3.2 doğrulaması (sevkiyat, toplama, irsaliye ve uçtan uca test)

- Backend: `pytest` 828 test geçti (sevkiyat, iade bağı ve uçtan uca: 40; izlenebilirlik müşteri ayağı: 1;
  etiket ve ekler PR #9 ile birlikte); `ruff check`, `ruff format --check`, `mypy` temiz; OpenAPI şeması
  uyarısız; `makemigrations --check` temiz. Stoka dokunan tüm sevkiyat testleri `invariants` fixture'ı ile
  `assert_stock_invariants()` çağırır.
- Sevkiyat servisleri (`apps/sales/tests/test_shipments.py`): planlamada kalan miktar ve sınırlar; okutmada
  stok ve rezervasyonun sevk alanına taşınması; kısmi okutma ve satırı aşma; karantina, SKT'si geçmiş ve raf
  ömrü yetersiz lotun okutulamaması; farklı lotta gerekçe ve eski rezervasyonun bırakılması; geri alma;
  yükleme ve sevk onayında `SHIPMENT` hareketi, `CONSUMED` rezervasyon ve sipariş durumu; kısmi sevk;
  okutulduktan sonra bloke olan lotun sevki durdurması; iptalde okutmaların geri dönmesi; görevler ve
  "Sevk edildi" bildirimi; denetim günlüğünde maskeli TC no; durum makinesinin izinli ve yasak geçişleri.
- API (`test_shipment_api.py`): planla, lot no ya da `LOT:` etiketiyle okut, farklı lot gerekçesi, geri al,
  yükle, sevk et, irsaliye JSON (maskeli TC) ve PDF, toplama önerisi, müşteriye sevk edilen lotlar, rol
  matrisi (yetkisiz rol 403).
- İade bağı (`apps/returns/tests/test_shipment_link.py`): iade sevk edilenden fazla olamaz, sevkiyat sevk
  edilmiş ve aynı müşterinin olmalı.
- Uçtan uca (`apps/sales/tests/test_e2e_shipment.py`): mal kabul → QC → üretim → bulk serbest → dolum →
  mamul serbest → sipariş → FEFO rezervasyon → ikinci siparişte eksik → sevkiyat planı → karantina lotu
  reddedilir → toplama → yükleme → sevk → irsaliye PDF → hammadde lotunun ileri izlemesinde doğru müşteri
  ve miktar → geri izleme tedarikçiye → geri çağırma → iade (sevk edilenden fazlası reddedilir) → QC
  serbest → stoğa dönüş.
- Demo verisi: `seed_sales_demo` bir siparişe planlanmış sevkiyat ve sevk edilmiş bir sevkiyat (irsaliyesi
  alınabilir) ekler (`test_seed_demo_includes_sales`).
- Frontend: `npm test` 164 test (sevkiyat ekranları 14, iade bağı 2), `lint`, `format:check`, `typecheck`,
  `build` temiz. Ekranlar: Sevkiyatlar listesi ve sevkiyat detayı (satırlar, okutulanlar, araç ve şoför,
  yükleme ve sevk onayı, irsaliye PDF, iptal, kayıt paneli); sipariş detayında "Sevkiyat planla" ve
  siparişin sevkiyatları; depoya Toplama sekmesi ve toplama tableti (satır başına kalan, rezerve lot önce
  sonra FEFO önerisi, raf ömrü uyarısı, `ScanInput` ile okutma, farklı lotta gerekçe, geri alma, "Yükleme
  tamam"); müşteri kartında sevk edilen lotlar; iade formunda sevkiyat seçimi.
- İnceleme düzeltmeleri (PR #13, kurallar DECISIONS.md "İnceleme sonrası kurallar"): kod incelemesinde
  testle doğrulanan 20 hata ve düzeltmelerin bağımsız denetiminde bulunan 5 sorun (çok satırlı sipariş
  onayıyla okutma arasında birim satırı kilitlenmesi, iptalde eski lot durumu, sipariş ekranında sevk
  alanı rezervasyonunda "Bırak", eksik aday listesi ve kilit sırası testleri) düzeltildi; her düzeltmenin
  testi düzeltmeden önceki kodda kırılıyor. Backend `pytest` 846 test geçti; yeni testler: sevk alanındaki
  stok rezerve edilmez ve önerilmez, ikinci rampa başka rampanın okuttuğu mala dokunmaz, sevk alanı
  rezervasyonu siparişten bırakılmaz, aynı lottan iki okutma rezervasyonu aşarsa sevk reddedilir, okutma
  eksiği kapatınca eksik görevi kapanır, yüklendikten sonra okutma geri alınıp kalan sevk edilir, okutma
  kalmayınca sevk reddedilir, okutma sipariş ve lotu kilitler (sipariş → lot → bakiye sırası, yalnızca lot
  satırı), sevk alanındaki stok aday listesinde yok, sipariş rezervasyonu lokasyon türünü taşır, SKT'si
  geçmiş rezerve lot öneride işaretlenir, irsaliye tarihi yerel ve karışık birimler toplanmaz, ters
  kayıtla geri alınan sevk iade edilemez ve müşteri kartında görünmez, iade kabulü sevkiyatı kilitler,
  plaka / şoför / taşıyıcı uzunluğu 400 döner, iki üründe aynı lot no `ambiguous_lot`, demo verisi sevk
  edilemeyen siparişe sevkiyat açmaz; uçtan uca test iade dönen mamulün varsayılan olarak mamul deposuna
  (sevk alanına değil) döndüğünü doğrular. Frontend `npm test` 173 test: tablette çift Enter (aynı anda
  basılsa da) tek okutma gönderir, sipariş ekranı sevk alanı rezervasyonunda "Bırak" göstermez, bir sayfa
  yüklenemezse sayfalayıcı kalır, eksik satırda seçim kalır, varsayılan miktar tek lokasyonun serbest
  stoğu, yüklenen sevkiyatta depo okutmayı geri alır, müşteri kartında sevk edilen lotlar sayfalı,
  laboratuvar iadede sevkiyat numarasını bağlantısız görür.

### Faz 3 kabul kriterleri (tamamı)

| Kriter | Durum | Kanıt |
|---|---|---|
| Uçtan uca test: mal kabul → … → mamul lot serbest → sipariş → rezervasyon → toplama → sevk → irsaliye PDF | ✓ | `test_goods_receipt_to_shipment_waybill_trace_and_return`; API'de `test_full_shipment_flow` |
| Rezerve stok başka siparişe ayrılamıyor; `available` hesabı doğru | ✓ | `test_reserved_stock_is_not_given_to_another_order`, `test_reserved_stock_cannot_be_reserved_twice`, `test_stock_balances_show_reserved_quantity`; uçtan uca testte ikinci siparişin eksiği |
| Karantina / SKT geçmiş / raf ömrü yetersiz lot sevk edilemiyor | ✓ | `test_unshippable_lots_cannot_be_picked` (üç durum), `test_lot_blocked_after_picking_stops_dispatch`, API `test_shelf_life_block_and_unknown_lot`; uçtan uca testte karantina lotu |
| İade karantinaya giriyor ve QC kararıyla yönleniyor | ✓ | `apps/returns/tests/test_services.py`; uçtan uca testte iade → serbest → stok |
| Hammadde lotunun ileri izlemesi doğru müşterileri ve miktarları veriyor; geri izleme tedarikçiye iniyor | ✓ | `test_customer_leg_from_shipments`, uçtan uca test (müşteri ve 600 adet), `apps/traceability/tests/test_selectors.py` |
| Geri çağırma simülasyonu 10.000 hareketlik demo veride 1 sn altında | ✓ | `test_recall_performance_on_deep_wide_data` (10.050 hareket, ~0,4 sn) |
| Stok değişmezleri tüm yeni testlerde geçiyor | ✓ | sevkiyat, iade ve uçtan uca testler `invariants` fixture'ı ile biter |

## Faz 4 — Destek modülleri ve raporlama

Plan dosyası: `docs/plan/FAZ-4-destek-raporlama.md`. Kararlar D-12 (sıra), D-13 (satın alma onay
limiti), D-14 (tank temizliği), D-15 (kg başı genel gider) `docs/DECISIONS.md`'de.

### Adım 4.1 doğrulaması (maliyet)

- Backend: `pytest` 873 test geçti (costing: 22); `ruff check`, `ruff format --check`, `mypy` temiz;
  `makemigrations --check` temiz. Stoka dokunan maliyet testleri `invariants` fixture'ı ile
  `assert_stock_invariants()` çağırır.
- Elle hesaplanmış örnek (`test_hand_calculated_purchase_bulk_and_finished_lot_cost`): LAS alışı EUR fiyat,
  kur, nakliye (miktar oranı) ve gümrük (tutar oranı) ile 92.123,61 TL / 2.000 kg = 46,0618; SLES 40,9619;
  su 0,1829. Bulk 41.903,94 TL / 980 kg = 42,7591 (malzeme + enerji, işçilik, amortisman kalemleri). Mamul
  37.201,90 TL / 1.000 adet = 37,2019 (bulk, ambalaj, dolum oranları, fire), mamul fire payı 366,12.
- Kurallar: tahmini maliyet (son alış, sonra standart), bilinmeyen girdinin "eksik" olarak mamule taşınması,
  yoğunluksuz malzemede genel gider kaleminin eksik işaretlenmesi, kaydedilmiş kabulde fiyat düzeltmesinin
  yeni sürüm açması, kur ve not kuralları, yeniden hesaplamada not zorunluluğu ve zincirleme, bitmemiş
  şarjın maliyetlenmemesi, oran geçerlilik tarihi, standart maliyet kuralları, olay başına tek hesap.
- Raporlar: şarj teorik 39.943,94 TL vs fiili birim 40,7591, fark %2,04; fire 223,80 + 366,12 = 589,92;
  LAS stok değeri 1.400 × 46,0618 = 64.486,52; Excel çıktıları açılıyor.
- Yetki: `yonetim` dışındaki tüm roller her maliyet ucunda 403, admin görür, anonim reddedilir
  (`test_cost_amounts_are_forbidden_to_other_roles`); depo mal kabulde fiyat görmez ve gönderdiği fiyat yok
  sayılır (`test_receipt_prices_hidden_from_depo_and_ignored_on_write`).
- Demo verisi: `seed_costing_demo` (seed_demo sonunda) standart maliyetler, altı kg başı oran ve tüm
  maliyetlenebilir lotların maliyeti (`apps/costing/tests/test_seed_demo.py`).
- Frontend: `npm test` 181 test (maliyet ve menü testleri dahil), `lint`, `format:check`, `typecheck`,
  `build` temiz. Ekranlar: Maliyet menüsü (yalnızca yönetim): lot maliyetleri, raporlar (Excel), kg başı
  oranlar, standart maliyetler; lot maliyet dökümü ve "Yeniden hesapla"; mal kabulde "Fiyat ve masraflar"
  paneli (satın alma ve yönetim); lot kartında "Maliyet" düğmesi.

| Faz 4 kabul kriteri | Durum | Kanıt |
|---|---|---|
| Bulk ve mamul lot maliyeti kalem kalem doğru (elle hesaplanmış örnek) | ✓ | `test_hand_calculated_purchase_bulk_and_finished_lot_cost` |
| Maliyet tutarları yetkisiz role API'de dönmüyor | ✓ | `test_cost_amounts_are_forbidden_to_other_roles`, `test_receipt_prices_hidden_from_depo_and_ignored_on_write` |
| Stok değişmezleri yeni testlerde geçiyor (maliyet) | ✓ | costing testleri `invariants` fixture'ı ile biter |

### Adım 4.2 doğrulaması (satın alma)

- Yeni uygulama `apps/purchasing`: talep `ST-`, sipariş `SA-` (onay limiti D-13), siparişten mal kabul,
  öneri (basit MRP), tedarikçi performansı, sipariş PDF'i ve e-posta. Ekranlar `/satin-alma`: siparişler,
  beklenen teslimatlar, talepler, öneriler, tedarikçi performansı, ayarlar (rollere göre).
- Backend: `pytest` 907 test yeşil (34'ü satın alma; maliyet PR'ıyla birleştirildikten sonra), `ruff check`, `ruff format --check`, `mypy` temiz,
  `makemigrations --check` değişiklik yok. Frontend: `npm test` 191 test (10'u satın alma), lint, biçim,
  tip denetimi ve build temiz.
- Testlerde: limit altı/üstü onay ve limitsiz durumda yonetim onayı, onaya gönderme ve geri gönderme
  görevleri, onayda depoya beklenen teslimat bildirimi, PDF ekli e-posta ve e-posta hatasında geri alma,
  talep → sipariş → iptalde talebin yeniden açılması, %10 fazla teslim toleransı, siparişsiz mal kabulün
  etkilenmemesi, kalanı kapatma, teslimatı olan siparişin iptal edilememesi, tedarikçi performansı,
  `lot.rejected` bildiriminin satın almaya tedarikçi adıyla gitmesi, depo rolünün fiyat görmemesi,
  yetkisiz rollerin 403 alması.

### Faz 4 kabul kriterleri (Adım 4.2'ye düşenler)

| Kriter | Durum | Kanıt |
|---|---|---|
| Minimum stok ve açık emir ihtiyacından satın alma talebi önerisi | ✓ | `test_suggestions_from_min_stock_and_open_production_orders` (öneri ve 07:00'de otomatik talep), API `test_supplier_performance_and_suggestions_api` |
| Siparişe bağlı mal kabul bekleyen miktarı doğru düşürüyor | ✓ | `test_receipt_from_order_decreases_pending_quantity` (kısmi ve tam teslim, durum PARTIALLY_RECEIVED → RECEIVED, fiyat ve kur siparişten) |
| Stok değişmezleri tüm yeni testlerde geçiyor | ✓ | stoka dokunan satın alma testleri `invariants` fixture'ı ile biter |

### Adım 4.3 doğrulaması (raporlama ve panolar)

- Yeni uygulama `apps/reporting`: 5 pano, 7 rapor, Excel/PDF çıktısı, arka plan rapor işi
  (`ReportJob`, Celery) ve bildirim; ekran "Panolar ve raporlar" (Panolar, Raporlar,
  İndirmeler), menüde her role açık, içerik rolle daralır.
- Testler (`apps/reporting/tests`, 39 test): servislerle kurulan gerçek akış (mal kabul → red
  ve kabul numuneleri → tolerans dışı tartımlı şarj → fireli dolum → sevkiyat) üzerinden rapor
  değerleri (verim %95, sapma 1, fire %2,5, red oranı %20, zamanında sevk); her pano ve rapor
  için izinli ve yasak rol (403), anonim 401; tutar sütunlarının depo ve planlamaya ekranda ve
  Excel'de dönmemesi; arka plan işi, bildirim, yalnızca isteyenin indirmesi, saklama süresi;
  durum makinesi geçişleri. Frontend: 9 Vitest testi.
- **Performans**: demo verisi + 10.000'den fazla stok hareketi + 3.000 görevle yönetim panosu
  0,32 sn, 15 sorgu; diğer panolar 0,03 sn (`test_performance.py`, sınır 2 sn ve 30 sorgu).

### Faz 4 kabul kriterleri (Adım 4.3'e düşenler)

- [x] Yönetim panosu 2 sn altında açılıyor (demo verisiyle) — 0,32 sn.
- [x] Maliyet tutarları yetkisiz role API'de dönmüyor — rapor ve pano tarafı da test edildi.
- [x] Stok değişmezleri tüm yeni testlerde geçiyor.

### Adım 4.4 ve 4.5 doğrulaması (bakım, İSG ve çevre)

- Yeni uygulamalar `apps/maintenance` (bakım planı, `BK-` iş emri, duruş, temizlik kaydı, kalibrasyon,
  temizliksiz geçiş kuralları, yedek parça sarfı) ve `apps/hse` (tehlike bilgisi ve H/P ifadeleri, GBF arşivi
  ve eksik GBF raporu, depolama limitleri, `AT-` atık kaydı, `OL-` olay/kaza kaydı). Üretim ve dolum bakımı
  `masterdata.check_equipment` kancasıyla, İSG stok hareketlerini `inventory.register_movement_hook` ile
  kullanır (DECISIONS.md).
- Backend: `pytest` 994 test yeşil (bakımda 51, İSG'de 36 yeni test), `ruff check`, `ruff format --check`,
  `mypy` temiz, `makemigrations --check` değişiklik yok. Frontend: `npm test` 219 test (bakım 14, İSG 13),
  `lint`, `format:check`, `typecheck`, `build` temiz.
- Ekranlar: Bakım menüsü `/bakim` (iş emirleri, planlar, duruşlar, kalibrasyon, temizliksiz geçişler, ayarlar)
  ve iş emri sayfası; ana sayfada "Arıza bildir"; tartım ekranında terazi seçimi ve kalibrasyon uyarısı;
  şarj başlatmada tank temizlik kontrolü ve "Temizlik kaydı gir". İSG menüsü `/isg` (olaylar, tehlike
  bilgileri, H/P ifadeleri, GBF arşivi ve eksik GBF raporu Excel'i, depolama limitleri, atık, özet, ayarlar),
  olay sayfası, malzeme listesinde "Tehlike bilgisi"; tehlikeli lotlarda uyarı simgesi.
- Demo verisi: `seed_maintenance_demo` (iki terazi, biri kalibrasyonu 3 gün içinde dolan; tank ve hat
  planları; bir temizliksiz geçiş) ve `seed_hse_demo` (LAS, NaOH, alkol, koruyucu tehlike bilgisi; GBF'ler,
  biri eskimiş biri eksik; hammadde deposu limitleri; atık teslimi; ramak kala bildirimi), `seed_demo` sonunda.

| Faz 4 kabul kriteri | Durum | Kanıt |
|---|---|---|
| Kalibrasyonu geçmiş terazi kuralı çalışıyor | ✓ | `test_overdue_calibration_blocks_weighing`, `test_due_soon_calibration_warns_but_allows`, `test_scale_required_when_scales_exist`, `test_failed_calibration_puts_scale_down` |
| Temizliği yapılmamış tank kuralı çalışıyor | ✓ | `test_product_change_requires_cleaning`, `test_same_product_needs_no_cleaning`, `test_changeover_rule_allows_switch_without_cleaning`, API `test_cleaning_check_and_record` |
| Stok değişmezleri tüm yeni testlerde geçiyor (bakım, İSG) | ✓ | yedek parça sarfı ve depolama limiti testleri `invariants` fixture'ı ile biter |

## Faz 5 — Entegrasyonlar ve canlıya geçiş

Faz dosyası: `docs/plan/FAZ-5-entegrasyon-canli.md`. Kararlar D-16 … D-20 (DECISIONS.md).

| Adım | Durum | Not |
|---|---|---|
| 5.4 Canlı ortam | Kod tamam (2026-10-16), sunucuya kurulum bekliyor | Üretim compose, nginx HTTPS + güvenlik başlıkları, üretim ayarları, `docs/KURULUM.md`, `docs/CANLI-KONTROL-LISTESI.md` |
| 5.5 Yedek, izleme, güvenlik | Kod tamam (2026-10-16), sunucuya kurulum bekliyor | Gece yedeği + ayrı konum kopyası + haftalık otomatik geri yükleme testi; `ops` izleme ve uyarılar; kilit, hareketsizlik süresi, 2FA, şifre politikası; CI gizli bilgi ve bağımlılık taraması; `docs/KVKK.md` |
| 5.6 Geçiş ve eğitim | Araçlar tamam (2026-10-16, PR #18), sayım günü bekliyor | Excel içe aktarmalar, Canlıya geçiş ekranı, stok karşılaştırması, Sorun bildir, kılavuzlar; `docs/GECIS-PLANI.md` |

### Adım 5.4 ve 5.5 doğrulaması (canlı ortam ve güvenlik)

- Sandbox'ta üretim kurulumu (`scripts/prod-compose.sh up -d --build --wait`) tüm servisler sağlıklı;
  `scripts/prod_smoke_test.sh https://localhost` geçti: HTTP→HTTPS 301, TLS 1.0/1.1 reddi, her yanıtta HSTS,
  CSP, X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy; bilinmeyen API adresi JSON 404 (DEBUG
  kapalı); statik dosyalar nginx'ten; bilinmeyen Host 444; HTTPS üzerinden giriş, Secure/HttpOnly çerezler,
  WebSocket 101; `check --deploy` uyarısız; yedek alındı (103 tablo), geri yükleme testi geçici veritabanında
  sayıları tuttu, `/api/v1/ops/health/` tümü `ok`. Aynı test CI'da `prod` işinde çalışır.
- Hata durumları elle denendi: ayrı konum işaret dosyası yok → yedek `failed`; bozuk `db.dump` → sha256 hatası;
  manifestte değiştirilmiş sayı → `mismatches` dolu, test başarısız; veritabanı kapalı → Türkçe hata mesajı.
  Ayrı konum klasörü ve rclone hedefi kopyalanıp doğrulandı; ayrı konumdan geri yükleme testi geçti.
  `scripts/restore.sh latest --yes` ile tam geri yükleme provası yapıldı.
- Giriş güvenliği: `apps/core/tests/test_security.py` (26 test: kilit ve süresi, var olmayan kullanıcı adı,
  admin bildirimi ve kilit açma, RFC 6238 test vektörü, 2FA kurulum/giriş/tekrar kullanılamayan kod/kurtarma
  kodu, zorunlu rolde kurulum öncesi engel, yönetim paneli 2FA, şifre politikası ve değiştirme, hareketsizlik
  süresi, arka plan isteğinin oturumu uzatmaması, saha tableti çerezi ve sahte çerezin reddi).
- İzleme ve KVKK: `apps/ops/tests/test_ops.py` (21 test: durum dosyası içe aktarımı, yedek/test/disk/yük/kuyruk
  kontrolleri, uyarının bir kez ve saatte bir tekrarı, düzelme bildirimi, dış izleme ucu, IP saklama süresi).
- Frontend: iki adımlı giriş, Güvenlik sayfası (2FA kurulum, kurtarma kodları, şifre değiştirme), Sistem
  (durum, kullanıcılar, bu cihaz), hareketsizlik başlığı ve süresi, arayüz hata kaydı; 259 test geçiyor.
  Güvenlik sayfasının üretim kurulumundaki görüntüsü: `/mnt/project-files/faz5-canli-guvenlik/guvenlik-sayfasi.png`.
- Backend 1081+ test, ruff, mypy temiz; gitleaks (tüm geçmiş), pip-audit ve npm audit (yüksek/kritik) temiz.

### Faz 5 kabul kriterleri (Adım 5.4 ve 5.5'e düşenler)

| Kabul kriteri | Durum | Kanıt |
|---|---|---|
| Canlı ortam HTTPS, güvenlik başlıkları ve `DEBUG=False` ile çalışıyor; güvenlik kontrol listesi tamam | Sandbox'ta ✓; gerçek sunucuda kontrol listesi kurulumda işaretlenecek | `scripts/prod_smoke_test.sh`, CI `prod` işi, `docs/CANLI-KONTROL-LISTESI.md` |
| Yedekten geri yükleme testi başarılı ve otomatik | ✓ (her pazar 04:00 + CI) | `backup/restore-test.sh`, duman testindeki geri yükleme adımı, `ops` izleme kontrolü |

### Adım 5.6 doğrulaması (geçiş ve eğitim)

- İçe aktarmalar: ana verilere depo, lokasyon, ekipman, birim dönüşümü; reçeteler (taslak sürüm).
  Canlı başlangıç tarihi açılış stokunu kapatır. Yeni uygulama `apps/golive`: hazırlık listesi, paralel
  çalışma stok karşılaştırması (`SK-`), "Sorun bildir" (`SB-`, admin görevi). Ekranlar: Canlıya geçiş
  (`/gecis`), Yardım (`/yardim`, rol kılavuzları ve sayım günü planı), üst çubukta Sorun bildir.
  Hazırlanacaklar listesi `docs/GECIS-PLANI.md`.
- Testler: `apps/golive/tests` (servis ve API: düzeyler, birim dönüşümü, gün sonu stoğu, hatalı satır,
  Excel çıktısı, hazırlık listesi, sorun bildirimi görevi ve görünürlüğü, her uç noktada yasak rol),
  `apps/recipes/tests/test_importers.py`, `apps/masterdata/tests/test_importers.py` (yeni türler),
  `test_opening_closes_on_go_live_date`. Frontend: `golive.test.tsx`, `RecipeImport.test.tsx`, menü testi.
- Sonuç: backend `pytest` 1067 test yeşil, `ruff check`, `ruff format --check`, `mypy` temiz,
  `makemigrations --check` değişiklik yok. Frontend `npm test` 238 test, lint, biçim, tip denetimi ve
  derleme temiz.
- Kılavuzlar: 11 kılavuz (genel, 9 rol, sayım günü) ve demo verisinden alınmış 45 ekran görüntüsü
  (`frontend/public/kilavuz/`). Görüntüler `scripts/kilavuz-ekran-goruntuleri.mjs` ile yeniden üretilir
  (servisler ve demo verisi ayaktayken; eksik örnek kayıtları API üzerinden açar, hiçbir şey silmez).
- Prova (demo verisi, ayrı veritabanı, gerçek HTTP API üzerinden): hazırlık listesi → depo, lokasyon,
  ekipman içe aktarma (önizle + aktar) → reçete içe aktarma (tekrar yükleme taslak var diye reddedildi) →
  açılış stoku → sayım listesiyle lot + lokasyon düzeyinde karşılaştırma → depo canlı tarihini giremedi
  (403), yönetim girdi → açılış yüklemesi `opening_closed` ile kapandı → haftalık malzeme düzeyinde
  karşılaştırma ve Excel çıktısı → üretim rolü karşılaştırmaya giremedi (403) → dolum "Sorun bildir"
  gönderdi, admin'e görev açıldı, başka kullanıcı bildirimi ve görüntüyü göremedi (404), admin açtı.

| Faz 5 kabul kriteri (Adım 5.6'ya düşen) | Durum | Kanıt |
|---|---|---|
| Açılış stoku yüklendi, paralel çalışma dönemi karşılaştırması tutarlı | Araçlar hazır; gerçek veriyle sayım gününde | Araç: açılış içe aktarma + `create_stock_comparison` testleri ve prova. Gerçek sayım ve 2–4 haftalık karşılaştırma fabrika verisiyle yapılacak. |
