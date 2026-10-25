// Personel ekranlarının metinleri (CLAUDE.md §6: arayüz Türkçe).
export const PERSONNEL_BASE = "/personel";

export const employeePath = (id: number) => `${PERSONNEL_BASE}/${id}`;

/** Personel sorgularının ortak anahtarı (kayıttan sonra hepsi yenilenir). */
export const PERSONNEL_KEY = ["personnel"] as const;

export const pe = {
  title: "Personel",
  intro:
    "Sahadaki ve ofisteki bütün çalışanların kartları; sistemi kullanmayanlar da burada. Kişisel veridir, yalnızca yönetim ve sistem yöneticisi görür.",
  search: "Ad, sicil no, birim ya da görev ara",
  department: "Birim",
  allDepartments: "Tüm birimler",
  status: "Durum",
  statusActive: "Çalışanlar",
  statusLeft: "Ayrılanlar",
  statusAll: "Tümü",
  newEmployee: "Yeni personel",
  empty: "Kayıt bulunamadı.",
  count: (n: number) => `${n} kişi`,

  employeeNo: "Sicil no",
  fullName: "Ad soyad",
  titleField: "Görev",
  phone: "Telefon",
  hireDate: "İşe giriş tarihi",
  terminationDate: "İşten çıkış tarihi",
  emergencyName: "Acil durumda aranacak kişi",
  emergencyPhone: "Acil durum telefonu",
  user: "Sistem kullanıcısı",
  noUser: "Sistemi kullanmıyor",
  userHelp:
    "Sisteme giriş hesabı olan çalışanın kartı kullanıcısına bağlanır. Hesap Sistem > Kullanıcılar'da açılır.",
  departmentHelp: "Seçin ya da yeni birim yazın",
  accountInactive: "hesap pasif",
  working: "Çalışıyor",
  left: "Ayrıldı",
  leftOn: (date: string) => `Ayrıldı · ${date}`,
  sectionWork: "Görev",
  sectionContact: "İletişim",

  back: "Personel listesi",
  edit: "Düzenle",
  terminate: "İşten ayrıldı",
  reinstate: "Yeniden işe başladı",
  terminateTitle: (name: string) => `${name} · işten ayrılış`,
  terminateIntro:
    "Kart silinmez: pasife alınır ve çıkış tarihi yazılır. Geçmiş kayıtlarda adı korunur.",
  note: "Not (isteğe bağlı)",
  accountStillActive: (username: string) =>
    `Bu kişinin sistem hesabı (${username}) hâlâ açık. Hesabı Sistem > Kullanıcılar'dan pasife alın.`,
  confirmReinstate: (name: string) =>
    `${name} yeniden çalışıyor olarak işaretlensin mi? Çıkış tarihi silinir; eski tarih geçmişte kalır.`,
  terminated: (name: string) => `${name} için işten ayrılış kaydedildi.`,
  reinstated: (name: string) => `${name} yeniden çalışıyor olarak işaretlendi.`,
  created: (name: string) => `${name} için personel kartı açıldı.`,
  saved: (name: string) => `${name} kaydedildi.`,

  formNewTitle: "Yeni personel kartı",
  formEditTitle: (name: string) => `${name} · kartı düzenle`,
  required: "Bu alan zorunlu.",
  cancel: "Vazgeç",
  save: "Kaydet",
  create: "Kartı aç",

  history: "Geçmiş",
  noHistory: "Geçmiş kaydı yok.",
  system: "Sistem",
  // Geçmişte alan adları Türkçe gösterilir.
  fields: {
    employee_no: "Sicil no",
    full_name: "Ad soyad",
    department: "Birim",
    title: "Görev",
    hire_date: "İşe giriş tarihi",
    termination_date: "İşten çıkış tarihi",
    phone: "Telefon",
    emergency_contact_name: "Acil durumda aranacak kişi",
    emergency_contact_phone: "Acil durum telefonu",
    user: "Sistem kullanıcısı",
    is_active: "Çalışıyor",
  } as Record<string, string>,
  yes: "Evet",
  no: "Hayır",
};
