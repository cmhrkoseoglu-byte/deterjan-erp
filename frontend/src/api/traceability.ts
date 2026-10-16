// /api/v1/traceability/* uç noktaları (geri / ileri izleme, geri çağırma; Faz 3 Adım 3.4).
// Miktarlar lotun malzemesinin temel biriminde, metin olarak gelir.
import { api } from "./client";
import type { LotStatus, TraceNode } from "./inventory";
import type { MaterialType } from "./masterdata";

export interface ShipmentRow {
  lot_id: number;
  document_number: string;
  source_model: string | null;
  source_id: number | null;
  shipped_at: string;
  quantity: string;
  /** Sevkiyat modülü bağlanana kadar boş. */
  customer_id: number | null;
  customer_code: string | null;
  customer_name: string | null;
}

export interface BackwardNode extends Omit<TraceNode, "children"> {
  manufactured_at: string | null;
  supplier_id: number | null;
  supplier_code: string | null;
  supplier_name: string | null;
  supplier_lot_no: string;
  receipt_id: number | null;
  receipt_number: string | null;
  receipt_date: string | null;
  children: BackwardNode[];
}

export interface ForwardNode extends Omit<TraceNode, "children"> {
  on_hand: string;
  shipped: string;
  returned: string;
  shipments: ShipmentRow[];
  children: ForwardNode[];
}

interface LotRef {
  lot_id: number;
  lot_no: string;
  lot_status: LotStatus;
  material_id: number;
  material_code: string;
  material_name: string;
  material_type: MaterialType;
  unit: string;
}

export interface RecallLot {
  id: number;
  lot_no: string;
  status: LotStatus;
  status_display: string;
  material_id: number;
  material_code: string;
  material_name: string;
  material_type: MaterialType;
  unit: string;
  expiry_date: string | null;
  is_selected: boolean;
  on_hand: string;
  shipped: string;
  returned: string;
}

export interface RecallStock extends LotRef {
  location_id: number;
  location_code: string;
  location_name: string;
  location_type: string;
  warehouse_code: string;
  quantity: string;
}

export type RecallShipment = LotRef & ShipmentRow;

export interface RecallCustomer {
  customer_id: number | null;
  customer_code: string | null;
  customer_name: string | null;
  material_id: number;
  material_code: string;
  material_name: string;
  unit: string;
  quantity: string;
  lots: string[];
  documents: string[];
}

export interface RecallResult {
  selected: number[];
  lots: RecallLot[];
  stock: RecallStock[];
  shipments: RecallShipment[];
  customers: RecallCustomer[];
  summary: {
    lot_count: number;
    finished_lot_count: number;
    lots_in_stock: number;
    shipped_lot_count: number;
    shipment_count: number;
    customer_count: number;
  };
}

export async function getBackwardTrace(lotId: number): Promise<BackwardNode> {
  const { data } = await api.get<BackwardNode>(`/traceability/lots/${lotId}/backward/`);
  return data;
}

export async function getForwardTrace(lotId: number): Promise<ForwardNode> {
  const { data } = await api.get<ForwardNode>(`/traceability/lots/${lotId}/forward/`);
  return data;
}

function lotQuery(lotIds: number[]): string {
  return lotIds.map((id) => `lot=${id}`).join("&");
}

export async function getRecall(lotIds: number[]): Promise<RecallResult> {
  const { data } = await api.get<RecallResult>(`/traceability/recall/?${lotQuery(lotIds)}`);
  return data;
}

export function recallExportUrl(lotIds: number[], format: "xlsx" | "pdf"): string {
  return `/api/v1/traceability/recall/${format}/?${lotQuery(lotIds)}`;
}
