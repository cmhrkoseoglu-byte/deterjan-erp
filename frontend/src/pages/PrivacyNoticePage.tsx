import { Alert, Anchor, Container, List, Stack, Text, Title } from "@mantine/core";
import { IconAlertTriangle } from "@tabler/icons-react";
import { Link } from "react-router-dom";

/**
 * Hukuk danışmanı onayladığında `true` yapılır; o zamana kadar sayfa "taslak" uyarısıyla görünür
 * (docs/plan/musteri-siparis-takibi.md §4.7, DECISIONS 2026-11-20). Köşeli parantezli yerler
 * firmanın bilgileriyle doldurulur.
 */
const APPROVED = false;

/**
 * KVKK aydınlatma metni (m.10): giriş yapmadan açılır; giriş ekranından bağlantıyla gelinir.
 * Portal kullanıcıları (müşteri ve tedarikçi yetkilileri) ve çalışanlar için ortaktır.
 */
export function PrivacyNoticePage() {
  return (
    <Container size="md" py="xl">
      <Stack>
        <Anchor component={Link} to="/login" size="sm">
          Giriş sayfasına dön
        </Anchor>
        <Title order={2}>Kişisel verilerin korunması aydınlatma metni</Title>
        {!APPROVED && (
          <Alert color="yellow" icon={<IconAlertTriangle size={18} />} title="Taslak">
            Bu metin taslaktır; şirketin hukuk danışmanı onaylayınca yayımlanacaktır.
          </Alert>
        )}
        <Text>
          Bu metin, 6698 sayılı Kişisel Verilerin Korunması Kanunu'nun (KVKK) 10. maddesi uyarınca,
          bu sistemi kullanan çalışanlarımızı ve sisteme kendi hesabıyla giren müşteri ve tedarikçi
          yetkililerini bilgilendirmek için hazırlanmıştır.
        </Text>

        <Title order={4}>Veri sorumlusu</Title>
        <Text>
          [Şirket unvanı], [adres], MERSİS no: [MERSİS no]. İletişim: [KVKK başvuru e-posta adresi].
        </Text>

        <Title order={4}>Hangi kişisel verileri işliyoruz?</Title>
        <List spacing="xs">
          <List.Item>
            Kimlik ve iletişim: ad soyad, kullanıcı adı, e-posta, telefon; bağlı olduğunuz firmanın
            adı.
          </List.Item>
          <List.Item>
            Hesap güvenliği: şifrenin geri çevrilemez özeti; kurarsanız iki aşamalı doğrulama
            anahtarı ve kurtarma kodlarının özetleri.
          </List.Item>
          <List.Item>
            İşlem güvenliği: giriş, çıkış ve başarısız giriş kayıtları, IP adresi, sistemde
            yaptığınız işlemlerin kaydı (ör. bir irsaliyeyi indirdiğiniz).
          </List.Item>
          <List.Item>
            Ticari ilişki: firmanızın siparişleri, sevkiyatları ya da teslimatları ve cari hesap
            hareketleri.
          </List.Item>
        </List>

        <Title order={4}>Hangi amaçla ve hangi hukuki sebeple?</Title>
        <Text>
          Sisteme girişinizi sağlamak, firmanızla aramızdaki sipariş, sevkiyat, teslimat ve cari
          hesap ilişkisini size göstermek, hesap güvenliğini korumak ve yasal kayıt
          yükümlülüklerimizi yerine getirmek için. Hukuki sebepler: sözleşmenin kurulması ve ifası
          (KVKK m.5/2-c), hukuki yükümlülüğümüzün yerine getirilmesi (m.5/2-ç) ve temel hak ve
          özgürlüklerinize zarar vermemek kaydıyla meşru menfaatimiz (bilgi güvenliği; m.5/2-f).
        </Text>

        <Title order={4}>Kimlere aktarılır?</Title>
        <Text>
          Verileriniz yalnızca bu hizmeti yürütmek için yetkilendirilmiş çalışanlarımızca görülür.
          Kanunen yetkili kamu kurumlarına ve barındırma hizmeti aldığımız [barındırma firması,
          Türkiye] dışında üçüncü kişilere aktarılmaz; yurt dışına aktarım yapılmaz.
        </Text>

        <Title order={4}>Nasıl toplanır ve ne kadar saklanır?</Title>
        <Text>
          Hesabınız şirketimizce açılırken ve sistemi kullandıkça elektronik ortamda toplanır. Hesap
          bilgileri ticari ilişki sürdükçe, işlem kayıtları ticari kayıtların yasal saklama süresi
          (10 yıl) boyunca saklanır; giriş kayıtlarındaki IP adresi 1 yıl sonra silinir.
        </Text>

        <Title order={4}>Haklarınız</Title>
        <Text>
          KVKK m.11 uyarınca kişisel verilerinizin işlenip işlenmediğini öğrenme, bilgi isteme,
          düzeltilmesini, silinmesini ya da yok edilmesini isteme, aktarıldığı kişileri öğrenme,
          itiraz etme ve zararın giderilmesini talep etme haklarınız vardır. Başvurularınızı [KVKK
          başvuru e-posta adresi] adresine ya da yazılı olarak [adres] adresine iletebilirsiniz.
        </Text>
      </Stack>
    </Container>
  );
}
