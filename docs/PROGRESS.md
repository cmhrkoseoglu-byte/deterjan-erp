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

