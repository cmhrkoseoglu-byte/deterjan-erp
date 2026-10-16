# Faz 5 — Entegrasyonlar ve canlıya geçiş

**Amaç:** Sistemi dış dünyaya bağlamak (muhasebe, e-belge, terazi) ve üretim ortamında güvenli, yedekli,
izlenen şekilde çalıştırmak.

Not: **Canlıya geçiş hazırlığı (Adım 5.4–5.6) Faz 3 bittikten sonra da yapılabilir**; sistemi Faz 4'ü
beklemeden kullanmaya başlamak istenirse bu adımlar öne alınır (Karar D-16).

---

## Adım 5.1 — Muhasebe entegrasyonu

- Hedef program netleşince (Logo / Mikro / Netsis / diğer — Karar D-17) entegrasyon yöntemi seçilir:
  resmi API, ara veritabanı tablosu veya dosya (XML/Excel) aktarımı.
- Aktarılacaklar (önerilen): cari kartlar (tedarikçi/müşteri), malzeme kartları, mal kabuller (alış irsaliyesi),
  sevkiyatlar (satış irsaliyesi), üretimden giriş/sarf fişleri (maliyet modülü varsa tutarlarıyla).
- `integrations` uygulaması: her aktarım bir `IntegrationJob` kaydıdır (durum, deneme sayısı, hata mesajı,
  gönderilen/alınan veri). Hatalı aktarımlar panoda görünür ve yeniden denenebilir. Aynı kayıt iki kez aktarılmaz (idempotency anahtarı).
- Ana veri yönü kararı: kartlar hangi sistemde açılır, hangisi kopyalar? (Karar D-18)

## Adım 5.2 — e-İrsaliye / e-Fatura

- Özel entegratör firmasının API'si üzerinden (firma seçimi Karar D-19).
- Sevkiyat `DISPATCHED` → e-İrsaliye taslağı → kullanıcı onayı → gönderim → durum takibi (kabul/red).
- e-Fatura muhasebe programından kesiliyorsa bu sistemde yalnızca irsaliye.

## Adım 5.3 — Terazi ve saha cihazları

- **Terazi**: seri port / TCP üzerinden ağırlık okuyan küçük bir yerel ajan (`scale-agent`, Python) →
  WebSocket ile tartım ekranına canlı ağırlık. Elle giriş yetkili rolde ve gerekçeli kalır.
  Tartım kaydında `source = SCALE | MANUAL` ve terazi kimliği tutulur.
- **PLC / tank seviye** (opsiyonel): OPC UA veya Modbus ile tank seviyesi/sıcaklık okuma, şarj kaydına ekleme.
- **Dolum hattı sayacı** (opsiyonel): hat sayaç değerinin otomatik okunması.

## Adım 5.4 — Canlı ortam

- `docker-compose.prod.yml`: gunicorn/uvicorn workers, nginx + HTTPS (Let's Encrypt veya firma sertifikası),
  statik dosyalar, `DEBUG=False`, güvenli çerez ayarları, `ALLOWED_HOSTS`, CSP başlıkları.
- **Yerel sunucu** seçilirse: UPS, RAID, dışarıdan erişim için VPN. **Bulut** seçilirse: Türkiye'de veri
  merkezi (KVKK değerlendirmesi), güvenlik duvarı, sadece 443 açık.
- Ortam değişkenleri ve gizli bilgiler `.env` / gizli yönetimi; depoda gizli bilgi yok (CI kontrolü).

## Adım 5.5 — Yedekleme, izleme, güvenlik

- **Yedek**: her gece `pg_dump` + medya dosyaları; 30 gün saklama; **ayrı bir konuma** (bulut depolama veya
  harici disk) kopya. Haftalık otomatik **geri yükleme testi** (yedekten test veritabanına kur, sayıları karşılaştır).
- **İzleme**: sağlık kontrolü, hata takibi (Sentry veya muadili), disk/CPU uyarıları, Celery kuyruk uzunluğu.
- **Güvenlik**: parola politikası, başarısız girişte kilitleme, oturum zaman aşımı (saha tabletlerinde kısa),
  isteğe bağlı iki aşamalı doğrulama (yönetici rolleri), bağımlılık güvenlik taraması (CI).
- **KVKK**: kişisel veri envanteri (kullanıcılar, şoför bilgileri, müşteri yetkilileri), erişim kayıtları, saklama süreleri.

## Adım 5.6 — Geçiş ve eğitim

- **Veri geçişi**: Excel'den ana veri ve açılış stoku içe aktarma (Faz 1 araçları) — sayım günü planı:
  sayım → açılış stoku yükleme → sistem üzerinden çalışmaya başlama.
- **Paralel çalışma**: ilk 2–4 hafta Excel ile paralel; haftalık stok karşılaştırması.
- **Eğitim**: rol bazında kısa kullanım kılavuzları (ekran görüntülü), tablet ekranları için saha eğitimi.
- **Destek**: kullanıcı geri bildirimi için sistem içi "Sorun bildir" butonu (ekran + açıklama → admin görevi).

---

## Kabul kriterleri

- [ ] Muhasebeye aktarım idempotent; hatalı iş yeniden denenebiliyor (test).
- [ ] Terazi ajanı ile canlı ağırlık tartım ekranına geliyor; elle giriş gerekçe istiyor.
- [ ] Canlı ortam HTTPS, güvenlik başlıkları ve `DEBUG=False` ile çalışıyor; güvenlik kontrol listesi tamam.
- [ ] Yedekten geri yükleme testi başarılı ve otomatik.
- [ ] Açılış stoku yüklendi, paralel çalışma dönemi karşılaştırması tutarlı.

## Bu fazda kullanıcıya sorulacak kararlar

- **D-16** Canlıya geçiş Faz 3 sonrası mı, Faz 4 sonrası mı?
- **D-17** Muhasebe programı ve sürümü.
- **D-18** Ana veriler (cari, malzeme) hangi sistemde açılır?
- **D-19** e-İrsaliye için özel entegratör firması.
- **D-20** Barındırma: yerel sunucu mu, bulut mu? (CLAUDE.md §10)
