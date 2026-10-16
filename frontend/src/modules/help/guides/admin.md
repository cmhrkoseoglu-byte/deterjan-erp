# Sistem yöneticisi

Sistem yöneticisi; kullanıcıları ve rollerini yönetir, kullanıcıların gönderdiği sorun bildirimlerini çözer, etiket yazıcılarını ve etiket ayarlarını tutar. Yönetici her menüyü görür.

## Kullanıcı açma ve rol verme

Kullanıcılar Django yönetim panelinde tutulur. Sol menüdeki **Yönetim paneli** bağlantısı paneli açar (adres: /admin/). Uygulamaya giriş yaptığınız oturumla girersiniz.

1. Panelde **Kullanıcılar**'ı açın ve sağ üstteki **Kullanıcı ekle**'ye basın.
2. Kullanıcı adını, adını soyadını, e-postasını ve iki kez geçici şifreyi girip kaydedin.
3. Açılan kullanıcı sayfasında **Roller ve yetkiler** bölümüne inin. **Gruplar** listesinden kişinin rollerini seçin (depo, uretim, laboratuvar gibi). Bir kişiye birden fazla rol verilebilir.
4. **Etkin** işaretli olsun ve **Kaydet**'e basın.
5. Geçici şifreyi kişiye kendiniz iletin.

![Yönetim panelinde kullanıcı listesi](/kilavuz/admin-kullanicilar.jpg)

> Kullanıcı silinmez. İşten ayrılan kişinin **Etkin** işaretini kaldırın; geçmiş kayıtlarda adı kalır.

- **Görev durumu** yalnızca yönetim paneline girecek kişilere verilir. Uygulamayı kullanmak için gerekmez.
- Rollerin kendisi sabittir ve `seed_roles` komutuyla oluşur; panelden eklenmez ya da silinmez.
- Şifresini unutan kullanıcının sayfasında şifre alanının altındaki form bağlantısıyla yeni şifre verin.
- Paneldeki her değişiklik denetim günlüğüne yazılır.

## Sorun bildirimleri

Kullanıcı sağ üstteki **Sorun bildir** simgesiyle bildirim gönderince **Görevlerim**'e "Sorun bildirimi: SB-..." görevi düşer.

1. Görevde **Kayda git**'e basın ya da **Canlıya geçiş > Sorun bildirimleri** sekmesini açın.
2. Bildirimin sayfasında kullanıcının açıklaması, sorunun yaşandığı sayfa, tarayıcı ve ekran boyutu ile ekran görüntüsü vardır.
3. Sayfadaki bağlantıyla sorunlu ekranı açıp sorunu kendiniz deneyin.
4. Kullanıcıya kaydın altındaki yorumdan yanıt verin. `@` ile kullanıcıdan bahsederseniz bildirim alır.
5. Sorun çözülünce ya da yazılım ekibine iletilince görevde **Tamamla**'ya basın ve kısa not yazın.

![Sorun bildirimleri listesi](/kilavuz/admin-sorunlar.jpg)

![Sorun bildirimi sayfası](/kilavuz/admin-sorun.jpg)

> **Sorun bildirimleri** sekmesini yalnızca sistem yöneticisi görür. Bildiren kullanıcı yalnızca kendi bildirimini açabilir.

## Etiket yazıcıları

1. **Ana veriler > Yazıcılar** sekmesinde **Yeni**'ye basın.
2. **Kod**, **Ad**, **IP adresi**, **Port** (Zebra yazıcılarda genelde 9100), **Çözünürlük (dpi)** ve yazıcının durduğu **Lokasyon**'u girip kaydedin.
3. Satırdaki **Deneme etiketi** simgesine basın. Yazıcıdan deneme etiketi çıkmalıdır.
4. Çalışmayan ya da kaldırılan yazıcıyı pasife alın.

**Ana veriler > Etiket ayarları** sekmesinde **Etikette firma adı**, **GS1 firma öneki** ve **Varsayılan yazıcı** girilir. GS1 firma öneki girilince palet etiketi (SSCC) açılır.

![Etiket ayarları](/kilavuz/admin-etiket-ayarlari.jpg)

> Yazıcı tanımlı değilse etiketler PDF olarak basılır. Lokasyon etiketleri **Ana veriler > Lokasyonlar** sekmesindeki yazıcı simgesiyle basılır.

## Diğer yönetici işleri

- **Elle serbest bırak**: Lot sayfasında yalnızca yöneticiye görünür. Olağan serbest bırakma laboratuvar kararıyla yapılır; bu düğme istisnai durumlar içindir ve gerekçe denetim günlüğüne yazılır.
- **Canlıya geçiş > Hazırlık** listesindeki "Kullanıcılar" ve "Etiket yazıcıları" maddeleri sizin sorumluluğunuzdadır.
- Kullanıcı bir ekranı göremediğini söylerse önce rollerini kontrol edin. Menü ve sekmeler role göre açılır.
