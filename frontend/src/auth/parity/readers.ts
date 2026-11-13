import type { ManagementDashboard } from "../../api/reporting";
import { tr } from "../../i18n/tr";
import { GUIDES } from "../../modules/help/guides";
import { hs } from "../../modules/hse/strings";
import { mt } from "../../modules/maintenance/strings";
import { rt } from "../../modules/reporting/strings";

/** Sayfa başlığındaki bildirim düğmeleri: arıza (Görevlerim, Bakım) ve olay (İSG). */
const REPORT_BUTTONS: Record<string, string> = {
  [mt.reportBreakdown]: "breakdown",
  [hs.reportIncident]: "incident",
};

/** Sayfada görünen bildirim düğmeleri (`breakdown`, `incident`). */
export function readReportButtons(container: HTMLElement): string[] {
  const found = Array.from(container.querySelectorAll("button"), (button) => {
    return REPORT_BUTTONS[button.textContent?.trim() ?? ""];
  });
  return [...new Set(found.filter(Boolean))].sort();
}

/**
 * Yönetim panosu verisi: onay bekleyen, dikkat gerektiren ve açık emir kalemlerinin hepsi dolu,
 * böylece panodaki her hedefli bağlantının yeri çizilir.
 */
export function managementData(): ManagementDashboard {
  const period = { bulk: [{ unit: "KG", quantity: "100.0000", batches: 1 }], units: 10, runs: 1 };
  const status = (label: string) => [{ status: "APPROVED", label, count: 1 }];
  return {
    date: "2026-11-11",
    approvals: {
      conditional_acceptance: { count: 1, oldest_wait_hours: "30.00" },
      purchase_orders: { count: 1, total_try: null },
    },
    production: { today: period, week: period },
    daily: [{ date: "2026-11-11", bulk: [{ unit: "KG", quantity: "100.0000" }], units: 10 }],
    shipping: { dispatched_today: 1, late_orders: 1 },
    open_orders: {
      production: status("Onaylandı"),
      filling: status("Onaylandı"),
      sales: status("Onaylandı"),
    },
    qc_pending: { sample_count: 1, lot_count: 1, avg_wait_hours: "30.00", max_wait_hours: "30.00" },
    scrap: { days: 7, good_units: "10", scrap_units: "1", rate: "10.00" },
    critical_stock: {
      count: 1,
      items: [
        { material_id: 1, material: "M-1 — Malzeme", stock: "1", min_stock: "5", unit: "KG" },
      ],
    },
    expiring_lots: { days: 30, count: 0, expired_count: 1, items: [] },
    tasks: {
      overdue_total: 1,
      by_role: [{ role: "depo", label: "Depo", open: 1, overdue: 1, max_delay_hours: "30.00" }],
    },
    maintenance: {
      days: 7,
      open_work_orders: 1,
      due_plans: 1,
      overdue_plans: 1,
      open_downtimes: 1,
      downtime_minutes: 10,
    },
    hse: { days: 30, incidents: 1, injuries: 1, open_incidents: 1 },
    stock_value: null,
  };
}

/** Panodaki başlık → bölge: onay kartları, dikkat gerektirenler, açık emirler. */
const REGIONS: Record<string, string> = {
  [rt.approvalsMine]: "approvals",
  [rt.approvalsOthers]: "approvals",
  [rt.attention]: "attention",
  [rt.openOrders]: "openOrders",
};

function follows(anchor: Node, node: Node): boolean {
  return Boolean(anchor.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING);
}

/**
 * Yönetim panosunda gösterilen hedefli bağlantılar (`bölge → adres`) ve onay başlığının hangisi
 * olduğu ("Onayınızı bekleyenler" = `mine`, "Yönetim onayı bekleyenler" = `others`).
 */
export function readManagement(container: HTMLElement): { heading: string; links: string[] } {
  const titles = Array.from(container.querySelectorAll("h4"));
  const texts = titles.map((title) => title.textContent);
  const heading = texts.includes(rt.approvalsMine)
    ? "mine"
    : texts.includes(rt.approvalsOthers)
      ? "others"
      : "none";
  const links: string[] = [];
  for (const anchor of Array.from(container.querySelectorAll("a[href]"))) {
    const title = [...titles].reverse().find((node) => follows(node, anchor));
    const region = title ? REGIONS[title.textContent ?? ""] : undefined;
    if (region) links.push(`${region} → ${anchor.getAttribute("href")}`);
  }
  return { heading, links };
}

/** Yardım sayfası: "Rolünüzün kılavuzları" altındakiler ve açılan kılavuz (adres parçası). */
export function readHelp(container: HTMLElement): { mine: string[]; opened: string | null } {
  const items = Array.from(container.querySelectorAll(".mantine-NavLink-root"));
  const slug = (item: Element) => {
    const label = item.querySelector(".mantine-NavLink-label")?.textContent;
    const guide = GUIDES.find((entry) => entry.title === label);
    if (!guide) throw new Error(`Kılavuz bulunamadı: ${label}`);
    return guide.slug;
  };
  const paragraphs = Array.from(container.querySelectorAll("p"));
  const mineHeading = paragraphs.find((node) => node.textContent === tr.help.mine);
  const othersHeading = paragraphs.find((node) => node.textContent === tr.help.others);
  const mine =
    mineHeading && othersHeading
      ? items.filter((item) => follows(mineHeading, item) && follows(item, othersHeading))
      : [];
  const active = items.find((item) => item.hasAttribute("data-active"));
  return { mine: mine.map(slug), opened: active ? slug(active) : null };
}
