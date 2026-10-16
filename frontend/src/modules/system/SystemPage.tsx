import { Stack, Tabs, Title } from "@mantine/core";
import { useNavigate, useParams } from "react-router-dom";
import { DevicePanel } from "./DevicePanel";
import { StatusPanel } from "./StatusPanel";
import { SYSTEM_BASE, TABS, type TabKey } from "./config";
import { sy } from "./strings";
import { UsersPanel } from "./UsersPanel";

function tabFromPath(value: string | undefined): TabKey {
  return (Object.keys(TABS) as TabKey[]).find((key) => TABS[key] === value) ?? "status";
}

/** Sistem (yalnızca admin): sistem durumu ve yedekler, kullanıcı kilidi ve 2FA, saha tableti. */
export function SystemPage() {
  const tab = tabFromPath(useParams().tab);
  const navigate = useNavigate();
  return (
    <Stack>
      <Title order={2}>{sy.title}</Title>
      <Tabs
        value={tab}
        onChange={(value) => value && navigate(`${SYSTEM_BASE}/${TABS[value as TabKey]}`)}
      >
        <Tabs.List>
          {(Object.keys(TABS) as TabKey[]).map((key) => (
            <Tabs.Tab key={key} value={key}>
              {sy.tabs[key]}
            </Tabs.Tab>
          ))}
        </Tabs.List>
      </Tabs>
      {tab === "status" && <StatusPanel />}
      {tab === "users" && <UsersPanel />}
      {tab === "device" && <DevicePanel />}
    </Stack>
  );
}
