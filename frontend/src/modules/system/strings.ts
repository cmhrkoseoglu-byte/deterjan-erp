// Sistem ekranı metinleri (Faz 5, yalnızca admin).
export const sy = {
  title: "Sistem",
  tabs: { status: "Sistem durumu", users: "Kullanıcılar", device: "Bu cihaz" },
  refresh: "Yenile",
  asOf: (text: string) => `${text} itibarıyla`,
  // Sistem durumu
  statusHelp:
    "Gece yedeği her gece 02:00'de alınır, geri yükleme testi her pazar 04:00'te otomatik yapılır. Sorun olursa sistem yöneticilerine bildirim gider.",
  checkStatus: { ok: "Normal", error: "Sorun", unknown: "Bilinmiyor" },
  since: (text: string) => `${text} itibarıyla`,
  disks: "Disk kullanımı",
  diskDetail: (free: string, total: string) => `Boş: ${free} / ${total}`,
  load: "Sunucu yükü (15 dk)",
  loadDetail: (cpus: number) => `${cpus} işlemci`,
  queue: "Bekleyen arka plan işi",
  unknown: "Bilinmiyor",
  runs: "Son yedekler ve geri yükleme testleri",
  noRuns: "Henüz yedek ya da geri yükleme testi kaydı yok.",
  runDate: "Tarih",
  runKind: "Tür",
  runStatus: "Durum",
  runRows: "Satır",
  runSize: "Boyut",
  runSizeDetail: (db: string, media: string, files: string) =>
    `Veritabanı ${db} · Ekler ${media} (${files} dosya)`,
  runOffsite: "Ayrı konum",
  runMessage: "Mesaj",
  mismatches: (n: number) => `${n} tabloda satır sayısı tutmadı`,
  mismatch: (table: string, expected: string, actual: string) =>
    `${table}: beklenen ${expected}, bulunan ${actual}`,
  // Kullanıcılar
  usersNote:
    "Yeni çalışana buradan hesap açın: sistem geçici şifre üretir, çalışan ilk girişte kendi şifresini belirler. Kullanıcılar silinmez; ayrılan çalışanı pasife alın.",
  newUser: "Yeni kullanıcı",
  edit: "Düzenle",
  moreActions: (name: string) => `${name}: diğer işlemler`,
  you: "Siz",
  tempPassword: "Geçici şifre",
  search: "Ara (kullanıcı adı, ad, e-posta)",
  noUsers: "Kullanıcı bulunamadı.",
  user: "Kullanıcı",
  roles: "Roller",
  state: "Durum",
  lastLogin: "Son giriş",
  never: "Hiç giriş yapmadı",
  inactive: "Pasif",
  locked: "Kilitli",
  superuser: "Süper kullanıcı",
  otpOn: "2FA açık",
  otpOff: "2FA yok",
  unlock: "Kilidi aç",
  resetOtp: "2FA sıfırla",
  confirmUnlock: (name: string) =>
    `${name} kullanıcısının hesap kilidi açılsın mı? Kullanıcı hemen yeniden giriş deneyebilir.`,
  confirmResetOtp: (name: string) =>
    `${name} kullanıcısının iki aşamalı doğrulaması sıfırlansın mı? Telefonunu kaybeden kullanıcı bir sonraki girişte yeniden kurar.`,
  unlocked: (name: string) => `${name} kullanıcısının kilidi açıldı.`,
  otpReset: (name: string) => `${name} kullanıcısının iki aşamalı doğrulaması sıfırlandı.`,
  resetPassword: "Şifre sıfırla",
  confirmResetPassword: (name: string) =>
    `${name} kullanıcısının şifresi sıfırlansın mı? Yeni geçici şifre bir kez gösterilir; kullanıcının açık oturumu kapanır ve girişte kendi şifresini belirler.`,
  passwordReset: (name: string) => `${name} kullanıcısının şifresi sıfırlandı.`,
  deactivate: "Pasife al",
  activate: "Etkinleştir",
  confirmDeactivate: (name: string) =>
    `${name} pasife alınsın mı? Kullanıcı giriş yapamaz, açık oturumu kapanır. Kayıtları ve geçmişi silinmez; istediğinizde yeniden etkinleştirebilirsiniz.`,
  confirmActivate: (name: string) =>
    `${name} yeniden etkinleştirilsin mi? Kullanıcı eski şifresiyle giriş yapabilir; hatırlamıyorsa şifresini sıfırlayın.`,
  deactivated: (name: string) => `${name} pasife alındı.`,
  activated: (name: string) => `${name} yeniden etkinleştirildi.`,
  // Kullanıcı formu
  formNewTitle: "Yeni kullanıcı",
  formEditTitle: (name: string) => `${name}: bilgileri düzenle`,
  username: "Kullanıcı adı",
  usernameHelp:
    "Girişte kullanılır, sonradan değiştirilemez. Küçük harf, rakam, nokta, alt çizgi ve tire; Türkçe karakter olmadan (ör. ahmet.yilmaz).",
  usernameInvalid: "Kullanıcı adı kurala uymuyor (ör. ahmet.yilmaz).",
  fullName: "Ad soyad",
  phone: "Telefon",
  email: "E-posta",
  emailInvalid: "Geçerli bir e-posta adresi girin.",
  roleField: "Roller",
  rolesHelp:
    "Kullanıcı yalnızca rollerinin ekranlarında işlem yapar; birden fazla rol seçilebilir.",
  noRoleWarning: "Rol seçmediniz: kullanıcı sistemde işlem yapamaz.",
  ownAdminLocked: "Kendi sistem yöneticisi rolünüzü kaldıramazsınız.",
  required: "Gerekli",
  createAccount: "Hesabı aç",
  save: "Kaydet",
  cancel: "Vazgeç",
  saved: (name: string) => `${name} kullanıcısının bilgileri kaydedildi.`,
  // Geçici şifre
  tempTitle: "Geçici şifre",
  tempIntro: (name: string, username: string) =>
    `${name} (kullanıcı adı: ${username}) için geçici şifre:`,
  tempWarning:
    "Bu şifre bir daha gösterilmez. Çalışana yüz yüze ya da güvenli bir yoldan iletin; ilk girişte kendi şifresini belirleyecek.",
  copy: "Kopyala",
  copied: "Kopyalandı",
  tempDone: "Şifreyi ilettim, kapat",
  // Bu cihaz
  deviceTitle: "Saha tableti",
  deviceIsField: "Bu tarayıcı saha tableti olarak işaretli.",
  deviceNotField: "Bu tarayıcı saha tableti olarak işaretli değil.",
  deviceHelp: (minutes: number) =>
    `Saha tabletinde (üretim, dolum, depo, sevkiyat) kim giriş yaparsa yapsın oturum ${minutes} dakika işlem yapılmayınca kapanır. Bu işareti her tablette bir kez, o tabletin tarayıcısından açın.`,
  deviceSwitch: "Bu tarayıcı saha tableti",
  deviceCurrentIdle: (minutes: number) =>
    `Bu tarayıcıda şu anki hareketsizlik süresi: ${minutes} dakika`,
  deviceMarked: "Bu tarayıcı saha tableti olarak işaretlendi.",
  deviceUnmarked: "Saha tableti işareti kaldırıldı.",
} as const;
