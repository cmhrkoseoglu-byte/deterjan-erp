# Yetki paketleri

Bu dosya üretilir; elle değiştirmeyin. Kaynak: `backend/apps/*/access.py`
(docs/plan/kisi-yetkileri.md §5.1). Tablo, her bölümde rollerin varsayılan paketini gösterir.
Kişiye özel ayarlar (Sistem > Kullanıcılar > Yetkiler) burada yer almaz. CI dosyanın güncel
olduğunu denetler.

Yeniden üretmek için (depo kökünde):

```
docker compose exec -T backend python manage.py export_access --format=markdown > docs/YETKI-PAKETLERI.md
```

| Modül | Bölüm | Herkes | Rolü olan herkes | Yönetim | Planlama | Depo | Üretim | Laboratuvar | Dolum | Sevkiyat | Satın Alma | Not |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Hassas veriler | Fiyatları görür |  |  | G |  |  |  |  |  |  | G |  |
| Hassas veriler | Maliyetleri görür |  |  | G |  |  |  |  |  |  |  |  |
| Ana veriler | Ana veri kartları |  |  | G | G D |  |  |  |  |  |  | okuma: herkes, kişiden kapatılamaz |
| Ana veriler | Birimler, yazıcılar ve etiket ayarları |  |  | G | G |  |  |  |  |  |  | yalnız admin: Değiştirir; okuma: herkes, kişiden kapatılamaz |
| Ana veriler | Firma bilgileri |  |  | G D | G |  |  |  |  |  |  | okuma: herkes, kişiden kapatılamaz |
| Ana veriler | Açık kayıtlar | Okur |  |  |  |  |  |  |  |  |  |  |
| Reçeteler | Reçeteler ve sürümler |  |  |  | G D O |  |  | G D O |  |  |  | okuma: herkes, Açık kayıtlar satırıyla kişiden kapatılabilir |
| Reçeteler | Açık kayıtlar | Okur |  |  |  |  |  |  |  |  |  |  |
| Depo ve stok | Stok sorgu, hareketler ve transfer | G |  |  |  | D |  |  |  |  |  | kilitli: Görür |
| Depo ve stok | Lotlar | G |  |  |  |  |  |  |  |  |  | kilitli: Görür |
| Depo ve stok | Palet etiketleri (SSCC) | G |  |  |  | D | D |  | D | D |  | kilitli: Görür |
| Depo ve stok | Mal kabul |  |  | G | G | G D |  | G |  |  | G | okuma: herkes, Açık kayıtlar satırıyla kişiden kapatılabilir |
| Depo ve stok | Mal kabul fiyat ve masrafları |  |  | D |  |  |  |  |  |  | D |  |
| Depo ve stok | Sayım düzeltme |  |  | G |  | G D O |  |  |  |  |  | okuma: herkes, Açık kayıtlar satırıyla kişiden kapatılabilir |
| Depo ve stok | Lot bloke etme |  |  |  |  |  |  | O |  |  |  |  |
| Depo ve stok | Elle serbest bırakma (D-5) |  |  |  |  |  |  |  |  |  |  | yalnız admin: Onaylar |
| Depo ve stok | Açık kayıtlar | Okur |  |  |  |  |  |  |  |  |  |  |
| Üretim | Üretim emirleri |  |  | G | G D O | G | G |  |  |  |  | okuma: herkes, Açık kayıtlar satırıyla kişiden kapatılabilir |
| Üretim | Malzeme hazırlama |  |  |  |  | G D |  |  |  |  |  | okuma: herkes, Açık kayıtlar satırıyla kişiden kapatılabilir |
| Üretim | Şarj ve tartım |  |  | G | G | G | G D |  |  |  |  | okuma: herkes, Açık kayıtlar satırıyla kişiden kapatılabilir |
| Üretim | Açık kayıtlar | Okur |  |  |  |  |  |  |  |  |  |  |
| Kalite kontrol | Numuneler ve kalite kararı |  |  | G |  |  |  | G D O |  |  |  | okuma: herkes, Açık kayıtlar satırıyla kişiden kapatılabilir |
| Kalite kontrol | Şartlı kabul onayı |  |  | G O |  |  |  |  |  |  |  |  |
| Kalite kontrol | Spesifikasyonlar ve test tanımları |  |  | G |  |  |  | G D O |  |  |  | okuma: herkes, Açık kayıtlar satırıyla kişiden kapatılabilir |
| Kalite kontrol | Açık kayıtlar | Okur |  |  |  |  |  |  |  |  |  |  |
| Dolum | Dolum emirleri |  |  | G | G D O | G |  |  | G |  |  | okuma: herkes, Açık kayıtlar satırıyla kişiden kapatılabilir |
| Dolum | Ambalaj hazırlama |  |  |  |  | G D |  |  |  |  |  | okuma: herkes, Açık kayıtlar satırıyla kişiden kapatılabilir |
| Dolum | Dolum hattı |  |  | G | G | G |  |  | G D |  |  | okuma: herkes, Açık kayıtlar satırıyla kişiden kapatılabilir |
| Dolum | Ambalaj reçeteleri |  |  | G | G D O | G |  |  | G |  |  | okuma: herkes, Açık kayıtlar satırıyla kişiden kapatılabilir |
| Dolum | Dolum emrini geri alma |  |  | D |  |  |  |  |  |  |  |  |
| Dolum | Açık kayıtlar | Okur |  |  |  |  |  |  |  |  |  |  |
| Sevkiyat | Satış siparişleri |  |  | G D O | G | G |  |  |  | G D O |  |  |
| Sevkiyat | Sevkiyatlar ve irsaliye |  |  | G | G | G |  |  |  | G D O |  |  |
| Sevkiyat | Toplama ve yükleme |  |  |  |  | G D |  |  |  |  |  |  |
| Sevkiyat | Müşteriye sevk edilen lotlar |  |  | G |  |  |  |  |  | G |  |  |
| İadeler | İade kayıtları |  |  | G |  | G |  | G |  | G D |  | okuma: herkes, Açık kayıtlar satırıyla kişiden kapatılabilir |
| İadeler | İade teslim alma ve imha |  |  |  |  | D |  |  |  | D |  |  |
| İadeler | Açık kayıtlar | Okur |  |  |  |  |  |  |  |  |  |  |
| İzlenebilirlik | Geri ve ileri izleme, geri çağırma |  |  | G |  |  |  | G |  |  |  |  |
| Satın alma | Satın alma talepleri |  |  | G D | G D | G D | G D |  |  |  | G D |  |
| Satın alma | Talep önerileri |  |  | G | G |  |  |  |  |  | G |  |
| Satın alma | Satın alma siparişleri |  |  | G D O |  | G |  |  |  |  | G D O |  |
| Satın alma | Limit üstü sipariş onayı |  |  | O |  |  |  |  |  |  |  |  |
| Satın alma | Beklenen teslimatlar ve siparişten mal kabul |  |  | G D |  | G D |  |  |  |  | G D |  |
| Satın alma | Tedarikçi performansı |  |  | G |  |  |  |  |  |  | G |  |
| Satın alma | Satın alma ayarları |  |  | G D |  |  |  |  |  |  |  |  |
| Maliyet | Lot maliyetleri ve maliyet raporları |  |  | G D |  |  |  |  |  |  |  |  |
| Maliyet | Gider oranları ve standart maliyetler |  |  | G D |  |  |  |  |  |  |  |  |
| Maliyet | Personel maliyeti |  |  | G D |  |  |  |  |  |  |  | yalnız Yönetim (KVKK) |
| Bakım | Bakım iş emirleri |  |  | G D | G D |  | G D | G D | G D |  |  |  |
| Bakım | Tüm birimlerin iş emirlerini yürütme |  |  | D |  |  |  |  |  |  |  |  |
| Bakım | Bakım planları ve iş emri açma |  |  | G D | G |  | G D | G D | G D |  |  |  |
| Bakım | Arıza bildirimi |  | D |  |  |  |  |  |  |  |  | kilitli: Değiştirir |
| Bakım | Duruşlar |  |  | G D | G D |  | G D | G D | G D |  |  | okuma: rolü olan herkes, kişiden kapatılamaz |
| Bakım | Tank temizliği |  |  | G D | G |  | G D | G | G |  |  |  |
| Bakım | Kalibrasyon |  |  | G | G |  | G | G | G |  |  |  |
| Bakım | Temizliksiz geçişler (D-14) |  |  | G | G |  | G | G D | G |  |  |  |
| Bakım | Bakım ayarları |  |  | G D |  |  |  |  |  |  |  |  |
| İSG ve çevre | Olay bildirimi |  | G D |  |  |  |  |  |  |  |  | kilitli: Görür, Değiştirir |
| İSG ve çevre | Olaylar ve kazalar |  |  | G D |  |  |  |  |  |  |  | yalnız Yönetim (KVKK) |
| İSG ve çevre | GBF arşivi |  |  | G D |  | G |  | G |  |  |  |  |
| İSG ve çevre | Tehlike bilgileri ve H/P ifadeleri |  | G | D |  |  |  | D |  |  |  | kilitli: Görür |
| İSG ve çevre | Depolama limitleri |  |  | G D |  | G |  |  |  |  |  |  |
| İSG ve çevre | Atık |  |  | G D |  |  |  |  |  |  |  |  |
| İSG ve çevre | İSG özeti |  |  | G |  |  |  |  |  |  |  |  |
| İSG ve çevre | İSG ayarları |  |  | G D |  |  |  |  |  |  |  |  |
| Personel | Personel kartları ve özlük belgeleri |  |  | G D |  |  |  |  |  |  |  | yalnız Yönetim (KVKK) |
| Personel | Puantaj ve tatil takvimi |  |  | G D O |  |  |  |  |  |  |  | yalnız Yönetim (KVKK) |
| Personel | Ücretler |  |  | G D |  |  |  |  |  |  |  | yalnız Yönetim (KVKK) |
| Personel | Bordro |  |  | G D O |  |  |  |  |  |  |  | yalnız Yönetim (KVKK) |
| Personel | Personel ayarları |  |  | G D |  |  |  |  |  |  |  | yalnız Yönetim (KVKK) |
| Panolar ve raporlar | Yönetim panosu ve görev süreleri raporu |  |  | G | G |  |  |  |  |  |  |  |
| Panolar ve raporlar | Depo panosu |  |  | G | G | G |  |  |  |  |  |  |
| Panolar ve raporlar | Stok raporları |  |  | G | G | G |  |  |  |  | G |  |
| Panolar ve raporlar | Üretim panosu ve üretim raporu |  |  | G | G |  | G |  |  |  |  |  |
| Panolar ve raporlar | Dolum raporu |  |  | G | G |  |  |  | G |  |  |  |
| Panolar ve raporlar | Laboratuvar panosu ve kalite raporu |  |  | G | G |  |  | G |  |  |  |  |
| Panolar ve raporlar | Sevkiyat panosu |  |  | G | G | G |  |  |  | G |  |  |
| Panolar ve raporlar | Sevkiyat raporu |  |  | G | G |  |  |  |  | G |  |  |
| Canlıya geçiş | Hazırlık listesi |  |  | G | G | G |  |  |  |  |  |  |
| Canlıya geçiş | Canlıya geçiş ayarları |  |  | G D | G | G |  |  |  |  |  |  |
| Canlıya geçiş | Stok karşılaştırma |  |  | G D | G | G D |  |  |  |  |  |  |
| Canlıya geçiş | Sorun bildirimleri listesi |  |  |  |  |  |  |  |  |  |  | yalnız admin: Görür |
| Görevler | Tüm birimlerin görevleri |  |  | G |  |  |  |  |  |  |  |  |
| Sistem | Denetim günlüğü |  |  | G |  |  |  |  |  |  |  | yalnız Yönetim (KVKK) |

Harfler: G görür, D değiştirir, O onaylar; Okur: kayıtları okur (Açık kayıtlar).
