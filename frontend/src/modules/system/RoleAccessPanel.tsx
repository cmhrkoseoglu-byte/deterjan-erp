import {
  Alert,
  Button,
  Group,
  Select,
  Stack,
  Table,
  Text,
  Tooltip,
  UnstyledButton,
} from "@mantine/core";
import { IconFileSpreadsheet, IconInfoCircle } from "@tabler/icons-react";
import { Fragment, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ACCESS_REPORT_EXPORT_URL } from "../../api/access";
import { ROLES } from "../../api/types";
import { describeAccess } from "../../auth/access";
import {
  HOLDER_LABELS,
  MODULES,
  PACKAGES,
  SECTIONS,
  type AccessLevel,
  type PermKey,
} from "../../auth/access.gen";
import { sy } from "./strings";
import { WhoHasModal } from "./WhoHasModal";

const HOLDERS: readonly string[] = ["*", ...ROLES.filter((role) => role !== "admin")];
const LEVEL_ORDER: readonly [AccessLevel, string][] = [
  ["read", "r"],
  ["view", "v"],
  ["change", "c"],
  ["approve", "a"],
];

interface Letter {
  level: AccessLevel;
  /** Rolü olan herkesin paketinden ("+"). */
  anyRole: boolean;
}

/** Paket sahibinin bölümdeki düzeyleri: rol sütunlarında "+" paketi de görünür (soluk). */
function lettersFor(holder: string, key: string): Letter[] {
  const own = PACKAGES[holder]?.[key] ?? "";
  const plus = holder === "*" ? "" : (PACKAGES["+"]?.[key] ?? "");
  return LEVEL_ORDER.filter(([, letter]) => own.includes(letter) || plus.includes(letter)).map(
    ([level, letter]) => ({ level, anyRole: !own.includes(letter) }),
  );
}

export interface WhoHasTarget {
  key: string;
  level: AccessLevel;
  holder: string;
}

/**
 * Sistem > Rol yetkileri (salt okunur; plan §6.2): rol paketleri tek tabloda, Herkes ve 8 rol;
 * hücredeki harfe basınca "Kimde var?". Rol seçimi adreste (`?rol=`).
 */
export function RoleAccessPanel() {
  const [params, setParams] = useSearchParams();
  const selected = params.get("rol");
  const holder = selected && HOLDERS.includes(selected) ? selected : null;
  const columns = holder ? [holder] : HOLDERS;
  const [target, setTarget] = useState<WhoHasTarget | null>(null);

  function choose(value: string | null) {
    const next = new URLSearchParams(params);
    if (value) next.set("rol", value);
    else next.delete("rol");
    setParams(next, { replace: true });
  }

  return (
    <Stack>
      <Alert color="blue" variant="light" icon={<IconInfoCircle size={18} />}>
        <Text size="sm">{sy.roleAccessIntro}</Text>
      </Alert>
      <Group justify="space-between" align="flex-end">
        <Select
          label={sy.roleSelect}
          placeholder={sy.roleSelectAll}
          data={HOLDERS.map((item) => ({ value: item, label: HOLDER_LABELS[item] ?? item }))}
          value={holder}
          onChange={choose}
          clearable
          maw={260}
        />
        <Button
          component="a"
          href={ACCESS_REPORT_EXPORT_URL}
          variant="light"
          leftSection={<IconFileSpreadsheet size={18} />}
        >
          {sy.exportExcel}
        </Button>
      </Group>
      <Text size="xs" c="dimmed">
        {sy.legend}
      </Text>
      <Table.ScrollContainer minWidth={holder ? 420 : 1000}>
        <Table striped withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{sy.sectionColumn}</Table.Th>
              {columns.map((item) => (
                <Table.Th key={item} ta="center">
                  {HOLDER_LABELS[item] ?? item}
                </Table.Th>
              ))}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {MODULES.map((module) => (
              <Fragment key={module.key}>
                <Table.Tr>
                  <Table.Td colSpan={columns.length + 1}>
                    <Text fw={600} size="sm">
                      {module.label}
                    </Text>
                  </Table.Td>
                </Table.Tr>
                {module.sections.map((key: PermKey) => (
                  <Table.Tr key={key}>
                    <Table.Td>
                      <Text size="sm">{SECTIONS[key].label}</Text>
                    </Table.Td>
                    {columns.map((item) => (
                      <Table.Td key={item} ta="center">
                        <Group gap={6} justify="center" wrap="nowrap">
                          {lettersFor(item, key).map((letter) => {
                            const text = describeAccess({ key, level: letter.level }) ?? key;
                            const button = (
                              <UnstyledButton
                                key={letter.level}
                                aria-label={sy.whoHasCell(HOLDER_LABELS[item] ?? item, text)}
                                onClick={() =>
                                  setTarget({ key, level: letter.level, holder: item })
                                }
                                fw={700}
                                fz="sm"
                                c={letter.anyRole ? "dimmed" : undefined}
                              >
                                {sy.levelLetters[letter.level]}
                              </UnstyledButton>
                            );
                            return letter.anyRole ? (
                              <Tooltip key={letter.level} label={sy.anyRoleHint}>
                                {button}
                              </Tooltip>
                            ) : (
                              button
                            );
                          })}
                        </Group>
                      </Table.Td>
                    ))}
                  </Table.Tr>
                ))}
              </Fragment>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {target && <WhoHasModal target={target} onClose={() => setTarget(null)} />}
    </Stack>
  );
}
