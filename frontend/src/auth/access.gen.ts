// Bu dosya üretilir; elle değiştirmeyin.
// Kaynak: backend/apps/*/access.py (docs/plan/kisi-yetkileri.md §5.1).
// Yeniden üretmek için (depo kökünde):
//   docker compose exec -T backend python manage.py export_access --format=ts \
//     > frontend/src/auth/access.gen.ts

export const ACCESS_CATALOG_HASH = "951e0b0fc37ca9d926460386442633070a0ff33402a2b7ff9d718334510c3cbf";

export type AccessLevel = "read" | "view" | "change" | "approve";
export type ReadScope = "view" | "shared" | "any_role" | "open";
export type SectionKind = "section" | "action" | "sensitive" | "open_records";

export interface SectionMeta {
  key: string;
  module: string;
  label: string;
  kind: SectionKind;
  levels: readonly AccessLevel[];
  help: Readonly<Partial<Record<AccessLevel, string>>>;
  read: ReadScope;
  /** Düzey (ya da "*" her düzey) için gereken bölüm ve düzey. */
  requires: readonly { level: string; key: string; need: AccessLevel }[];
  restrictedToRole: string | null;
  adminOnly: readonly AccessLevel[];
  locked: readonly AccessLevel[];
}

export interface ModuleMeta {
  key: string;
  label: string;
  /** false: menüde kendi modülü yok, bölümleri menü açmaz. */
  menu: boolean;
  sections: readonly PermKey[];
}

export const LEVEL_LABELS: Readonly<Record<AccessLevel, string>> = {
  "read": "Kayıtları okur",
  "view": "Görür",
  "change": "Değiştirir",
  "approve": "Onaylar"
};

/** Paket sahipleri: "*" herkes, "+" rolü olan herkes ve 8 rol. */
export const HOLDER_LABELS: Readonly<Record<string, string>> = {
  "*": "Herkes",
  "+": "Rolü olan herkes",
  "yonetim": "Yönetim",
  "planlama": "Planlama",
  "depo": "Depo",
  "uretim": "Üretim",
  "laboratuvar": "Laboratuvar",
  "dolum": "Dolum",
  "sevkiyat": "Sevkiyat",
  "satin_alma": "Satın Alma"
};

export const PERM = {
  "SENSITIVE_PRICES": "sensitive.prices",
  "SENSITIVE_COSTS": "sensitive.costs",
  "MASTERDATA_CARDS": "masterdata.cards",
  "MASTERDATA_REFERENCE": "masterdata.reference",
  "MASTERDATA_COMPANY": "masterdata.company",
  "MASTERDATA_OPEN_RECORDS": "masterdata.open_records",
  "RECIPES_RECIPES": "recipes.recipes",
  "RECIPES_OPEN_RECORDS": "recipes.open_records",
  "INVENTORY_STOCK": "inventory.stock",
  "INVENTORY_LOTS": "inventory.lots",
  "INVENTORY_PALLETS": "inventory.pallets",
  "INVENTORY_RECEIPTS": "inventory.receipts",
  "INVENTORY_RECEIPT_PRICES": "inventory.receipt_prices",
  "INVENTORY_ADJUSTMENTS": "inventory.adjustments",
  "INVENTORY_LOT_BLOCK": "inventory.lot_block",
  "INVENTORY_MANUAL_RELEASE": "inventory.manual_release",
  "INVENTORY_OPEN_RECORDS": "inventory.open_records",
  "PRODUCTION_ORDERS": "production.orders",
  "PRODUCTION_PREP": "production.prep",
  "PRODUCTION_BATCHES": "production.batches",
  "PRODUCTION_OPEN_RECORDS": "production.open_records",
  "QUALITY_SAMPLES": "quality.samples",
  "QUALITY_CONDITIONAL": "quality.conditional",
  "QUALITY_SPECS": "quality.specs",
  "QUALITY_OPEN_RECORDS": "quality.open_records",
  "FILLING_ORDERS": "filling.orders",
  "FILLING_PREP": "filling.prep",
  "FILLING_RUNS": "filling.runs",
  "FILLING_SPECS": "filling.specs",
  "FILLING_REVERT": "filling.revert",
  "FILLING_OPEN_RECORDS": "filling.open_records",
  "SALES_ORDERS": "sales.orders",
  "SALES_SHIPMENTS": "sales.shipments",
  "SALES_PICKING": "sales.picking",
  "SALES_SHIPPED_LOTS": "sales.shipped_lots",
  "RETURNS_RETURNS": "returns.returns",
  "RETURNS_RECEIVING": "returns.receiving",
  "RETURNS_OPEN_RECORDS": "returns.open_records",
  "TRACEABILITY_TRACE": "traceability.trace",
  "PURCHASING_REQUESTS": "purchasing.requests",
  "PURCHASING_SUGGESTIONS": "purchasing.suggestions",
  "PURCHASING_ORDERS": "purchasing.orders",
  "PURCHASING_OVER_LIMIT": "purchasing.over_limit",
  "PURCHASING_DELIVERIES": "purchasing.deliveries",
  "PURCHASING_PERFORMANCE": "purchasing.performance",
  "PURCHASING_SETTINGS": "purchasing.settings",
  "COSTING_LOT_COSTS": "costing.lot_costs",
  "COSTING_RATES": "costing.rates",
  "COSTING_PERSONNEL_COST": "costing.personnel_cost",
  "MAINTENANCE_WORK_ORDERS": "maintenance.work_orders",
  "MAINTENANCE_ANY_UNIT": "maintenance.any_unit",
  "MAINTENANCE_PLANS": "maintenance.plans",
  "MAINTENANCE_BREAKDOWNS": "maintenance.breakdowns",
  "MAINTENANCE_DOWNTIMES": "maintenance.downtimes",
  "MAINTENANCE_CLEANINGS": "maintenance.cleanings",
  "MAINTENANCE_CALIBRATION": "maintenance.calibration",
  "MAINTENANCE_UNCLEANED": "maintenance.uncleaned",
  "MAINTENANCE_SETTINGS": "maintenance.settings",
  "HSE_INCIDENT_REPORT": "hse.incident_report",
  "HSE_INCIDENTS": "hse.incidents",
  "HSE_SDS": "hse.sds",
  "HSE_HAZARDS": "hse.hazards",
  "HSE_STORAGE": "hse.storage",
  "HSE_WASTE": "hse.waste",
  "HSE_SUMMARY": "hse.summary",
  "HSE_SETTINGS": "hse.settings",
  "PERSONNEL_CARDS": "personnel.cards",
  "PERSONNEL_ATTENDANCE": "personnel.attendance",
  "PERSONNEL_WAGES": "personnel.wages",
  "PERSONNEL_PAYROLL": "personnel.payroll",
  "PERSONNEL_SETTINGS": "personnel.settings",
  "REPORTING_MANAGEMENT": "reporting.management",
  "REPORTING_WAREHOUSE": "reporting.warehouse",
  "REPORTING_STOCK": "reporting.stock",
  "REPORTING_PRODUCTION": "reporting.production",
  "REPORTING_FILLING": "reporting.filling",
  "REPORTING_LAB": "reporting.lab",
  "REPORTING_SHIPPING": "reporting.shipping",
  "REPORTING_SHIPPING_REPORT": "reporting.shipping_report",
  "GOLIVE_READINESS": "golive.readiness",
  "GOLIVE_SETTINGS": "golive.settings",
  "GOLIVE_COMPARISONS": "golive.comparisons",
  "GOLIVE_PROBLEMS": "golive.problems",
  "WORKFLOW_ALL_TASKS": "workflow.all_tasks",
  "SYSTEM_AUDIT_LOG": "system.audit_log"
} as const;

export type PermKey = (typeof PERM)[keyof typeof PERM];

export const MODULES: readonly ModuleMeta[] = [
  {
    "key": "sensitive",
    "label": "Hassas veriler",
    "menu": false,
    "sections": [
      "sensitive.prices",
      "sensitive.costs"
    ]
  },
  {
    "key": "masterdata",
    "label": "Ana veriler",
    "menu": true,
    "sections": [
      "masterdata.cards",
      "masterdata.reference",
      "masterdata.company",
      "masterdata.open_records"
    ]
  },
  {
    "key": "recipes",
    "label": "Reçeteler",
    "menu": true,
    "sections": [
      "recipes.recipes",
      "recipes.open_records"
    ]
  },
  {
    "key": "inventory",
    "label": "Depo ve stok",
    "menu": true,
    "sections": [
      "inventory.stock",
      "inventory.lots",
      "inventory.pallets",
      "inventory.receipts",
      "inventory.receipt_prices",
      "inventory.adjustments",
      "inventory.lot_block",
      "inventory.manual_release",
      "inventory.open_records"
    ]
  },
  {
    "key": "production",
    "label": "Üretim",
    "menu": true,
    "sections": [
      "production.orders",
      "production.prep",
      "production.batches",
      "production.open_records"
    ]
  },
  {
    "key": "quality",
    "label": "Kalite kontrol",
    "menu": true,
    "sections": [
      "quality.samples",
      "quality.conditional",
      "quality.specs",
      "quality.open_records"
    ]
  },
  {
    "key": "filling",
    "label": "Dolum",
    "menu": true,
    "sections": [
      "filling.orders",
      "filling.prep",
      "filling.runs",
      "filling.specs",
      "filling.revert",
      "filling.open_records"
    ]
  },
  {
    "key": "sales",
    "label": "Sevkiyat",
    "menu": true,
    "sections": [
      "sales.orders",
      "sales.shipments",
      "sales.picking",
      "sales.shipped_lots"
    ]
  },
  {
    "key": "returns",
    "label": "İadeler",
    "menu": true,
    "sections": [
      "returns.returns",
      "returns.receiving",
      "returns.open_records"
    ]
  },
  {
    "key": "traceability",
    "label": "İzlenebilirlik",
    "menu": true,
    "sections": [
      "traceability.trace"
    ]
  },
  {
    "key": "purchasing",
    "label": "Satın alma",
    "menu": true,
    "sections": [
      "purchasing.requests",
      "purchasing.suggestions",
      "purchasing.orders",
      "purchasing.over_limit",
      "purchasing.deliveries",
      "purchasing.performance",
      "purchasing.settings"
    ]
  },
  {
    "key": "costing",
    "label": "Maliyet",
    "menu": true,
    "sections": [
      "costing.lot_costs",
      "costing.rates",
      "costing.personnel_cost"
    ]
  },
  {
    "key": "maintenance",
    "label": "Bakım",
    "menu": true,
    "sections": [
      "maintenance.work_orders",
      "maintenance.any_unit",
      "maintenance.plans",
      "maintenance.breakdowns",
      "maintenance.downtimes",
      "maintenance.cleanings",
      "maintenance.calibration",
      "maintenance.uncleaned",
      "maintenance.settings"
    ]
  },
  {
    "key": "hse",
    "label": "İSG ve çevre",
    "menu": true,
    "sections": [
      "hse.incident_report",
      "hse.incidents",
      "hse.sds",
      "hse.hazards",
      "hse.storage",
      "hse.waste",
      "hse.summary",
      "hse.settings"
    ]
  },
  {
    "key": "personnel",
    "label": "Personel",
    "menu": true,
    "sections": [
      "personnel.cards",
      "personnel.attendance",
      "personnel.wages",
      "personnel.payroll",
      "personnel.settings"
    ]
  },
  {
    "key": "reporting",
    "label": "Panolar ve raporlar",
    "menu": true,
    "sections": [
      "reporting.management",
      "reporting.warehouse",
      "reporting.stock",
      "reporting.production",
      "reporting.filling",
      "reporting.lab",
      "reporting.shipping",
      "reporting.shipping_report"
    ]
  },
  {
    "key": "golive",
    "label": "Canlıya geçiş",
    "menu": true,
    "sections": [
      "golive.readiness",
      "golive.settings",
      "golive.comparisons",
      "golive.problems"
    ]
  },
  {
    "key": "workflow",
    "label": "Görevler",
    "menu": false,
    "sections": [
      "workflow.all_tasks"
    ]
  },
  {
    "key": "system",
    "label": "Sistem",
    "menu": false,
    "sections": [
      "system.audit_log"
    ]
  }
];

export const SECTIONS: Readonly<Record<PermKey, SectionMeta>> = {
  "sensitive.prices": {
    "key": "sensitive.prices",
    "module": "sensitive",
    "label": "Fiyatları görür",
    "kind": "sensitive",
    "levels": [
      "view"
    ],
    "help": {
      "view": "Alış fiyatları: mal kabul fiyat ve masrafları, satın alma tutarları ve sipariş PDF'i. Satış fiyatları bu hakka bağlı değildir."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "sensitive.costs": {
    "key": "sensitive.costs",
    "module": "sensitive",
    "label": "Maliyetleri görür",
    "kind": "sensitive",
    "levels": [
      "view"
    ],
    "help": {
      "view": "Lot maliyeti, stok değeri ve raporların maliyet sütunları."
    },
    "read": "view",
    "requires": [
      {
        "level": "*",
        "key": "sensitive.prices",
        "need": "view"
      }
    ],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "masterdata.cards": {
    "key": "masterdata.cards",
    "module": "masterdata",
    "label": "Ana veri kartları",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Malzeme, tedarikçi, müşteri, depo, lokasyon, ekipman, kategori ve birim dönüşümü kartları.",
      "change": "Kart açar ve düzenler, Excel'den içe aktarır, GTIN önerisi alır, pasife alır."
    },
    "read": "shared",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "masterdata.reference": {
    "key": "masterdata.reference",
    "module": "masterdata",
    "label": "Birimler, yazıcılar ve etiket ayarları",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Birim, yazıcı ve etiket ayarı sekmeleri (salt okunur).",
      "change": "Birim, yazıcı ve etiket ayarlarını değiştirir (yalnız sistem yöneticisi)."
    },
    "read": "shared",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [
      "change"
    ],
    "locked": []
  },
  "masterdata.company": {
    "key": "masterdata.company",
    "module": "masterdata",
    "label": "Firma bilgileri",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Ticari unvan, adres, vergi ve sicil bilgileri.",
      "change": "Firma bilgilerini düzenler."
    },
    "read": "shared",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "masterdata.open_records": {
    "key": "masterdata.open_records",
    "module": "masterdata",
    "label": "Açık kayıtlar",
    "kind": "open_records",
    "levels": [
      "read"
    ],
    "help": {
      "read": "Bu modülün kayıtlarını giriş yapan herkes okuyabilir."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "recipes.recipes": {
    "key": "recipes.recipes",
    "module": "recipes",
    "label": "Reçeteler ve sürümler",
    "kind": "section",
    "levels": [
      "view",
      "change",
      "approve"
    ],
    "help": {
      "view": "Reçete kartı, sürümler, satırlar, adımlar ve ölçekleme.",
      "change": "Reçete ve sürüm taslağı açar ve düzenler, Excel'den taslak alır, pasife alır.",
      "approve": "Reçete sürümünü onaylar."
    },
    "read": "open",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "recipes.open_records": {
    "key": "recipes.open_records",
    "module": "recipes",
    "label": "Açık kayıtlar",
    "kind": "open_records",
    "levels": [
      "read"
    ],
    "help": {
      "read": "Bu modülün kayıtlarını giriş yapan herkes okuyabilir."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "inventory.stock": {
    "key": "inventory.stock",
    "module": "inventory",
    "label": "Stok sorgu, hareketler ve transfer",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Stok ve hareket listeleri.",
      "change": "Transfer, ters kayıt ve açılış stoku içe aktarma."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": [
      "view"
    ]
  },
  "inventory.lots": {
    "key": "inventory.lots",
    "module": "inventory",
    "label": "Lotlar",
    "kind": "section",
    "levels": [
      "view"
    ],
    "help": {
      "view": "Lot sayfası, soy ağacı, lot etiketi ve analiz sertifikası PDF'i."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": [
      "view"
    ]
  },
  "inventory.pallets": {
    "key": "inventory.pallets",
    "module": "inventory",
    "label": "Palet etiketleri (SSCC)",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Palet listesi.",
      "change": "Palet oluşturur."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": [
      "view"
    ]
  },
  "inventory.receipts": {
    "key": "inventory.receipts",
    "module": "inventory",
    "label": "Mal kabul",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Mal kabul belgeleri (fiyatsız).",
      "change": "Hazırlar, taslağı düzenler, kaydeder ve stoka alır, taslağı iptal eder."
    },
    "read": "open",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "inventory.receipt_prices": {
    "key": "inventory.receipt_prices",
    "module": "inventory",
    "label": "Mal kabul fiyat ve masrafları",
    "kind": "action",
    "levels": [
      "change"
    ],
    "help": {
      "change": "Birim fiyat, para birimi, kur ve ek masraf girer ve düzeltir."
    },
    "read": "view",
    "requires": [
      {
        "level": "change",
        "key": "inventory.receipts",
        "need": "view"
      },
      {
        "level": "change",
        "key": "sensitive.prices",
        "need": "view"
      }
    ],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "inventory.adjustments": {
    "key": "inventory.adjustments",
    "module": "inventory",
    "label": "Sayım düzeltme",
    "kind": "section",
    "levels": [
      "view",
      "change",
      "approve"
    ],
    "help": {
      "view": "Sayım düzeltme belgeleri.",
      "change": "Hazırlar, taslağı düzenler, taslağı iptal eder.",
      "approve": "Kaydeder ve stoka alır (D-3)."
    },
    "read": "open",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "inventory.lot_block": {
    "key": "inventory.lot_block",
    "module": "inventory",
    "label": "Lot bloke etme",
    "kind": "action",
    "levels": [
      "approve"
    ],
    "help": {
      "approve": "Lotu gerekçeyle bloke eder."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "inventory.manual_release": {
    "key": "inventory.manual_release",
    "module": "inventory",
    "label": "Elle serbest bırakma (D-5)",
    "kind": "action",
    "levels": [
      "approve"
    ],
    "help": {
      "approve": "Lotu kalite kararı olmadan serbest bırakır (yalnız sistem yöneticisi)."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [
      "approve"
    ],
    "locked": []
  },
  "inventory.open_records": {
    "key": "inventory.open_records",
    "module": "inventory",
    "label": "Açık kayıtlar",
    "kind": "open_records",
    "levels": [
      "read"
    ],
    "help": {
      "read": "Bu modülün kayıtlarını giriş yapan herkes okuyabilir."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "production.orders": {
    "key": "production.orders",
    "module": "production",
    "label": "Üretim emirleri",
    "kind": "section",
    "levels": [
      "view",
      "change",
      "approve"
    ],
    "help": {
      "view": "Emir listesi ve sayfası.",
      "change": "Emir açar, taslağı düzenler, taslağı iptal eder, yeniden işleme emri açar, emri elle tamamlar.",
      "approve": "Emri onaylar, onaylı emri iptal eder."
    },
    "read": "open",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "production.prep": {
    "key": "production.prep",
    "module": "production",
    "label": "Malzeme hazırlama",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Hazırlama sekmesi.",
      "change": "Hazırlığı başlatır, malzeme okutur, hazır bildirir."
    },
    "read": "open",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "production.batches": {
    "key": "production.batches",
    "module": "production",
    "label": "Şarj ve tartım",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Şarjlar ve tartımlar.",
      "change": "Şarj başlatır, tartar, bitirir; tartım yapılmamış şarjı iptal eder."
    },
    "read": "open",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "production.open_records": {
    "key": "production.open_records",
    "module": "production",
    "label": "Açık kayıtlar",
    "kind": "open_records",
    "levels": [
      "read"
    ],
    "help": {
      "read": "Bu modülün kayıtlarını giriş yapan herkes okuyabilir."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "quality.samples": {
    "key": "quality.samples",
    "module": "quality",
    "label": "Numuneler ve kalite kararı",
    "kind": "section",
    "levels": [
      "view",
      "change",
      "approve"
    ],
    "help": {
      "view": "Numuneler, sonuçlar ve kararlar.",
      "change": "Numune açar, numune alma bilgilerini düzenler, spesifikasyon atar, sonuç girer ve düzeltir, numuneyi iptal eder (Numune kuyruğu sekmesi).",
      "approve": "Karar verir: serbest bırakır, reddeder, yeniden işletir, şartlı kabul önerir."
    },
    "read": "open",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "quality.conditional": {
    "key": "quality.conditional",
    "module": "quality",
    "label": "Şartlı kabul onayı",
    "kind": "section",
    "levels": [
      "view",
      "approve"
    ],
    "help": {
      "view": "Onay bekleyen şartlı kabuller.",
      "approve": "Önerilen şartlı kabulü onaylar ya da reddeder; öneren kişi onaylayamaz."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "quality.specs": {
    "key": "quality.specs",
    "module": "quality",
    "label": "Spesifikasyonlar ve test tanımları",
    "kind": "section",
    "levels": [
      "view",
      "change",
      "approve"
    ],
    "help": {
      "view": "Spesifikasyon sürümleri ve test tanımları.",
      "change": "Spesifikasyon ve test tanımı açar ve düzenler.",
      "approve": "Spesifikasyon sürümünü onaylar."
    },
    "read": "open",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "quality.open_records": {
    "key": "quality.open_records",
    "module": "quality",
    "label": "Açık kayıtlar",
    "kind": "open_records",
    "levels": [
      "read"
    ],
    "help": {
      "read": "Bu modülün kayıtlarını giriş yapan herkes okuyabilir."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "filling.orders": {
    "key": "filling.orders",
    "module": "filling",
    "label": "Dolum emirleri",
    "kind": "section",
    "levels": [
      "view",
      "change",
      "approve"
    ],
    "help": {
      "view": "Dolum emirleri.",
      "change": "Emir açar, taslağı düzenler, taslağı iptal eder.",
      "approve": "Emri onaylar, onaylı emri iptal eder."
    },
    "read": "open",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "filling.prep": {
    "key": "filling.prep",
    "module": "filling",
    "label": "Ambalaj hazırlama",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Hazırlama sekmesi.",
      "change": "Hazırlığı başlatır, ambalaj okutur, hazır bildirir."
    },
    "read": "open",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "filling.runs": {
    "key": "filling.runs",
    "module": "filling",
    "label": "Dolum hattı",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Dolum partileri ve tüketim raporları.",
      "change": "Parti başlatır, bulk tüketimini ve ambalaj okutmayı kaydeder, fire girer, partiyi bitirir, kaydı olmayan partiyi iptal eder, dolumu bitirir."
    },
    "read": "open",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "filling.specs": {
    "key": "filling.specs",
    "module": "filling",
    "label": "Ambalaj reçeteleri",
    "kind": "section",
    "levels": [
      "view",
      "change",
      "approve"
    ],
    "help": {
      "view": "Ambalaj reçetesi sürümleri ve satırları.",
      "change": "Ambalaj reçetesi açar ve düzenler.",
      "approve": "Ambalaj reçetesi sürümünü onaylar."
    },
    "read": "open",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "filling.revert": {
    "key": "filling.revert",
    "module": "filling",
    "label": "Dolum emrini geri alma",
    "kind": "action",
    "levels": [
      "change"
    ],
    "help": {
      "change": "Fiilen yapılmamış dolumu geri alır: emrin stok hareketleri ters kayıtla geri alınır, partiler ve açık numuneler iptal edilir, emir iptal olur."
    },
    "read": "view",
    "requires": [
      {
        "level": "change",
        "key": "filling.orders",
        "need": "view"
      }
    ],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "filling.open_records": {
    "key": "filling.open_records",
    "module": "filling",
    "label": "Açık kayıtlar",
    "kind": "open_records",
    "levels": [
      "read"
    ],
    "help": {
      "read": "Bu modülün kayıtlarını giriş yapan herkes okuyabilir."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "sales.orders": {
    "key": "sales.orders",
    "module": "sales",
    "label": "Satış siparişleri",
    "kind": "section",
    "levels": [
      "view",
      "change",
      "approve"
    ],
    "help": {
      "view": "Siparişler ve fiyatları, Müşteriler sekmesi ve müşteri kartı.",
      "change": "Taslak açar, rezervasyon yapar, siparişi kapatır, taslağı iptal eder.",
      "approve": "Siparişi onaylar ve rezerve eder, onaylı siparişi iptal eder."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "sales.shipments": {
    "key": "sales.shipments",
    "module": "sales",
    "label": "Sevkiyatlar ve irsaliye",
    "kind": "section",
    "levels": [
      "view",
      "change",
      "approve"
    ],
    "help": {
      "view": "Sevkiyatlar ve irsaliye PDF'i.",
      "change": "Sevkiyat planlar, araç ve şoför bilgisini girer, sevk öncesi iptal eder.",
      "approve": "Sevki onaylar."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "sales.picking": {
    "key": "sales.picking",
    "module": "sales",
    "label": "Toplama ve yükleme",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Toplama sekmesi.",
      "change": "Lot okutur, okutmayı geri alır, yüklemeyi tamamlar."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "sales.shipped_lots": {
    "key": "sales.shipped_lots",
    "module": "sales",
    "label": "Müşteriye sevk edilen lotlar",
    "kind": "section",
    "levels": [
      "view"
    ],
    "help": {
      "view": "Müşteri kartındaki sevk edilen lotlar paneli."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "returns.returns": {
    "key": "returns.returns",
    "module": "returns",
    "label": "İade kayıtları",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "İade listesi ve sayfası.",
      "change": "İade açar, taslağı düzenler, taslağı iptal eder."
    },
    "read": "open",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "returns.receiving": {
    "key": "returns.receiving",
    "module": "returns",
    "label": "İade teslim alma ve imha",
    "kind": "action",
    "levels": [
      "change"
    ],
    "help": {
      "change": "İadeyi teslim alır, imha eder."
    },
    "read": "view",
    "requires": [
      {
        "level": "change",
        "key": "returns.returns",
        "need": "view"
      }
    ],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "returns.open_records": {
    "key": "returns.open_records",
    "module": "returns",
    "label": "Açık kayıtlar",
    "kind": "open_records",
    "levels": [
      "read"
    ],
    "help": {
      "read": "Bu modülün kayıtlarını giriş yapan herkes okuyabilir."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "traceability.trace": {
    "key": "traceability.trace",
    "module": "traceability",
    "label": "Geri ve ileri izleme, geri çağırma",
    "kind": "section",
    "levels": [
      "view"
    ],
    "help": {
      "view": "Geri ve ileri izleme ile geri çağırma raporları, Excel ve PDF."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "purchasing.requests": {
    "key": "purchasing.requests",
    "module": "purchasing",
    "label": "Satın alma talepleri",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Talepler sekmesi.",
      "change": "Talep açar; kişi kendi talebini düzenler ve iptal eder."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "purchasing.suggestions": {
    "key": "purchasing.suggestions",
    "module": "purchasing",
    "label": "Talep önerileri",
    "kind": "section",
    "levels": [
      "view"
    ],
    "help": {
      "view": "Öneriler sekmesi."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "purchasing.orders": {
    "key": "purchasing.orders",
    "module": "purchasing",
    "label": "Satın alma siparişleri",
    "kind": "section",
    "levels": [
      "view",
      "change",
      "approve"
    ],
    "help": {
      "view": "Siparişler (fiyatlar yalnız Fiyatları görür ile).",
      "change": "Sipariş yazar, yönetim onayına ve tedarikçiye gönderir, kalanı kapatır, taslağı ya da onay bekleyeni iptal eder, başkasının talebini düzenler ve iptal eder.",
      "approve": "D-13 limiti içinde onaylar, onaylı siparişi iptal eder."
    },
    "read": "view",
    "requires": [
      {
        "level": "change",
        "key": "sensitive.prices",
        "need": "view"
      },
      {
        "level": "approve",
        "key": "sensitive.prices",
        "need": "view"
      }
    ],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "purchasing.over_limit": {
    "key": "purchasing.over_limit",
    "module": "purchasing",
    "label": "Limit üstü sipariş onayı",
    "kind": "action",
    "levels": [
      "approve"
    ],
    "help": {
      "approve": "Limit üstü ya da limit girilmemişken onaylar; taslağa geri gönderir."
    },
    "read": "view",
    "requires": [
      {
        "level": "approve",
        "key": "purchasing.orders",
        "need": "view"
      },
      {
        "level": "approve",
        "key": "sensitive.prices",
        "need": "view"
      }
    ],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "purchasing.deliveries": {
    "key": "purchasing.deliveries",
    "module": "purchasing",
    "label": "Beklenen teslimatlar ve siparişten mal kabul",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Açık sipariş satırları (fiyatsız) ve mal kabullerin sipariş bağlantıları.",
      "change": "Siparişten mal kabul taslağı açar."
    },
    "read": "view",
    "requires": [
      {
        "level": "change",
        "key": "purchasing.orders",
        "need": "view"
      }
    ],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "purchasing.performance": {
    "key": "purchasing.performance",
    "module": "purchasing",
    "label": "Tedarikçi performansı",
    "kind": "section",
    "levels": [
      "view"
    ],
    "help": {
      "view": "Tedarikçi performans raporu."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "purchasing.settings": {
    "key": "purchasing.settings",
    "module": "purchasing",
    "label": "Satın alma ayarları",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Onay limiti ve fazla teslim toleransı.",
      "change": "Onay limitini ve fazla teslim toleransını değiştirir."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "costing.lot_costs": {
    "key": "costing.lot_costs",
    "module": "costing",
    "label": "Lot maliyetleri ve maliyet raporları",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Lot maliyeti ve maliyet raporları.",
      "change": "Maliyeti hesaplar."
    },
    "read": "view",
    "requires": [
      {
        "level": "*",
        "key": "sensitive.costs",
        "need": "view"
      }
    ],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "costing.rates": {
    "key": "costing.rates",
    "module": "costing",
    "label": "Gider oranları ve standart maliyetler",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Gider oranları ve standart maliyetler.",
      "change": "Oran ekler ve düzeltir; standart maliyet ekler, düzeltir, pasife alır."
    },
    "read": "view",
    "requires": [
      {
        "level": "*",
        "key": "sensitive.costs",
        "need": "view"
      }
    ],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "costing.personnel_cost": {
    "key": "costing.personnel_cost",
    "module": "costing",
    "label": "Personel maliyeti",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Personel maliyeti sekmesi ve Excel'i (açılışı bordro erişim günlüğüne yazılır).",
      "change": "Birimlerin maliyet aşamasını değiştirir; onaylı aydan işçilik oranı ekler (Gider oranları: Değiştirir de ister)."
    },
    "read": "view",
    "requires": [
      {
        "level": "*",
        "key": "sensitive.costs",
        "need": "view"
      },
      {
        "level": "*",
        "key": "personnel.wages",
        "need": "view"
      },
      {
        "level": "*",
        "key": "personnel.payroll",
        "need": "view"
      }
    ],
    "restrictedToRole": "yonetim",
    "adminOnly": [],
    "locked": []
  },
  "maintenance.work_orders": {
    "key": "maintenance.work_orders",
    "module": "maintenance",
    "label": "Bakım iş emirleri",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Bakım iş emirleri.",
      "change": "Kişinin kendi biriminin (sorumlu rol) iş emirlerinde işe başlar, parça ekler, tamamlar, iptal eder."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "maintenance.any_unit": {
    "key": "maintenance.any_unit",
    "module": "maintenance",
    "label": "Tüm birimlerin iş emirlerini yürütme",
    "kind": "action",
    "levels": [
      "change"
    ],
    "help": {
      "change": "Sorumlu birim kuralının istisnası: her birimin iş emrini yürütür."
    },
    "read": "view",
    "requires": [
      {
        "level": "change",
        "key": "maintenance.work_orders",
        "need": "change"
      }
    ],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "maintenance.plans": {
    "key": "maintenance.plans",
    "module": "maintenance",
    "label": "Bakım planları ve iş emri açma",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Bakım planları.",
      "change": "Plan açar ve düzenler, elle iş emri açar."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "maintenance.breakdowns": {
    "key": "maintenance.breakdowns",
    "module": "maintenance",
    "label": "Arıza bildirimi",
    "kind": "action",
    "levels": [
      "change"
    ],
    "help": {
      "change": "Arıza bildirir."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": [
      "change"
    ]
  },
  "maintenance.downtimes": {
    "key": "maintenance.downtimes",
    "module": "maintenance",
    "label": "Duruşlar",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Duruş kayıtları.",
      "change": "Duruş başlatır ve bitirir."
    },
    "read": "any_role",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "maintenance.cleanings": {
    "key": "maintenance.cleanings",
    "module": "maintenance",
    "label": "Tank temizliği",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Tank temizliği kayıtları.",
      "change": "Temizlik kaydeder; tamamlanmış temizlik iş emri açar."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "maintenance.calibration": {
    "key": "maintenance.calibration",
    "module": "maintenance",
    "label": "Kalibrasyon",
    "kind": "section",
    "levels": [
      "view"
    ],
    "help": {
      "view": "Terazi kalibrasyon durumu."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "maintenance.uncleaned": {
    "key": "maintenance.uncleaned",
    "module": "maintenance",
    "label": "Temizliksiz geçişler (D-14)",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Temizliksiz geçiş kayıtları.",
      "change": "Temizliksiz geçişe izin verir."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "maintenance.settings": {
    "key": "maintenance.settings",
    "module": "maintenance",
    "label": "Bakım ayarları",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Kalibrasyon uyarı süresi ve iş emri açma süresi.",
      "change": "Bakım ayarlarını değiştirir."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "hse.incident_report": {
    "key": "hse.incident_report",
    "module": "hse",
    "label": "Olay bildirimi",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Kişinin kendi bildirdiği olaylar.",
      "change": "Olay bildirir; kendi olayına yorum ve fotoğraf ekler."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": [
      "view",
      "change"
    ]
  },
  "hse.incidents": {
    "key": "hse.incidents",
    "module": "hse",
    "label": "Olaylar ve kazalar",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Bütün olaylar (yaralanan kişi ve yaralanma bilgisi).",
      "change": "Olayı inceler, kapatır, iptal eder."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": "yonetim",
    "adminOnly": [],
    "locked": []
  },
  "hse.sds": {
    "key": "hse.sds",
    "module": "hse",
    "label": "GBF arşivi",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "GBF'ler, eksik ve süresi geçmiş GBF raporu.",
      "change": "Yeni GBF ekler, PDF yükler."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "hse.hazards": {
    "key": "hse.hazards",
    "module": "hse",
    "label": "Tehlike bilgileri ve H/P ifadeleri",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Malzemenin tehlike bilgisi ve H/P ifadeleri.",
      "change": "Tehlike bilgisini ve H/P ifadelerini düzenler."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": [
      "view"
    ]
  },
  "hse.storage": {
    "key": "hse.storage",
    "module": "hse",
    "label": "Depolama limitleri",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Tehlikeli madde depolama limitleri.",
      "change": "Limitleri düzenler."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "hse.waste": {
    "key": "hse.waste",
    "module": "hse",
    "label": "Atık",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Atık kayıtları.",
      "change": "Atık kaydı açar ve düzenler."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "hse.summary": {
    "key": "hse.summary",
    "module": "hse",
    "label": "İSG özeti",
    "kind": "section",
    "levels": [
      "view"
    ],
    "help": {
      "view": "Sayılar (isim yok)."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "hse.settings": {
    "key": "hse.settings",
    "module": "hse",
    "label": "İSG ayarları",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "GBF en çok yaşı.",
      "change": "İSG ayarlarını değiştirir."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "personnel.cards": {
    "key": "personnel.cards",
    "module": "personnel",
    "label": "Personel kartları ve özlük belgeleri",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Personel kartları, özlük bilgileri ve belgeleri.",
      "change": "Kart açar ve düzenler, belge ekler."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": "yonetim",
    "adminOnly": [],
    "locked": []
  },
  "personnel.attendance": {
    "key": "personnel.attendance",
    "module": "personnel",
    "label": "Puantaj ve tatil takvimi",
    "kind": "section",
    "levels": [
      "view",
      "change",
      "approve"
    ],
    "help": {
      "view": "Puantaj ve tatil takvimi.",
      "change": "Gün ve aralık girişi, tatiller.",
      "approve": "Ayı onaylar ve yeniden açar."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": "yonetim",
    "adminOnly": [],
    "locked": []
  },
  "personnel.wages": {
    "key": "personnel.wages",
    "module": "personnel",
    "label": "Ücretler",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Ücret geçmişi.",
      "change": "Ücret girer ve düzeltir."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": "yonetim",
    "adminOnly": [],
    "locked": []
  },
  "personnel.payroll": {
    "key": "personnel.payroll",
    "module": "personnel",
    "label": "Bordro",
    "kind": "section",
    "levels": [
      "view",
      "change",
      "approve"
    ],
    "help": {
      "view": "Ön bordro, pusulalar, PDF ve Excel.",
      "change": "Kalemler, devirler, dış bordro tutarları; yeniden açılan ayda karta geçirme.",
      "approve": "Onaylar, yeniden açar, onaylı bordronun ödeme tarihini düzeltir."
    },
    "read": "view",
    "requires": [
      {
        "level": "*",
        "key": "personnel.wages",
        "need": "view"
      }
    ],
    "restrictedToRole": "yonetim",
    "adminOnly": [],
    "locked": []
  },
  "personnel.settings": {
    "key": "personnel.settings",
    "module": "personnel",
    "label": "Personel ayarları",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Bordro parametreleri (asgari ücret, SGK oranları, vergi dilimleri) ve hafta tatili günleri.",
      "change": "Bordro parametrelerini ve hafta tatili günlerini değiştirir."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": "yonetim",
    "adminOnly": [],
    "locked": []
  },
  "reporting.management": {
    "key": "reporting.management",
    "module": "reporting",
    "label": "Yönetim panosu ve görev süreleri raporu",
    "kind": "section",
    "levels": [
      "view"
    ],
    "help": {
      "view": "Yönetim panosu ve görev süreleri raporu."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "reporting.warehouse": {
    "key": "reporting.warehouse",
    "module": "reporting",
    "label": "Depo panosu",
    "kind": "section",
    "levels": [
      "view"
    ],
    "help": {
      "view": "Depo panosu."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "reporting.stock": {
    "key": "reporting.stock",
    "module": "reporting",
    "label": "Stok raporları",
    "kind": "section",
    "levels": [
      "view"
    ],
    "help": {
      "view": "Stok durumu ve stok hareketleri raporları."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "reporting.production": {
    "key": "reporting.production",
    "module": "reporting",
    "label": "Üretim panosu ve üretim raporu",
    "kind": "section",
    "levels": [
      "view"
    ],
    "help": {
      "view": "Üretim panosu ve üretim raporu."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "reporting.filling": {
    "key": "reporting.filling",
    "module": "reporting",
    "label": "Dolum raporu",
    "kind": "section",
    "levels": [
      "view"
    ],
    "help": {
      "view": "Dolum raporu."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "reporting.lab": {
    "key": "reporting.lab",
    "module": "reporting",
    "label": "Laboratuvar panosu ve kalite raporu",
    "kind": "section",
    "levels": [
      "view"
    ],
    "help": {
      "view": "Laboratuvar panosu ve kalite raporu."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "reporting.shipping": {
    "key": "reporting.shipping",
    "module": "reporting",
    "label": "Sevkiyat panosu",
    "kind": "section",
    "levels": [
      "view"
    ],
    "help": {
      "view": "Sevkiyat panosu."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "reporting.shipping_report": {
    "key": "reporting.shipping_report",
    "module": "reporting",
    "label": "Sevkiyat raporu",
    "kind": "section",
    "levels": [
      "view"
    ],
    "help": {
      "view": "Sevkiyat raporu."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "golive.readiness": {
    "key": "golive.readiness",
    "module": "golive",
    "label": "Hazırlık listesi",
    "kind": "section",
    "levels": [
      "view"
    ],
    "help": {
      "view": "Canlıya geçiş hazırlık kontrol listesi."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "golive.settings": {
    "key": "golive.settings",
    "module": "golive",
    "label": "Canlıya geçiş ayarları",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Canlı başlangıç tarihi.",
      "change": "Tarihi kaydeder ya da kaldırır (o günden açılış stoku yüklenemez)."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "golive.comparisons": {
    "key": "golive.comparisons",
    "module": "golive",
    "label": "Stok karşılaştırma",
    "kind": "section",
    "levels": [
      "view",
      "change"
    ],
    "help": {
      "view": "Stok karşılaştırmaları.",
      "change": "Yeni karşılaştırma yükler (Excel)."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "golive.problems": {
    "key": "golive.problems",
    "module": "golive",
    "label": "Sorun bildirimleri listesi",
    "kind": "section",
    "levels": [
      "view"
    ],
    "help": {
      "view": "Bütün sorun bildirimleri (yalnız sistem yöneticisi)."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [
      "view"
    ],
    "locked": []
  },
  "workflow.all_tasks": {
    "key": "workflow.all_tasks",
    "module": "workflow",
    "label": "Tüm birimlerin görevleri",
    "kind": "section",
    "levels": [
      "view"
    ],
    "help": {
      "view": "Başka rollerin görevlerini de görür."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": null,
    "adminOnly": [],
    "locked": []
  },
  "system.audit_log": {
    "key": "system.audit_log",
    "module": "system",
    "label": "Denetim günlüğü",
    "kind": "section",
    "levels": [
      "view"
    ],
    "help": {
      "view": "Bütün kayıtların değişiklik geçmişi (API)."
    },
    "read": "view",
    "requires": [],
    "restrictedToRole": "yonetim",
    "adminOnly": [],
    "locked": []
  }
};

/** Paket sahibi → bölüm → "vca" harfleri (rol varsayılanları). */
export const PACKAGES: Readonly<Record<string, Readonly<Record<string, string>>>> = {
  "*": {
    "filling.open_records": "r",
    "inventory.lots": "v",
    "inventory.open_records": "r",
    "inventory.pallets": "v",
    "inventory.stock": "v",
    "masterdata.open_records": "r",
    "production.open_records": "r",
    "quality.open_records": "r",
    "recipes.open_records": "r",
    "returns.open_records": "r"
  },
  "+": {
    "hse.hazards": "v",
    "hse.incident_report": "vc",
    "maintenance.breakdowns": "c"
  },
  "yonetim": {
    "costing.lot_costs": "vc",
    "costing.personnel_cost": "vc",
    "costing.rates": "vc",
    "filling.orders": "v",
    "filling.revert": "c",
    "filling.runs": "v",
    "filling.specs": "v",
    "golive.comparisons": "vc",
    "golive.readiness": "v",
    "golive.settings": "vc",
    "hse.hazards": "c",
    "hse.incidents": "vc",
    "hse.sds": "vc",
    "hse.settings": "vc",
    "hse.storage": "vc",
    "hse.summary": "v",
    "hse.waste": "vc",
    "inventory.adjustments": "v",
    "inventory.receipt_prices": "c",
    "inventory.receipts": "v",
    "maintenance.any_unit": "c",
    "maintenance.calibration": "v",
    "maintenance.cleanings": "vc",
    "maintenance.downtimes": "vc",
    "maintenance.plans": "vc",
    "maintenance.settings": "vc",
    "maintenance.uncleaned": "v",
    "maintenance.work_orders": "vc",
    "masterdata.cards": "v",
    "masterdata.company": "vc",
    "masterdata.reference": "v",
    "personnel.attendance": "vca",
    "personnel.cards": "vc",
    "personnel.payroll": "vca",
    "personnel.settings": "vc",
    "personnel.wages": "vc",
    "production.batches": "v",
    "production.orders": "v",
    "purchasing.deliveries": "vc",
    "purchasing.orders": "vca",
    "purchasing.over_limit": "a",
    "purchasing.performance": "v",
    "purchasing.requests": "vc",
    "purchasing.settings": "vc",
    "purchasing.suggestions": "v",
    "quality.conditional": "va",
    "quality.samples": "v",
    "quality.specs": "v",
    "reporting.filling": "v",
    "reporting.lab": "v",
    "reporting.management": "v",
    "reporting.production": "v",
    "reporting.shipping": "v",
    "reporting.shipping_report": "v",
    "reporting.stock": "v",
    "reporting.warehouse": "v",
    "returns.returns": "v",
    "sales.orders": "vca",
    "sales.shipments": "v",
    "sales.shipped_lots": "v",
    "sensitive.costs": "v",
    "sensitive.prices": "v",
    "system.audit_log": "v",
    "traceability.trace": "v",
    "workflow.all_tasks": "v"
  },
  "planlama": {
    "filling.orders": "vca",
    "filling.runs": "v",
    "filling.specs": "vca",
    "golive.comparisons": "v",
    "golive.readiness": "v",
    "golive.settings": "v",
    "inventory.receipts": "v",
    "maintenance.calibration": "v",
    "maintenance.cleanings": "v",
    "maintenance.downtimes": "vc",
    "maintenance.plans": "v",
    "maintenance.uncleaned": "v",
    "maintenance.work_orders": "vc",
    "masterdata.cards": "vc",
    "masterdata.company": "v",
    "masterdata.reference": "v",
    "production.batches": "v",
    "production.orders": "vca",
    "purchasing.requests": "vc",
    "purchasing.suggestions": "v",
    "recipes.recipes": "vca",
    "reporting.filling": "v",
    "reporting.lab": "v",
    "reporting.management": "v",
    "reporting.production": "v",
    "reporting.shipping": "v",
    "reporting.shipping_report": "v",
    "reporting.stock": "v",
    "reporting.warehouse": "v",
    "sales.orders": "v",
    "sales.shipments": "v"
  },
  "depo": {
    "filling.orders": "v",
    "filling.prep": "vc",
    "filling.runs": "v",
    "filling.specs": "v",
    "golive.comparisons": "vc",
    "golive.readiness": "v",
    "golive.settings": "v",
    "hse.sds": "v",
    "hse.storage": "v",
    "inventory.adjustments": "vca",
    "inventory.pallets": "c",
    "inventory.receipts": "vc",
    "inventory.stock": "c",
    "production.batches": "v",
    "production.orders": "v",
    "production.prep": "vc",
    "purchasing.deliveries": "vc",
    "purchasing.orders": "v",
    "purchasing.requests": "vc",
    "reporting.shipping": "v",
    "reporting.stock": "v",
    "reporting.warehouse": "v",
    "returns.receiving": "c",
    "returns.returns": "v",
    "sales.orders": "v",
    "sales.picking": "vc",
    "sales.shipments": "v"
  },
  "uretim": {
    "inventory.pallets": "c",
    "maintenance.calibration": "v",
    "maintenance.cleanings": "vc",
    "maintenance.downtimes": "vc",
    "maintenance.plans": "vc",
    "maintenance.uncleaned": "v",
    "maintenance.work_orders": "vc",
    "production.batches": "vc",
    "production.orders": "v",
    "purchasing.requests": "vc",
    "reporting.production": "v"
  },
  "laboratuvar": {
    "hse.hazards": "c",
    "hse.sds": "v",
    "inventory.lot_block": "a",
    "inventory.receipts": "v",
    "maintenance.calibration": "v",
    "maintenance.cleanings": "v",
    "maintenance.downtimes": "vc",
    "maintenance.plans": "vc",
    "maintenance.uncleaned": "vc",
    "maintenance.work_orders": "vc",
    "quality.samples": "vca",
    "quality.specs": "vca",
    "recipes.recipes": "vca",
    "reporting.lab": "v",
    "returns.returns": "v",
    "traceability.trace": "v"
  },
  "dolum": {
    "filling.orders": "v",
    "filling.runs": "vc",
    "filling.specs": "v",
    "inventory.pallets": "c",
    "maintenance.calibration": "v",
    "maintenance.cleanings": "v",
    "maintenance.downtimes": "vc",
    "maintenance.plans": "vc",
    "maintenance.uncleaned": "v",
    "maintenance.work_orders": "vc",
    "reporting.filling": "v"
  },
  "sevkiyat": {
    "inventory.pallets": "c",
    "reporting.shipping": "v",
    "reporting.shipping_report": "v",
    "returns.receiving": "c",
    "returns.returns": "vc",
    "sales.orders": "vca",
    "sales.shipments": "vca",
    "sales.shipped_lots": "v"
  },
  "satin_alma": {
    "inventory.receipt_prices": "c",
    "inventory.receipts": "v",
    "purchasing.deliveries": "vc",
    "purchasing.orders": "vca",
    "purchasing.performance": "v",
    "purchasing.requests": "vc",
    "purchasing.suggestions": "v",
    "reporting.stock": "v",
    "sensitive.prices": "v"
  }
};

/** Kayıt türü → okuyabilen bölümler (bölümlerden birinde okuma yeter). */
export const READERS: Readonly<Record<string, readonly PermKey[]>> = {
  "filling.fillingorder": [
    "filling.orders",
    "filling.prep",
    "filling.runs"
  ],
  "filling.fillingrun": [
    "filling.orders",
    "filling.prep",
    "filling.runs"
  ],
  "filling.packagingspec": [
    "filling.specs"
  ],
  "hse.incident": [
    "hse.incident_report",
    "hse.incidents"
  ],
  "hse.safetydatasheet": [
    "hse.sds"
  ],
  "hse.wasterecord": [
    "hse.waste"
  ],
  "inventory.goodsreceipt": [
    "inventory.receipts"
  ],
  "inventory.lot": [
    "inventory.lots"
  ],
  "inventory.stockadjustment": [
    "inventory.adjustments"
  ],
  "maintenance.maintenanceworkorder": [
    "maintenance.work_orders"
  ],
  "production.productionbatch": [
    "production.orders",
    "production.prep",
    "production.batches"
  ],
  "production.productionorder": [
    "production.orders",
    "production.prep",
    "production.batches"
  ],
  "purchasing.purchaseorder": [
    "purchasing.orders"
  ],
  "quality.sample": [
    "quality.samples",
    "quality.conditional"
  ],
  "returns.customerreturn": [
    "returns.returns"
  ],
  "sales.salesorder": [
    "sales.orders"
  ],
  "sales.shipment": [
    "sales.shipments",
    "sales.picking"
  ]
};

/** Alan grubu → tam gösteren bölümler (Görür); grubun modülünün Açık kayıtlar satırı da yeter. */
export const FIELD_OPENERS: Readonly<Record<string, readonly PermKey[]>> = {
  "masterdata.customer.contact": [
    "masterdata.cards",
    "sales.orders"
  ],
  "masterdata.supplier.contact": [
    "masterdata.cards"
  ]
};
