export const REPORTING_BASE = "/raporlar";
export const TABS = { dashboards: "panolar", reports: "raporlar", jobs: "indirmeler" } as const;
export type TabKey = keyof typeof TABS;
export const jobsPath = `${REPORTING_BASE}/${TABS.jobs}`;
