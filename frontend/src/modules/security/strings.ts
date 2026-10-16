// Güvenlik sayfası metinleri (Faz 5: şifre, iki aşamalı doğrulama, oturum).
export const st = {
  title: "Güvenlik",
  setupRequiredTitle: "İki aşamalı doğrulama zorunlu",
  setupRequired:
    "Rolünüz için iki aşamalı doğrulama zorunludur. Sistemi kullanmaya devam etmek için aşağıdaki adımlarla doğrulayıcı uygulamayı kurun.",
  // Şifre
  passwordTitle: "Şifre değiştir",
  oldPassword: "Mevcut şifre",
  newPassword: "Yeni şifre",
  confirmPassword: "Yeni şifre (tekrar)",
  passwordMismatch: "Yeni şifreler aynı değil",
  required: "Gerekli",
  passwordRules: "Şifre kuralları",
  changePassword: "Şifreyi değiştir",
  passwordChanged: "Şifreniz değiştirildi.",
  // İki aşamalı doğrulama
  otpTitle: "İki aşamalı doğrulama",
  otpIntro:
    "Girişte şifrenize ek olarak telefonunuzdaki doğrulayıcı uygulamanın ürettiği 6 haneli kod istenir.",
  otpOn: "Açık",
  otpOff: "Kapalı",
  setup: "Kur",
  setupSteps: [
    "Google Authenticator ya da Microsoft Authenticator uygulamasını açın.",
    "QR kodu okutun.",
    "Uygulamadaki 6 haneli kodu girin.",
  ],
  qrAlt: "Doğrulayıcı uygulama için QR kod",
  manualKey: "QR kodu okutamıyorsanız bu anahtarı uygulamaya elle girin:",
  code: "6 haneli kod",
  codeRequired: "Kod gerekli",
  confirm: "Doğrula ve aç",
  cancel: "Vazgeç",
  otpEnabled: "İki aşamalı doğrulama açıldı.",
  recoveryRemaining: (n: number) => `Kalan kurtarma kodu: ${n}`,
  recoveryLow: "Kurtarma kodunuz azaldı; yenilerini alın.",
  newRecoveryCodes: "Yeni kurtarma kodları",
  newRecoveryIntro:
    "Yeni kodlar oluşturulunca eski kurtarma kodları geçersiz olur. Uygulamadaki güncel kodu girin.",
  create: "Oluştur",
  disable: "Kapat",
  disableTitle: "İki aşamalı doğrulamayı kapat",
  disableIntro: "Kapatmak için şifrenizi girin.",
  disabled: "İki aşamalı doğrulama kapatıldı.",
  cannotDisable: "Rolünüz için zorunlu olduğundan iki aşamalı doğrulama kapatılamaz.",
  password: "Şifre",
  // Kurtarma kodları
  codesTitle: "Kurtarma kodları",
  codesWarning: "Bu kodları güvenli bir yere yazın; bir daha gösterilmez.",
  codesHelp:
    "Telefonunuz yanınızda değilse girişte doğrulama kodu yerine bu kodlardan birini girebilirsiniz. Her kod bir kez kullanılır.",
  copy: "Kopyala",
  copied: "Kopyalandı",
  print: "Yazdır",
  codesSaved: "Kodları kaydettim",
  // Oturum
  sessionTitle: "Oturum",
  idleTimeout: (minutes: number) => `Hareketsizlik süresi: ${minutes} dakika`,
  idleHelp: "Bu süre boyunca işlem yapmazsanız oturumunuz kendiliğinden kapanır.",
  fieldDevice: "Bu cihaz saha tableti olarak işaretli.",
  notFieldDevice: "Bu cihaz saha tableti değil.",
} as const;

/** Saniyeyi dakikaya yuvarlar (en az 1). */
export function idleMinutes(seconds: number): number {
  return Math.max(1, Math.round(seconds / 60));
}
