// Sistem > Kullanıcılar > Yetkiler ekranının metinleri (plan §6.1). Modül, bölüm ve düzey adları
// katalogdan (`auth/access.gen.ts`), rol adları `tr.roles`'tan gelir.
import type { EndReason } from "../../../api/access";

export const ua = {
  back: "← Kullanıcılar",
  title: (name: string) => `${name} · Yetkiler`,
  tabAccess: "Yetkiler",
  tabHistory: "Geçmiş",
  notFound: "Kullanıcı bulunamadı.",
  inactive: "Pasif",
  superuser: "Süper kullanıcı",
  noOtp: "2FA yok",
  // Uyarılar
  inactiveWarning: "Kullanıcı pasif; giriş yapamaz.",
  noRoleWarning:
    "Rolü olmayan kişi görev almaz; yalnız temel yetkileri ve kişiye eklenenleri kullanır.",
  selfWarning: "Kendi sayfanızdasınız: yalnız rollerinizi değiştirebilirsiniz.",
  staleCatalog: "Uygulama güncel değil; sayfayı yenileyin.",
  changedWhileEditing:
    "Bu kişinin yetkileri siz düzenlerken değişti. Kaydetmeden önce sayfayı yenileyin.",
  discardAndReload: "Değişiklikleri at ve yenile",
  // Roller
  roles: "Roller",
  rolesHelp:
    "Rol değişikliği yetkilerle birlikte, aynı kayıtta ve gerekçeyle kaydedilir. Birden fazla rol seçilebilir.",
  ownAdminLocked: "Kendi sistem yöneticisi rolünüzü kaldıramazsınız.",
  adminWillEnd: (n: number) =>
    `Kaydedince kişiye özel ${n} ayarı biter; sistem yöneticisi her yetkiye sahiptir.`,
  kvkkWillEnd:
    "Yönetim rolü kaldırılınca personel, bordro, personel maliyeti, olaylar ve denetim günlüğü eklemeleri biter (KVKK).",
  adminText:
    "Sistem yöneticisi her ekranı görür ve her işlemi yapar; kişiye özel yetki uygulanmaz.",
  // Araç çubuğu
  search: "Bölüm ara",
  onlyPersonal: "Yalnız kişiye özel ayarlar",
  resetAll: "Tümünü rol varsayılanına döndür",
  cleanIneffective: "Etkisiz ayarları temizle",
  noMatch: "Aramaya uyan bölüm yok.",
  // Bölümler
  sensitiveTitle: "Hassas veriler",
  kvkkNote:
    "Personel, bordro, personel maliyeti, olaylar ve kazalar ile denetim günlüğü yetkileri yalnız yönetim rolündeki kullanıcılara verilebilir (KVKK).",
  modulesTitle: "Modül yetkileri",
  sectionColumn: "Bölüm",
  inMenu: "Menüde",
  notInMenu: "Menüde değil",
  overrideCount: (n: number) => `${n} kişiye özel`,
  moduleActions: (label: string) => `${label}: toplu işlemler`,
  columnToggle: (module: string, level: string) => `${module}: tümü ${level}`,
  resetModule: "Rol varsayılanına dön",
  viewOnly: "Yalnız görsün",
  removeAll: "Modüldeki bütün yetkileri kaldır",
  // Hücreler
  states: {
    role: "Rolden",
    granted: "Eklendi",
    revoked: "Kaldırıldı",
    none: "Verilmedi",
    locked: "Kilitli",
    absent: "Bu bölümde yok",
  },
  fromRole: (labels: string) => `${labels} rolünden`,
  everyoneSource: "Herkese açık",
  lockReasons: {
    everyone: "Herkese açık; kaldırılamaz",
    any_role: "Rolü olan herkese açık; kaldırılamaz",
    admin_only: "Yalnız sistem yöneticisi",
    kvkk: "Yalnız yönetim rolündekilere verilebilir (KVKK)",
  },
  ineffective: {
    redundant: "Etkisiz: rol zaten veriyor",
    redundantRevoke: "Etkisiz: rol zaten vermiyor",
    dropped_prereq: "Etkisiz: ön koşul eksik",
    dropped_view: "Görür kaldırıldığı için geçersiz",
    dropped_kvkk: "Yalnız yönetim rolünde geçerli",
  },
  unsaved: " (kaydedilmedi)",
  savedBy: (date: string, by: string, note: string) => `${date} · ${by} · ${note}`,
  // Açık kayıtlar
  openRecords: "Açık kayıtlar",
  openRecordsOpen: "Herkes okur",
  openRecordsClosed: "Bu kişi için kapalı",
  openReadNote: "Bu bölümün kayıtlarını giriş yapan herkes okuyabilir.",
  stillReads: (labels: string) => `Kayıtları şu bölümlerden okumaya devam eder: ${labels}.`,
  noLongerReads: "Bu modülün kayıtlarını artık okuyamaz.",
  affectedScreens: (text: string) => `Etkilenebilecek başka ekranlar: ${text}`,
  retiredTitle: "Kaldırılmış yetkiler",
  retiredHelp: "Katalogdan kaldırılmış bölümlerin ayarları; kaydedince biter.",
  // Kaydet çubuğu
  unsavedCount: (n: number) => `${n} değişiklik kaydedilmedi`,
  discard: "Vazgeç",
  saveEllipsis: "Kaydet…",
  // Özet penceresi
  summaryTitle: "Değişikliklerin özeti",
  summaryLoading: "Değişiklikler hesaplanıyor…",
  rolesChange: "Roller",
  granted: "Verilecek yetkiler",
  removed: "Kaldırılacak yetkiler",
  ended: "Biten kişiye özel ayarlar",
  menuAdded: "Menüye eklenecek modüller",
  menuRemoved: "Menüden kalkacak modüller",
  warnings: "Uyarılar",
  noEffect: "Kişinin geçerli yetkisi değişmiyor.",
  note: "Değişiklik notu",
  notePlaceholder: "Neden değiştiriyorsunuz? (ör. Ahmet izindeyken siparişleri onaylayacak)",
  noteRequired: "Değişikliğin gerekçesini yazın.",
  confirmSave: "Kaydet",
  reloadPage: "Sayfayı yenile",
  saved: (name: string) => `${name} kullanıcısının yetkileri kaydedildi.`,
  // Geçmiş
  historyEmpty: "Henüz kişiye özel yetki ya da rol değişikliği yok.",
  system: "Sistem",
  historyRoles: (before: string, after: string) => `Roller: ${before} → ${after}`,
  historyGranted: (text: string) => `Eklendi: ${text}`,
  historyRevoked: (text: string) => `Kaldırıldı: ${text}`,
  historyEnded: (reason: string, text: string) => `${reason}: ${text}`,
  noRoles: "Rolü yok",
  // Kaydedilmemiş değişiklikler
  leaveTitle: "Kaydedilmemiş değişiklikler",
  leaveText: "Yaptığınız değişiklikler kaydedilmedi. Sayfadan çıkılsın mı?",
  stay: "Sayfada kal",
  leave: "Değişiklikleri at ve çık",
} as const;

/** Bitiş nedenlerinin adları (Geçmiş ve özet; backend `EndReason` etiketleriyle aynı). */
export const END_REASONS: Readonly<Record<EndReason, string>> = {
  reset: "Rol varsayılanına döndü",
  ineffective: "Etkisiz olduğu için temizlendi",
  admin: "Sistem yöneticisi oldu",
  role_removed: "Gerekli rol kaldırıldı",
  replaced: "Değiştirildi",
  retired: "Yetki katalogdan kaldırıldı",
};

/** Kayıt türü → "… üzerinden görmeye devam eder" notundaki adı (her `READERS` anahtarı). */
export const RECORD_NOUNS: Readonly<Record<string, string>> = {
  "filling.fillingorder": "Dolum emirlerini",
  "filling.fillingrun": "Dolum partilerini",
  "filling.packagingspec": "Ambalaj reçetelerini",
  "hse.incident": "Olayları",
  "hse.safetydatasheet": "Güvenlik bilgi formlarını",
  "hse.wasterecord": "Atık kayıtlarını",
  "inventory.goodsreceipt": "Mal kabulleri",
  "inventory.lot": "Lotları",
  "inventory.stockadjustment": "Sayımları",
  "maintenance.maintenanceworkorder": "Bakım iş emirlerini",
  "production.productionbatch": "Şarjları",
  "production.productionorder": "Emirleri",
  "purchasing.purchaseorder": "Satın alma siparişlerini",
  "quality.sample": "Numuneleri",
  "returns.customerreturn": "İadeleri",
  "sales.salesorder": "Satış siparişlerini",
  "sales.shipment": "Sevkiyatları",
};
