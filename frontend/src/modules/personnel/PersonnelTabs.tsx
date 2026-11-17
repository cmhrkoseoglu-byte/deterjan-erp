import { Tabs } from "@mantine/core";
import { useNavigate } from "react-router-dom";
import { useCan } from "../../auth/access";
import { PERM } from "../../auth/access.gen";
import {
  at,
  ATTENDANCE_BASE,
  HOLIDAYS_BASE,
  PAYROLL_BASE,
  PERSONNEL_BASE,
  WAGES_BASE,
} from "./strings";

// Her alt sayfa tek bölüme aittir ve o bölümün Görür'üyle açılır (plan §5.9).
const TABS = [
  { value: PERSONNEL_BASE, label: at.tabs.cards, section: PERM.PERSONNEL_CARDS },
  { value: ATTENDANCE_BASE, label: at.tabs.attendance, section: PERM.PERSONNEL_ATTENDANCE },
  { value: WAGES_BASE, label: at.tabs.wages, section: PERM.PERSONNEL_WAGES },
  { value: PAYROLL_BASE, label: at.tabs.payroll, section: PERM.PERSONNEL_PAYROLL },
  { value: HOLIDAYS_BASE, label: at.tabs.holidays, section: PERM.PERSONNEL_ATTENDANCE },
];

/** Personel bölümünün sekmeleri: kartlar, puantaj, ücretler, bordro, tatil takvimi. */
export function PersonnelTabs({ active }: { active: string }) {
  const navigate = useNavigate();
  const { can } = useCan();
  return (
    <Tabs value={active} onChange={(value) => value && navigate(value)}>
      <Tabs.List style={{ overflowX: "auto", flexWrap: "nowrap" }}>
        {TABS.filter((tab) => can(tab.section)).map((tab) => (
          <Tabs.Tab key={tab.value} value={tab.value}>
            {tab.label}
          </Tabs.Tab>
        ))}
      </Tabs.List>
    </Tabs>
  );
}
