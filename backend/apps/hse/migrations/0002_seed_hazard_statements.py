from django.db import migrations

# Sık kullanılan H, P ve EUH ifadeleri (SEA Yönetmeliği Türkçe metinleri). Yenileri arayüzden
# eklenir; "..." içeren ifadelerde etikette ilgili bilgi tamamlanır.
STATEMENTS = [
    ("H", "H225", "Kolay alevlenir sıvı ve buhar."),
    ("H", "H226", "Alevlenir sıvı ve buhar."),
    ("H", "H272", "Yangını şiddetlendirebilir; oksitleyicidir."),
    ("H", "H290", "Metallere karşı aşındırıcı olabilir."),
    ("H", "H301", "Yutulması halinde toksiktir."),
    ("H", "H302", "Yutulması halinde zararlıdır."),
    ("H", "H304", "Yutulması ve solunum yoluna nüfuz etmesi halinde öldürücü olabilir."),
    ("H", "H312", "Cilt ile temasında zararlıdır."),
    ("H", "H314", "Ciddi cilt yanıklarına ve göz hasarına yol açar."),
    ("H", "H315", "Cilt tahrişine yol açar."),
    ("H", "H317", "Alerjik cilt reaksiyonuna yol açabilir."),
    ("H", "H318", "Ciddi göz hasarına yol açar."),
    ("H", "H319", "Ciddi göz tahrişine yol açar."),
    ("H", "H331", "Solunması halinde toksiktir."),
    ("H", "H332", "Solunması halinde zararlıdır."),
    (
        "H",
        "H334",
        "Solunması halinde alerji veya astım belirtilerine ya da solunum güçlüğüne yol açabilir.",
    ),
    ("H", "H335", "Solunum yolu tahrişine yol açabilir."),
    ("H", "H336", "Rehavet veya baş dönmesine yol açabilir."),
    ("H", "H400", "Sucul ortamda çok toksiktir."),
    ("H", "H410", "Sucul ortamda uzun süre kalıcı etkisiyle çok toksiktir."),
    ("H", "H411", "Sucul ortamda uzun süre kalıcı etkisiyle toksiktir."),
    ("H", "H412", "Sucul ortamda uzun süre kalıcı etkisiyle zararlıdır."),
    ("EUH", "EUH031", "Asitlerle temasında toksik gaz açığa çıkar."),
    ("EUH", "EUH066", "Tekrarlanan maruziyet ciltte kuruluk veya çatlamaya yol açabilir."),
    (
        "EUH",
        "EUH206",
        "Dikkat! Diğer ürünlerle birlikte kullanmayın. Tehlikeli gazlar (klor) açığa çıkabilir.",
    ),
    ("EUH", "EUH208", "... içerir. Alerjik reaksiyona yol açabilir."),
    ("EUH", "EUH210", "Talep edilmesi halinde güvenlik bilgi formu temin edilebilir."),
    (
        "EUH",
        "EUH401",
        "İnsan sağlığı ve çevreye yönelik riskleri önlemek için kullanım talimatlarına uyun.",
    ),
    ("P", "P101", "Tıbbi tavsiye gerekirse, ürünün kabını veya etiketini yanınızda bulundurun."),
    ("P", "P102", "Çocukların erişebileceği yerlerden uzak tutun."),
    ("P", "P103", "Kullanmadan önce etiketi okuyun."),
    (
        "P",
        "P210",
        "Isıdan, sıcak yüzeylerden, kıvılcımdan, açık alevden ve diğer tutuşturucu kaynaklardan "
        "uzak tutun. Sigara içilmez.",
    ),
    ("P", "P233", "Kabı sıkıca kapalı tutun."),
    ("P", "P234", "Sadece orijinal kabında saklayın."),
    ("P", "P260", "Tozunu/dumanını/gazını/sisini/buharını/spreyini solumayın."),
    ("P", "P261", "Tozunu/dumanını/gazını/sisini/buharını/spreyini solumaktan kaçının."),
    ("P", "P264", "Elleçlemeden sonra elleri iyice yıkayın."),
    ("P", "P270", "Bu ürünü kullanırken yemek yemeyin, içecek içmeyin veya sigara içmeyin."),
    ("P", "P271", "Sadece dış mekânda veya iyi havalandırılan alanlarda kullanın."),
    ("P", "P273", "Çevreye verilmesinden kaçının."),
    ("P", "P280", "Koruyucu eldiven/koruyucu giysi/göz koruyucu/yüz koruyucu kullanın."),
    (
        "P",
        "P301+P310",
        "YUTULURSA: Hemen ULUSAL ZEHİR DANIŞMA MERKEZİNİN 114 no'lu telefonunu veya doktoru "
        "arayın.",
    ),
    (
        "P",
        "P301+P312",
        "YUTULURSA: Kendinizi iyi hissetmiyorsanız ULUSAL ZEHİR DANIŞMA MERKEZİNİN 114 no'lu "
        "telefonunu veya doktoru arayın.",
    ),
    ("P", "P301+P330+P331", "YUTULURSA: Ağzınızı çalkalayın. Kusturmaya ÇALIŞMAYIN."),
    ("P", "P302+P352", "CİLT İLE TEMAS HALİNDE İSE: Bol su ile yıkayın."),
    (
        "P",
        "P303+P361+P353",
        "CİLT (veya saç) İLE TEMAS HALİNDE İSE: Kirlenmiş/kontamine olmuş tüm giysileri hemen "
        "çıkarın. Cildinizi su ile durulayın [veya duş alın].",
    ),
    (
        "P",
        "P304+P340",
        "SOLUNURSA: Kişiyi temiz havaya çıkarın ve rahat nefes alabileceği bir pozisyonda tutun.",
    ),
    (
        "P",
        "P305+P351+P338",
        "GÖZ İLE TEMAS HALİNDE İSE: Su ile birkaç dakika dikkatlice durulayın. Takılıysa ve "
        "yapması kolaysa kontakt lensleri çıkarın. Durulamaya devam edin.",
    ),
    (
        "P",
        "P310",
        "Hemen ULUSAL ZEHİR DANIŞMA MERKEZİNİN 114 no'lu telefonunu veya doktoru arayın.",
    ),
    (
        "P",
        "P312",
        "Kendinizi iyi hissetmiyorsanız ULUSAL ZEHİR DANIŞMA MERKEZİNİN 114 no'lu telefonunu "
        "veya doktoru arayın.",
    ),
    ("P", "P332+P313", "Ciltte tahriş oluşursa: Tıbbi yardım/bakım alın."),
    ("P", "P333+P313", "Ciltte tahriş veya kızarıklık oluşursa: Tıbbi yardım/bakım alın."),
    ("P", "P337+P313", "Göz tahrişi devam ederse: Tıbbi yardım/bakım alın."),
    ("P", "P362+P364", "Kirlenmiş giysileri çıkarın ve tekrar kullanmadan önce yıkayın."),
    ("P", "P370+P378", "Yangın durumunda: Söndürmek için ... kullanın."),
    ("P", "P391", "Döküntüyü toplayın."),
    ("P", "P403+P233", "İyi havalandırılan bir yerde depolayın. Kabı sıkıca kapalı tutun."),
    ("P", "P405", "Kilit altında saklayın."),
    ("P", "P501", "İçeriği/kabı yerel/ulusal mevzuata uygun olarak bertaraf edin."),
]


def seed_statements(apps, schema_editor):
    HazardStatement = apps.get_model("hse", "HazardStatement")
    for kind, code, text in STATEMENTS:
        HazardStatement.objects.get_or_create(code=code, defaults={"kind": kind, "text": text})


class Migration(migrations.Migration):
    dependencies = [("hse", "0001_initial")]

    operations = [migrations.RunPython(seed_statements, migrations.RunPython.noop)]
