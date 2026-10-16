import type { ColumnKind, ReportInfo, ReportParams, ReportValue } from "../../api/reporting";
import { formatDate, formatDateTime, formatMoney, formatNumber } from "../../i18n/format";
import { today } from "../inventory/config";
import { rt } from "./strings";

export function formatValue(value: ReportValue, kind: ColumnKind): string {
  if (value === null || value === "") return "";
  switch (kind) {
    case "number":
      return formatNumber(value as string | number);
    case "money":
      return formatMoney(value as string | number);
    case "percent":
    case "duration":
      return formatNumber(value as string | number, 2);
    case "date":
      return formatDate(value as string);
    case "datetime":
      return formatDateTime(value as string);
    case "boolean":
      return value ? rt.yes : rt.no;
    default:
      return String(value);
  }
}

function daysAgo(days: number): string {
  const date = new Date(`${today()}T12:00:00`);
  date.setDate(date.getDate() - (days - 1));
  return date.toISOString().slice(0, 10);
}

export function defaultParams(report: ReportInfo): ReportParams {
  if (!report.default_days || !report.filters.includes("date_from")) return {};
  return { date_from: daysAgo(report.default_days), date_to: today() };
}
