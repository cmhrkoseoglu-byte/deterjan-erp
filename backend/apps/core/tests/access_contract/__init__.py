"""Yetki sözleşme testi: kişiye özel ayar yokken erişim bugünküyle aynıdır (plan §5.5).

`docs/plan/kisi-yetkileri.md` §5.5'teki parçalar burada toplanır:

1. Uç nokta anlık görüntüsü (`test_endpoints.py`): her API uç noktası 14 personayla denenir;
   izin, 401 ya da 403 kararı `data/endpoints.json` dosyasında dondurulur.
2. Sondalar: yetki kararının işlevin içinde verildiği yerler (pano listeleri, fiyat ve maliyet
   alanları, görev alıcıları...) aynı biçimde dondurulur.

Anlık görüntüler bugünkü koddan (262dede) üretildi. Bir adım bir kararı değiştirirse test, fark
`allowlist.py`'deki bir maddeye (planın §8'i) bağlı değilse kırılır. Anlık görüntüyü yeniden
üretmek (`ACCESS_SNAPSHOT_UPDATE=1`) yalnız sahibin onayı ve DECISIONS kaydıyla yapılır.
"""
