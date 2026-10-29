import { Tabs } from "@mantine/core";
import { useNavigate } from "react-router-dom";
import { at, ATTENDANCE_BASE, HOLIDAYS_BASE, PERSONNEL_BASE } from "./strings";

const TABS = [
  { value: PERSONNEL_BASE, label: at.tabs.cards },
  { value: ATTENDANCE_BASE, label: at.tabs.attendance },
  { value: HOLIDAYS_BASE, label: at.tabs.holidays },
];

/** Personel bölümünün sekmeleri: kartlar, puantaj, tatil takvimi. */
export function PersonnelTabs({ active }: { active: string }) {
  const navigate = useNavigate();
  return (
    <Tabs value={active} onChange={(value) => value && navigate(value)}>
      <Tabs.List style={{ overflowX: "auto", flexWrap: "nowrap" }}>
        {TABS.map((tab) => (
          <Tabs.Tab key={tab.value} value={tab.value}>
            {tab.label}
          </Tabs.Tab>
        ))}
      </Tabs.List>
    </Tabs>
  );
}
