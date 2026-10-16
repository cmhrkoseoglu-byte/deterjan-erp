# CLAUDE.md — Deterjan Fabrikası Üretim Takip Sistemi

Bu dosya projenin anayasasıdır. Her oturumun başında oku. Burada yazan kurallar, faz planlarındaki
ayrıntılarla çelişirse **bu dosya geçerlidir**; çelişkiyi kullanıcıya bildir.

## 1. Proje özeti

Bir deterjan fabrikasında **hammadde kabulünden sevkiyata kadar** tüm süreci takip eden web uygulaması.
Bugüne kadar Excel kullanıldı; sistem sıfırdan kuruluyor. Birimler arası haberleşme sistem üzerinden,
kayıtlara bağlı görev/bildirim/yorum olarak yapılacak.

Ana zincir (sistemin omurgası):

```
Hammadde lotu → Üretim şarjı (bulk lot) → Dolum lotu (mamul) → Sevkiyat → Müşteri
```

Her mamul lotundan geriye (hangi hammadde lotları?) ve her hammadde lotundan ileriye (hangi müşteriler?)
tek sorguyla izlenebilmelidir.

## 2. Teknoloji yığını

| Katman | Seçim |
|---|---|
| Backend | Python 3.12+, Django 5.x, Django REST Framework, drf-spectacular (OpenAPI) |
| Veritabanı | PostgreSQL 16 (geliştirmede de PostgreSQL; SQLite kullanma) |
| Anlık bildirim | Django Channels + Redis |
| Arka plan işleri | Celery + Celery Beat + Redis |
| Frontend | React + TypeScript + Vite, React Router, TanStack Query, Mantine UI, PWA |
| Test | pytest, pytest-django, factory_boy; frontend için Vitest |
| Kod kalitesi | ruff (lint + format), mypy (backend servis katmanı), ESLint + Prettier |
| Kurulum | Docker Compose (db, redis, backend, worker, beat, frontend, nginx) |

Kimlik doğrulama: Django session + CSRF. SPA ve API, nginx arkasında **aynı origin** üzerinden sunulur.

## 3. Mimari: modüler monolit

Tek Django projesi, her iş alanı ayrı bir Django uygulaması (`backend/apps/<modül>`):

| Modül | Sorumluluk | Faz |
|---|---|---|
| `core` | Kullanıcı, rol, BaseModel, denetim günlüğü, belge numaralama, olay yayını | 0 |
| `masterdata` | Malzeme, birim, dönüşüm, depo/lokasyon, ekipman (tank/hat), tedarikçi, müşteri | 1 |
| `recipes` | Sürümlü reçete (formülasyon) | 1 |
| `inventory` | Lot, stok hareket defteri, bakiye, lot soy ağacı, mal kabul, sayım | 1 |
| `production` | Üretim emri, şarj, tartım, sapma | 1 |
| `workflow` | Olay → görev/bildirim kuralları, görev, bildirim, kayda bağlı yorum | 1 |
| `quality` | Test tanımı, spesifikasyon, numune, sonuç, onay/red, analiz sertifikası | 2 |
| `filling` | Ambalaj reçetesi, dolum emri, dolum lotu, fire, etiket/barkod | 2 |
| `sales` | Müşteri siparişi, sevkiyat, irsaliye | 3 |
| `returns` | Müşteri iadesi (karantina, iade numunesi, QC kararına göre yönlendirme) | 3 |
| `traceability` | Geri / ileri izleme raporu, geri çağırma simülasyonu (Excel/PDF) | 3 |
| `purchasing` | Satın alma talebi/siparişi | 4 |
| `costing` | Malzeme maliyeti, şarj ve ürün maliyeti | 4 |
| `maintenance` | Ekipman bakım planı, iş emri, duruş | 4 |
| `hse` | GBF arşivi, tehlikeli madde limitleri, atık | 4 |
| `reporting` | Panolar, raporlar, Excel çıktıları | 4 |

### Modül sınırları

- Bir modül başka bir modülün **modellerini okuyabilir**, ama başka modülün verisini **yalnızca o modülün
  `services.py` fonksiyonları üzerinden değiştirir**. Örnek: `production`, stok düşmek için
  `inventory.services.post_movement(...)` çağırır; `StockMovement.objects.create` yazmaz.
- Modüller arası "bir şey oldu" bildirimi **olay** ile yapılır (`core.events.publish`). `workflow` modülü
  olayları dinler; üretim modülü depoya görev açmayı bilmez.
- Döngüsel import yasak. Bağımlılık yönü: `core ← masterdata ← recipes/inventory ← production ← quality/filling ← sales/returns ← traceability`.
  `workflow` herkesi dinleyebilir, kimse `workflow`'a doğrudan bağımlı olmaz (sadece olay).

### Katmanlar (her modülde)

```
apps/<modül>/
  models.py        # Sadece alanlar, kısıtlar, basit property'ler. İş mantığı YOK.
  services.py      # Tüm yazma işlemleri ve iş kuralları. transaction.atomic burada.
  selectors.py     # Karmaşık okuma sorguları (raporlar, bakiyeler, soy ağacı).
  state.py         # Durum makinesi tanımı (izinli geçişler) — durumlu belgelerde.
  api/serializers.py, api/views.py, api/urls.py
  admin.py
  tests/           # test_services.py, test_api.py, factories.py
```

View'lar ince olur: doğrula → servisi çağır → serialize et. Serializer `save()` içinde iş mantığı yazma.

## 4. Değişmez kurallar (ihlal etme)

1. **Stok bir hareket defteridir.** `StockMovement` kayıtları değiştirilmez ve silinmez. Düzeltme, ters
   kayıt (reversal) ile yapılır. Bakiye (`StockBalance`) yalnızca `inventory.services.post_movement`
   içinde, aynı transaction'da, `select_for_update` ile güncellenir. Test her zaman şunu doğrular:
   `StockBalance == SUM(StockMovement)` (malzeme + lot + lokasyon bazında).
2. **Negatif stok yok.** Bir lot/lokasyon bakiyesi sıfırın altına düşecekse işlem reddedilir.
3. **Lot soy ağacı zorunlu.** Bir lottan tüketip başka bir lot üreten her işlem `LotLink`
   (girdi lot → çıktı lot, miktar) kaydı oluşturur.
4. **Sadece serbest bırakılmış (RELEASED) lot** üretimde tüketilir ve sevk edilir. Karantina/red/bloke
   lotlar seçilemez. (Faz 1'de serbest bırakma laboratuvar rolünün manuel işlemidir; Faz 2'de QC kararına bağlanır.)
5. **Belgeler durum makinesiyle ilerler.** Geçişler `state.py`'deki izin tablosuyla kontrol edilir; her
   geçiş `core.events.publish("<belge>.<yeni_durum>", ...)` olayı yayınlar ve denetim günlüğüne yazılır.
   Durum alanı doğrudan atanmaz, servis fonksiyonu kullanılır.
6. **Kullanılmış veri silinmez.** Ana verilerde `is_active=False`, belgelerde `CANCELLED` durumu. Hard
   delete API'de yoktur. Onaylanmış reçete sürümü değiştirilemez; yeni sürüm açılır.
7. **Her değişiklik iz bırakır.** Oluşturma, güncelleme (eski → yeni değerler), durum değişikliği ve
   iptal `core.AuditLog`'a yazılır. `created_by/updated_by` her kayıtta doludur.
8. **Miktar ve para `Decimal`.** `DecimalField(max_digits=18, decimal_places=4)` (miktar),
   `max_digits=18, decimal_places=4` (birim maliyet), para `decimal_places=2`. `float` yasak.
9. **Birimler.** Her malzemenin bir temel birimi (`base_unit`) vardır; stok her zaman temel birimde
   tutulur. Dönüşümler `MaterialUnitConversion` ve kg ↔ lt için `density` (g/ml) üzerinden yapılır.
   Dönüşüm yalnızca `masterdata.services.convert_quantity` ile.
10. **Belge numaraları** `core.services.next_document_number(prefix)` ile üretilir
    (ör. `UE-2026-00001`), yıl bazında sıfırlanır, `select_for_update` ile çakışmasız.
11. **Olaylar commit sonrası yayınlanır** (`transaction.on_commit`). Geri alınan işlem bildirim üretmez.
12. **Yetki her uç noktada kontrol edilir.** Rol bazlı izinler `core.permissions` içinde; frontend'in
   butonu gizlemesi yetki sayılmaz.

## 5. Roller

`admin`, `yonetim`, `planlama`, `depo`, `uretim`, `laboratuvar`, `dolum`, `sevkiyat`, `satin_alma`.
Django `Group` olarak tanımlanır, `seed_roles` yönetim komutuyla oluşturulur. Bir kullanıcının birden
fazla rolü olabilir. Görevler role ya da kişiye atanabilir.

## 6. Kod kuralları

- Kod, tablo, alan, değişken adları **İngilizce**. Kullanıcıya görünen her metin **Türkçe**
  (`verbose_name`, hata mesajları, arayüz). Django `LANGUAGE_CODE="tr"`, `TIME_ZONE="Europe/Istanbul"`, `USE_TZ=True`.
- İş kuralı ihlalleri `core.exceptions.BusinessRuleError(code, message)` fırlatır; API bunu 400 ve
  `{"code": "...", "detail": "..."}` olarak döner. Türkçe mesaj, sabit İngilizce kod.
- Tüm listeleme uç noktaları sayfalı (varsayılan 50) ve `django-filter` ile filtrelenebilir.
- API sürümlü: `/api/v1/...`. OpenAPI şeması `/api/schema/`, dokümantasyon `/api/docs/`.
- Her servis fonksiyonu tip ipuçlu ve docstring'li. Kullanıcıyı `actor: User` parametresi olarak alır.
- Gizli bilgi (şifre, anahtar) koda ya da depoya yazılmaz; `.env` (örneği `.env.example`).

## 7. Test kuralları

- Her servis fonksiyonu için mutlu yol + en az bir kural ihlali testi.
- Her durum makinesi için: izinli tüm geçişler ve en az bir yasak geçiş testi.
- Stok değişmezleri (kural 1, 2, 3) için ortak bir test yardımcısı: `assert_stock_invariants()`.
  Stoka dokunan her testin sonunda çağrılır.
- API testleri yetkiyi de test eder (yetkisiz rol 403 almalı).
- `pytest` yeşil olmadan bir adım tamamlanmış sayılmaz.

## 8. Çalışma protokolü (Claude için)

1. Oturum başında bu dosyayı, `docs/PROGRESS.md`'yi ve sıradaki faz dosyasını (`docs/plan/`) oku.
2. Faz dosyasındaki **adımları sırayla** uygula. Her adımdan önce kısa bir plan yaz, kullanıcı onaylarsa uygula.
3. Her adım sonunda: testleri çalıştır, `ruff check` ve `ruff format --check` temiz olsun,
   `docs/PROGRESS.md`'yi güncelle, anlamlı bir commit at (`feat(inventory): ...` biçiminde).
4. Planda olmayan bir karar gerekiyorsa (alan adı değil, iş kuralı düzeyinde) **sor**, tahmin etme.
   Kararı `docs/DECISIONS.md`'ye tarih ve gerekçesiyle yaz.
5. Bir fazın kabul kriterleri karşılanmadan sonraki faza geçme.
6. Bu dosyadaki kuralların değişmesi gerekiyorsa önce kullanıcıya öner; onay gelince güncelle.

## 9. Komutlar

```bash
cp .env.example .env                       # ilk kurulumda
docker compose up -d                       # tüm servisler (http://localhost/)
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py seed_roles
docker compose exec backend python manage.py create_demo_users   # demo kullanıcılar (yalnızca dev)
docker compose exec backend python manage.py seed_demo   # örnek veri (Faz 1 sonunda)

docker compose exec backend pytest                  # backend testleri
docker compose exec backend ruff check .            # lint
docker compose exec backend ruff format --check .   # biçim
docker compose exec backend mypy                    # tip denetimi

cd frontend && npm ci                      # frontend bağımlılıkları
cd frontend && npm test                    # Vitest
cd frontend && npm run lint && npm run format:check && npm run typecheck && npm run build

scripts/smoke_test.sh                      # servisler ayaktayken uçtan uca duman testi
pre-commit install                         # commit öncesi kancalar (bir kez)
pre-commit run --all-files
```

CI: `.github/workflows/ci.yml` (backend, frontend, Docker Compose duman testi).

## 10. Açık kararlar

- **Barındırma:** fabrikada yerel sunucu mu, bulut mu? Henüz karar verilmedi. Docker Compose ile ikisi de
  desteklenecek; Faz 5'e kadar karar verilmeli.
- **Ölçek** (ürün sayısı, tank/hat sayısı, kullanıcı sayısı): sonra netleşecek. Veri modeli sayıdan bağımsız.
- **Muhasebe programı** (Logo / Mikro / Netsis / diğer): Faz 5 öncesi netleşecek.
