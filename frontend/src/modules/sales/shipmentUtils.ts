import { useQueryClient } from "@tanstack/react-query";
import type { ShipmentDetail, ShipmentLine } from "../../api/sales";

/** Satırın kalan (toplanmamış) miktarı. */
export function lineRemaining(line: ShipmentLine): number {
  return Math.max(0, Number(line.quantity) - Number(line.picked_quantity ?? 0));
}

/** Sevkiyat sorgularını yeniler (detay, listeler, sipariş ve görevler). */
export function useShipmentRefresh() {
  const queryClient = useQueryClient();
  return (saved: ShipmentDetail) => {
    queryClient.setQueryData(["sales", "shipment", saved.id], saved);
    void queryClient.invalidateQueries({ queryKey: ["sales"] });
    void queryClient.invalidateQueries({ queryKey: ["workflow"] });
  };
}
