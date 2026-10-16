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
    "Kullanıcılar Yönetim panelinden eklenir ve roller oradan atanır. Bu ekrandan kilitli hesabı açabilir ve telefonunu kaybeden kullanıcının iki aşamalı doğrulamasını sıfırlayabilirsiniz.",
  usersAdminLink: "Yönetim panelinde kullanıcılar",
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
