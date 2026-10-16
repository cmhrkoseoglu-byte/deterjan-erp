# Canlıya geçiş planı (Faz 5, Adım 5.6)

Adım adım sayım günü planı, kullanıcıların da okuyacağı yerde, uygulamanın **Yardım > Canlıya geçiş ve
sayım günü** sayfasındadır (kaynak: `frontend/src/modules/help/guides/gecis.md`). Bu dosya, plan
başlamadan önce fabrikanın hazırlaması gerekenleri ve araçların nasıl denendiğini toplar.

## Fabrikanın hazırlaması gerekenler

1. **Kullanıcı listesi:** ad soyad, kullanıcı adı ve rol (birden fazla olabilir). Tabletler hat ya da
   vardiya kullanıcısıyla mı, kişisel kullanıcıyla mı açılacak?
2. **Excel listeleri (şablonlar uygulamada "Şablonu indir" ile alınır):**
   - Malzemeler: kod, ad, tür, temel birim; varsa yoğunluk, raf ömrü, minimum stok, giriş kontrolü,
     tehlikeli madde.
   - Birim dönüşümleri (koli, palet içi adet).
   - Tedarikçiler ve müşteriler (ünvan, vergi no, adres, yetkili).
   - Depolar, lokasyonlar (raf/bölge kodları; barkodla okutulacağı için tüm depolarda benzersiz),
     ekipmanlar (tank kapasiteleri, dolum hatları, teraziler).
   - Reçeteler: her ürünün formülü, şarj miktarı ve bileşen miktarları.
   - Malzeme, tedarikçi ve müşteri **kodları muhasebe programındaki kodlarla aynı** olmalı (Karar D-18).
3. **Sayım günü ve saati:** işlemlerin duracağı saat, sayım ekipleri, lokasyon dağılımı. Sayım
   listesinde lot no ve SKT yazılacak; lot no'su olmayan eski stok için bir kural (ör. `ACILIS-<kod>`).
4. **Etiket yazıcılarının IP adresleri** ve sahadaki teraziler (kalibrasyon tarihleri).
5. **Paralel çalışma için:** Excel stok listesinin hangi gün hazırlanacağı (önerilen cuma akşamı) ve
   karşılaştırmayı kimin yükleyeceği.

## Araçlar ve nerede

| İş | Ekran | Rol |
|---|---|---|
| Malzeme, dönüşüm, tedarikçi, müşteri, depo, lokasyon, ekipman yükleme | Ana veriler > ilgili sekme > Excel'den içe aktar | planlama |
| Reçete yükleme (taslak sürüm) | Reçeteler > Excel'den içe aktar | planlama, laboratuvar |
| Açılış stoku | Depo ve stok > Stok sorgu > Açılış stoku içe aktar | depo |
| Hazırlık listesi, canlı başlangıç tarihi | Canlıya geçiş > Hazırlık | yönetim (tarih), planlama ve depo görür |
| Haftalık stok karşılaştırması | Canlıya geçiş > Stok karşılaştırma | depo, yönetim (planlama görür) |
| Sorun bildirimi | Üst çubuk > Sorun bildir; admin: Canlıya geçiş > Sorun bildirimleri | herkes |
| Kılavuzlar | Yardım | herkes |

## Demo verisiyle prova

`seed_demo` sonunda `seed_golive_demo` bir örnek karşılaştırma açar (iki satır bilerek farklı). Prova
sırası: hazırlık listesine bak → şablonları indir → küçük bir dosyayla önizle → açılış stokunu yükle →
aynı listeyle karşılaştır ("Fark yok") → canlı tarihini bugüne al → açılış yüklemesinin kapandığını gör.
Gerçek açılış stoku ve paralel çalışma karşılaştırması sayım gününde fabrika verisiyle yapılır.
