# Sistem yöneticisi

Sistem yöneticisi; kullanıcıları ve rollerini yönetir, kullanıcıların gönderdiği sorun bildirimlerini çözer, etiket yazıcılarını ve etiket ayarlarını tutar. Yönetici her menüyü görür.

## Kullanıcı açma ve rol verme

Kullanıcılar **Sistem > Kullanıcılar** ekranında yönetilir. Bu ekranı yalnızca sistem yöneticisi görür.

1. **Yeni kullanıcı**'ya basın.
2. **Ad soyad**'ı yazın. **Kullanıcı adı** ad soyaddan önerilir (Ahmet Yılmaz → ahmet.yilmaz); isterseniz değiştirin. Kullanıcı adı küçük harf, rakam, nokta, alt çizgi ve tireden oluşur, Türkçe karakter içermez ve sonradan değiştirilemez.
3. Varsa telefonu ve e-postayı girin, kişinin **Roller**ini işaretleyin. Bir kişiye birden fazla rol verilebilir.
4. **Hesabı aç**'a basın. Sistem bir **geçici şifre** üretir ve **yalnızca bir kez** gösterir. **Kopyala** ile alın ya da not edin ve kişiye yüz yüze ya da güvenli bir yoldan iletin.
5. Kişi geçici şifreyle girince önce kendi şifresini belirler; o zamana kadar başka ekran açılmaz. Rolü gerektiriyorsa (sistem yöneticisi, yönetim) ardından iki aşamalı doğrulamayı kurar.

![Kullanıcılar ekranı](/kilavuz/admin-kullanicilar.jpg)

> Kullanıcı silinmez. İşten ayrılan kişiyi satırdaki **⋯ > Pasife al** ile pasife alın: giriş yapamaz, açık oturumu kapanır, geçmiş kayıtlarda adı kalır. Gerekirse **⋯ > Etkinleştir** ile geri açın.

- **Düzenle**: ad soyad, telefon, e-posta ve rolleri değiştirir. Kendi sistem yöneticisi rolünüzü kaldıramazsınız; sistemde her zaman en az bir aktif yönetici kalır.
- **⋯ > Şifre sıfırla**: şifresini unutan kişiye yeni geçici şifre üretir (bir kez gösterilir). Kişinin açık oturumu kapanır, hesabı kilitliyse kilit açılır; kişi girişte yeniden kendi şifresini belirler. Kendi şifrenizi **Güvenlik** sayfasından değiştirirsiniz.
- **Kilidi aç**: çok sayıda hatalı deneme yüzünden kilitlenen hesabı hemen açar.
- **2FA sıfırla**: telefonunu kaybeden kişinin iki aşamalı doğrulamasını sıfırlar; kişi sonraki girişte yeniden kurar.
- **Geçici şifre** rozeti kişinin henüz kendi şifresini belirlemediğini gösterir.
- Rollerin kendisi sabittir ve `seed_roles` komutuyla oluşur; eklenmez ya da silinmez.
- Bu ekrandaki her değişiklik denetim günlüğüne yazılır; şifreler günlüğe yazılmaz.
- Yönetim paneli (/admin/) yalnızca iç ağdan açılır; kullanıcı işleri için gerekmez.

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
