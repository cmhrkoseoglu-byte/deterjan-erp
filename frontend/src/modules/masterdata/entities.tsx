import { Badge, Select } from "@mantine/core";
import type { Printer } from "../../api/labels";
import type {
  Category,
  Conversion,
  Equipment,
  Location,
  Material,
  Partner,
  Unit,
  Warehouse,
} from "../../api/masterdata";
import type { Role } from "../../api/types";
import { formatNumber } from "../../i18n/format";
import type { EntityConfig } from "../common/CrudPage";
import type { FieldDef } from "../common/forms";
import { LocationLabelAction, PrinterTestAction } from "./LabelTools";

// Ana verileri planlama yazar (admin her yere erişir); birimleri yalnızca admin.
// Backend'deki izinlerle aynı tutulur: apps/masterdata/api/views.py.
const WRITE: Role[] = ["planlama"];
const ADMIN_ONLY: Role[] = ["admin"];

export const MATERIAL_TYPES = [
  { value: "RAW", label: "Hammadde" },
  { value: "PACKAGING", label: "Ambalaj" },
  { value: "BULK", label: "Yarı mamul (dökme)" },
  { value: "FINISHED", label: "Mamul" },
];

const UNIT_KINDS = [
  { value: "MASS", label: "Kütle" },
  { value: "VOLUME", label: "Hacim" },
  { value: "COUNT", label: "Adet" },
];

const LOCATION_TYPES = [
  { value: "STORAGE", label: "Depolama" },
  { value: "QUARANTINE", label: "Karantina" },
  { value: "PRODUCTION", label: "Üretim" },
  { value: "SHIPPING", label: "Sevkiyat" },
  { value: "TANK", label: "Tank" },
];

const EQUIPMENT_TYPES = [
  { value: "MIXING_TANK", label: "Karıştırma tankı" },
  { value: "STORAGE_TANK", label: "Stok tankı" },
  { value: "FILLING_LINE", label: "Dolum hattı" },
  { value: "SCALE", label: "Terazi" },
  { value: "OTHER", label: "Diğer" },
];

const code: FieldDef = { name: "code", label: "Kod", type: "text", required: true };
const name: FieldDef = { name: "name", label: "Ad", type: "text", required: true };

const codeColumn = { key: "code", label: "Kod" };
const nameColumn = { key: "name", label: "Ad" };

function selectFilter(
  label: string,
  field: string,
  options: { value: string; label: string }[],
): NonNullable<EntityConfig<never>["filters"]> {
  return (values, set) => (
    <Select
      aria-label={label}
      placeholder={label}
      data={options}
      value={values[field] ?? null}
      onChange={(value) => set(field, value ?? "")}
      clearable
      w={200}
    />
  );
}

export const materialConfig: EntityConfig<Material> = {
  endpoint: "materials",
  title: "Malzemeler",
  singular: "Malzeme",
  writeRoles: WRITE,
  importKind: "materials",
  columns: [
    codeColumn,
    nameColumn,
    { key: "material_type", label: "Tür", render: (row) => row.material_type_display },
    { key: "base_unit", label: "Temel birim", render: (row) => row.base_unit_code },
    { key: "category", label: "Kategori", render: (row) => row.category_name ?? "" },
    {
      key: "flags",
      label: "",
      render: (row) =>
        row.is_hazardous ? (
          <Badge color="orange" variant="light">
            Tehlikeli
          </Badge>
        ) : null,
    },
  ],
  fields: [
    code,
    name,
    {
      name: "material_type",
      label: "Tür",
      type: "select",
      required: true,
      options: MATERIAL_TYPES,
    },
    {
      name: "base_unit",
      label: "Temel birim",
      type: "relation",
      required: true,
      relation: { endpoint: "units" },
      description: "Stok bu birimde tutulur",
    },
    { name: "category", label: "Kategori", type: "relation", relation: { endpoint: "categories" } },
    {
      name: "density",
      label: "Yoğunluk (g/ml)",
      type: "decimal",
      description: "kg ↔ lt dönüşümü için",
    },
    { name: "shelf_life_days", label: "Raf ömrü (gün)", type: "integer" },
    { name: "min_stock", label: "Minimum stok", type: "decimal", description: "Temel birimde" },
    {
      name: "gtin",
      label: "GTIN (barkod no)",
      type: "text",
      description: "Mamulde doluysa koli etiketi GS1-128 basılır (8, 12, 13 ya da 14 hane)",
    },
    { name: "requires_incoming_qc", label: "Giriş kontrolü gerekli", type: "checkbox" },
    { name: "is_hazardous", label: "Tehlikeli madde", type: "checkbox" },
    { name: "storage_notes", label: "Depolama notu", type: "textarea" },
  ],
  defaults: { requires_incoming_qc: true, material_type: "RAW" },
  filters: selectFilter("Tür", "material_type", MATERIAL_TYPES),
};

export const conversionConfig: EntityConfig<Conversion & { code?: string; name?: string }> = {
  endpoint: "conversions",
  title: "Birim dönüşümleri",
  singular: "Birim dönüşümü",
  writeRoles: WRITE,
  columns: [
    { key: "material", label: "Malzeme", render: (row) => row.material_code },
    {
      key: "factor",
      label: "Dönüşüm",
      render: (row) =>
        `1 ${row.unit_code} = ${formatNumber(row.factor_to_base, undefined)} ${row.base_unit_code}`,
    },
  ],
  fields: [
    {
      name: "material",
      label: "Malzeme",
      type: "relation",
      required: true,
      relation: { endpoint: "materials" },
      lockedOnEdit: true,
      wide: true,
    },
    {
      name: "unit",
      label: "Birim",
      type: "relation",
      required: true,
      relation: { endpoint: "units" },
      lockedOnEdit: true,
    },
    {
      name: "factor_to_base",
      label: "Temel birim karşılığı",
      type: "decimal",
      required: true,
      description: "1 birim kaç temel birim eder (1 KOLI = 12 ADET → 12)",
    },
  ],
};

export const categoryConfig: EntityConfig<Category> = {
  endpoint: "categories",
  title: "Kategoriler",
  singular: "Kategori",
  writeRoles: WRITE,
  columns: [codeColumn, nameColumn],
  fields: [code, name],
};

export const unitConfig: EntityConfig<Unit> = {
  endpoint: "units",
  title: "Birimler",
  singular: "Birim",
  writeRoles: ADMIN_ONLY,
  columns: [
    codeColumn,
    nameColumn,
    { key: "kind", label: "Tür", render: (row) => row.kind_display },
    {
      key: "factor_to_kind_base",
      label: "Tür temel birimine katsayı",
      render: (row) => formatNumber(row.factor_to_kind_base, undefined) || "Malzemeye özel",
    },
  ],
  fields: [
    code,
    name,
    { name: "kind", label: "Tür", type: "select", required: true, options: UNIT_KINDS },
    {
      name: "factor_to_kind_base",
      label: "Tür temel birimine katsayı",
      type: "decimal",
      description: "KG ve LT için 1, G ve ML için 0,001. Koli gibi birimlerde boş bırakın.",
    },
  ],
};

export const warehouseConfig: EntityConfig<Warehouse> = {
  endpoint: "warehouses",
  title: "Depolar",
  singular: "Depo",
  writeRoles: WRITE,
  columns: [codeColumn, nameColumn],
  fields: [code, name],
};

export const locationConfig: EntityConfig<Location> = {
  endpoint: "locations",
  title: "Lokasyonlar",
  singular: "Lokasyon",
  writeRoles: WRITE,
  columns: [
    codeColumn,
    nameColumn,
    { key: "warehouse", label: "Depo", render: (row) => row.warehouse_code },
    { key: "location_type", label: "Tür", render: (row) => row.location_type_display },
  ],
  fields: [
    {
      name: "warehouse",
      label: "Depo",
      type: "relation",
      required: true,
      relation: { endpoint: "warehouses" },
    },
    code,
    name,
    {
      name: "location_type",
      label: "Tür",
      type: "select",
      required: true,
      options: LOCATION_TYPES,
      description: "Tanklar da birer lokasyondur (üretilen ürün tankta durur)",
    },
  ],
  defaults: { location_type: "STORAGE" },
  rowActions: (row) => <LocationLabelAction row={row} />,
  filters: selectFilter("Tür", "location_type", LOCATION_TYPES),
};

export const equipmentConfig: EntityConfig<Equipment> = {
  endpoint: "equipment",
  title: "Ekipmanlar",
  singular: "Ekipman",
  writeRoles: WRITE,
  columns: [
    codeColumn,
    nameColumn,
    { key: "equipment_type", label: "Tür", render: (row) => row.equipment_type_display },
    {
      key: "capacity",
      label: "Kapasite",
      render: (row) =>
        row.capacity ? `${formatNumber(row.capacity)} ${row.capacity_unit_code ?? ""}` : "",
    },
    { key: "location", label: "Lokasyon", render: (row) => row.location_code ?? "" },
  ],
  fields: [
    code,
    name,
    {
      name: "equipment_type",
      label: "Tür",
      type: "select",
      required: true,
      options: EQUIPMENT_TYPES,
    },
    {
      name: "location",
      label: "Lokasyon",
      type: "relation",
      relation: { endpoint: "locations" },
      description: "Tanklar için zorunlu; “Tank” türünde lokasyon seçin",
    },
    { name: "capacity", label: "Kapasite", type: "decimal" },
    {
      name: "capacity_unit",
      label: "Kapasite birimi",
      type: "relation",
      relation: { endpoint: "units" },
    },
  ],
  defaults: { equipment_type: "MIXING_TANK" },
  filters: selectFilter("Tür", "equipment_type", EQUIPMENT_TYPES),
};

const partnerFields: FieldDef[] = [
  code,
  { name: "name", label: "Ünvan", type: "text", required: true, wide: true },
  { name: "tax_office", label: "Vergi dairesi", type: "text" },
  { name: "tax_number", label: "Vergi no / TCKN", type: "text" },
  { name: "phone", label: "Telefon", type: "text" },
  { name: "email", label: "E-posta", type: "email" },
  { name: "contact_person", label: "Yetkili kişi", type: "text" },
  { name: "address", label: "Adres", type: "textarea" },
];

const partnerColumns = [
  codeColumn,
  { key: "name", label: "Ünvan" },
  { key: "tax_number", label: "Vergi no" },
  { key: "phone", label: "Telefon" },
  { key: "contact_person", label: "Yetkili" },
];

export const supplierConfig: EntityConfig<Partner> = {
  endpoint: "suppliers",
  title: "Tedarikçiler",
  singular: "Tedarikçi",
  writeRoles: WRITE,
  importKind: "suppliers",
  columns: partnerColumns,
  fields: partnerFields,
};

export const customerConfig: EntityConfig<Partner> = {
  endpoint: "customers",
  title: "Müşteriler",
  singular: "Müşteri",
  writeRoles: WRITE,
  importKind: "customers",
  columns: partnerColumns,
  fields: partnerFields,
};

export const printerConfig: EntityConfig<Printer> = {
  endpoint: "printers",
  title: "Yazıcılar",
  singular: "Yazıcı",
  writeRoles: ADMIN_ONLY,
  columns: [
    codeColumn,
    nameColumn,
    { key: "host", label: "Adres", render: (row) => `${row.host}:${row.port}` },
    { key: "dpi", label: "Çözünürlük", render: (row) => `${row.dpi} dpi` },
    { key: "location", label: "Lokasyon", render: (row) => row.location_code ?? "" },
  ],
  fields: [
    code,
    name,
    {
      name: "host",
      label: "IP adresi",
      type: "text",
      required: true,
      description: "Zebra yazıcının ağ adresi (ör. 192.168.1.50)",
    },
    { name: "port", label: "Port", type: "integer", required: true },
    {
      name: "dpi",
      label: "Çözünürlük (dpi)",
      type: "select",
      required: true,
      options: [
        { value: "203", label: "203 dpi" },
        { value: "300", label: "300 dpi" },
        { value: "600", label: "600 dpi" },
      ],
    },
    { name: "location", label: "Lokasyon", type: "relation", relation: { endpoint: "locations" } },
    { name: "note", label: "Not", type: "textarea" },
  ],
  defaults: { port: "9100", dpi: "203" },
  rowActions: (row) => <PrinterTestAction row={row} />,
};
