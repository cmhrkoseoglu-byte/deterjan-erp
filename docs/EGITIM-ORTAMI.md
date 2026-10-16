# Eğitim ortamı (bulutta, demo veri)

Fabrika sunucusu (D-20) hazır olana kadar kullanıcılar sistemi bir **eğitim sunucusunda** dener. Burada
yalnızca demo veri vardır; her ekranın altında turuncu **"EĞİTİM ORTAMI"** şeridi görünür. Gerçek
sayım, gerçek müşteri ya da çalışan bilgisi **girilmez**. Kişisel veri olmadığı için sunucunun yurt
dışında olması KVKK açısından sorun değildir. Canlı kullanım fabrika sunucusunda başlar
(`docs/KURULUM.md`, `docs/GECIS-PLANI.md`); eğitim sunucusundaki kayıtlar oraya taşınmaz.

## 1. Sunucuyu açın

Herhangi bir bulut sağlayıcıda Ubuntu 24.04 sanal sunucu:

| | En az | Örnek |
|---|---|---|
| İşlemci / bellek | 4 vCPU, 8 GB | Hetzner CX32 (ayda yaklaşık 8 €), DigitalOcean, Turhost, Natro vb. |
| Disk | 40 GB | |
| Ağ | Genel IPv4 adresi; 22, 80 ve 443 portları açık | |

Sunucu oluşturma ekranında **"Cloud config" / "User data"** kutusu varsa aşağıdakini yapıştırın ve
şifreyi değiştirin; sunucu açılınca kurulum kendiliğinden yapılır (10-15 dakika):

```bash
#!/bin/bash
export EGITIM_SIFRE='Buraya-En-Az-10-Karakter'
curl -fsSL https://raw.githubusercontent.com/cmhrkoseoglu-byte/deterjan-erp/main/scripts/egitim-kur.sh | bash >/var/log/egitim-kur.log 2>&1
```

Kutu yoksa sunucuya SSH ile root olarak bağlanıp aynı iki satırı (`export` ve `curl`) çalıştırın.

Şifre kuralları: en az 10 karakter; harf, rakam ve `. _ @ % + = : , ! -` (Türkçe harf, boşluk ve tırnak
olmasın). `Demo.12345` kabul edilmez, çünkü sunucu internete açıktır.

## 2. Linki paylaşın

Adres, sunucunun IP'sinin noktaları tire yapılmış hâlidir: IP `65.21.10.7` ise
**`https://65-21-10-7.sslip.io`**. Alan adı satın almak gerekmez; sertifika Let's Encrypt'ten
ücretsiz alınır ve kendiliğinden yenilenir. Firmanın alan adını kullanmak isterseniz DNS'te
`egitim.firma.com.tr` → sunucu IP'si kaydını açıp `EGITIM_ADRES=egitim.firma.com.tr` ekleyin.

Giriş: kullanıcı adı rol kodudur, şifre hepsi için `EGITIM_SIFRE`:

| Kullanıcı adı | Rol |
|---|---|
| `yonetim` | Yönetim |
| `planlama` | Planlama |
| `depo` | Depo |
| `uretim` | Üretim |
| `laboratuvar` | Laboratuvar |
| `dolum` | Dolum |
| `sevkiyat` | Sevkiyat |
| `satin_alma` | Satın alma |
| `admin` | Sistem yöneticisi (yalnızca eğitimi yürüten kişi) |

Her rolün kılavuzu sistemde **Yardım** menüsündedir. Ortak demo hesaplarını birden çok kişi
kullandığı için bu ortamda iki aşamalı doğrulama kapalıdır; canlı sunucuda admin ve yönetim için
zorunludur.

## 3. İşletim

Sunucuda root olarak:

```bash
cd /srv/deterjan-erp
cat /root/egitim-bilgi.txt                       # adres ve kullanıcılar
tail -f /var/log/egitim-kur.log                  # kurulum günlüğü
EGITIM_SIFRE='...' bash scripts/egitim-kur.sh    # güncelle (son sürüm) ya da şifreyi değiştir
scripts/prod-compose.sh ps                       # servis durumları
```

Demo veriyi sıfırlamak (herkesin girdiği deneme kayıtları silinir):

```bash
scripts/prod-compose.sh down -v && EGITIM_SIFRE='...' bash scripts/egitim-kur.sh
```

İş bitince sunucuyu bulut panelinden silmek yeterlidir; içinde gerçek veri yoktur.

## Teknik ayrıntı

`scripts/egitim-kur.sh` canlı kurulumla aynı compose dosyalarını (`scripts/prod-compose.sh`) kullanır,
yalnızca `.env.prod` içinde şunları ayarlar: `TRAINING_MODE=true` (demo komutlarına izin verir,
arayüz şeridini açar), `DEMO_USER_PASSWORD`, `OTP_REQUIRED_ROLES=` (boş), `INTERNAL_NETWORKS=127.0.0.1/32`
(yönetim paneli ve API belgeleri internetten kapalı), `WEB_CONCURRENCY=2`. Güvenlik duvarı (ufw) yalnızca
22, 80 ve 443'ü açar. Canlı sunucuda `TRAINING_MODE` kapalıdır ve demo komutları çalışmaz; eğitim
modunda zayıf ya da örnek demo şifresiyle uygulama hiç açılmaz (`config/settings/prod.py`).
