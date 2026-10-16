# Üretim (tablet)

Üretim; depo malzemeyi hazırladıktan sonra tankta şarjı başlatır, her malzemeyi tartıp kaydeder ve şarjı bitirir. Bu ekranlar tablette, büyük düğmelerle ve el okuyucuyla kullanılır.

## Şarj başlatma

Depo **Malzeme hazır** deyince **Görevlerim**'e üretim görevi düşer.

1. Menüden **Üretim**'e dokunun. **Şarjlar** sekmesi açılır.
2. Üstte **Devam ediyor** listesi, altta **Şarj başlat** listesi vardır. Başlatılacak emre dokunun.
3. Emir sayfasında **Şarj başlat**'a basın.
4. **Şarj miktarı** önerilen değerle gelir. Tank kapasitesi yetmiyorsa emir birden çok şarja bölünür; kalan miktar sonraki şarja kalır.
5. Tankta önceki üründen kalan temizlik uyarısı çıkarsa önce **Temizlik kaydı gir** ile temizliği kaydedin.
6. Onaylayın. Şarj sayfası açılır, çıktı lotu (B-...) karantinada oluşur.

![Şarjlar sekmesi](/kilavuz/uretim-sarjlar.jpg)

## Tartım

Şarj sayfasında her malzeme bir karttır. Kartta tartılan / planlanan miktar ve durum yazar: **Tartılmadı**, **Eksik**, **Tolerans içinde**, **Tolerans dışı (fazla)**.

![Şarj sayfası: malzeme kartları](/kilavuz/uretim-sarj.jpg)

1. Sıradaki malzemenin kartına dokunun. Altında **Talimat** görünür; okuyun.
2. **Terazi** listesinden kullandığınız teraziyi seçin. Su satırında terazi sorulmaz.
3. Malzemenin lot etiketini **Lot barkodu** alanına okutun.
4. Teraziyi okuyup **Tartılan miktar** alanına yazın. Altta sapma ve tolerans durumu anında görünür.
5. Büyük **Tartımı kaydet** düğmesine basın. Kart yeşile döner, sıradaki karta geçin.
6. Kaydedilen tartımlar sayfanın altında **Tartım kayıtları** tablosunda listelenir.

![Tartım: terazi, lot ve miktar](/kilavuz/uretim-tartim.jpg)

> Tolerans dışı tartımda **Sapma notu** zorunludur. Ne olduğunu kısaca yazın; planlama ve laboratuvar görür.

> Kalibrasyonu geçmiş ya da duruştaki terazi listede seçilemez. Kalibrasyonu yaklaşan terazide sarı uyarı çıkar; laboratuvara haber verin.

## Lot okutulamıyorsa

- Lot numarasını **Lot barkodu** alanına elle yazıp Enter'a basın.
- Ya da **Kullanılabilir lotlar** tablosunda lotun satırına dokunun. Tek lot varsa kendiliğinden seçilidir.
- Yanlış malzemenin lotunu okutursanız kırmızı uyarı çıkar ve uyarı sesi duyulur. Kaydedilmez.
- Tabloda lot yoksa malzeme üretim alanına hazırlanmamıştır. Depoyu arayın ya da kayda yorum yazın.
- Etiket okunmuyorsa depodan lot sayfasındaki **Etiket yazdır** ile yeni etiket isteyin.

## Şarjı bitirme

1. Tüm malzemeler tartılınca üstteki **Şarjı bitir**'e basın.
2. **Çıktı miktarı**'nı (tanktaki ürün) girin. Verim kendiliğinden hesaplanır.
3. Toleransın altında kalan satır varsa **Bitiş notu** zorunludur.
4. Onaylayın. Laboratuvara numune analizi görevi düşer. Lot serbest kalınca dolum yapılabilir.

![Şarjı bitir penceresi](/kilavuz/uretim-sarj-bitir.jpg)

> Tankta, hatta ya da terazide arıza varsa **Görevlerim** ekranındaki **Arıza bildir** düğmesini kullanın. Ekran hata veriyorsa sağ üstteki **Sorun bildir** simgesine basın.
