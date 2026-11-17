import {
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  Loader,
  Paper,
  Stack,
  Switch,
  Tabs,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconAlertTriangle, IconInfoCircle, IconSearch } from "@tabler/icons-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import { useCallback, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  fetchUserAccess,
  type AccessSaveInput,
  type AccessSaveResult,
  type SavedOverride,
  type UserAccess,
} from "../../../api/access";
import { accessKeys } from "../../../api/accessKeys";
import { getErrorMessage } from "../../../api/client";
import { moduleVisible } from "../../../auth/access";
import { ACCESS_CATALOG_HASH, MODULES, type AccessLevel } from "../../../auth/access.gen";
import { useUnsavedChangesPrompt } from "../../../components/useUnsavedChangesPrompt";
import { ForbiddenPage } from "../../../pages/ForbiddenPage";
import { AccessHistory } from "./AccessHistory";
import {
  cellId,
  cleanIneffective,
  defaultLetters,
  diff,
  ineffectiveCount,
  overridesFrom,
  parseCellId,
  previewAccess,
  removeAllInModule,
  resetAll,
  resetModule,
  section,
  setColumn,
  settle,
  toggle,
  toOverrides,
  viewOnlyModule,
  type Draft,
  type GrantLevel,
  type Note,
} from "./matrix";
import { menuUser as previewUser } from "./menuDiff";
import { ModuleBlock, SectionRows } from "./ModuleBlock";
import { RolesSection } from "./RolesSection";
import { SaveBar } from "./SaveBar";
import { SaveSummaryModal } from "./SaveSummaryModal";
import { ua } from "./strings";

// Kullanıcı listesinin sorguları (UsersPanel); kişinin Yetkiler sorgusu bunun dışındadır.
const USERS_LIST_KEY = ["system", "users", "list"] as const;

function baseDraft(data: UserAccess): Draft {
  return {
    roles: [...data.roles],
    overrides: overridesFrom(data.overrides.filter((row) => row.known)),
  };
}

function searchText(key: string): string {
  const meta = section(key)!;
  const module = MODULES.find((item) => item.key === meta.module);
  return [module?.label ?? "", meta.label, ...Object.values(meta.help)]
    .join(" ")
    .toLocaleLowerCase("tr");
}

/**
 * Sistem > Kullanıcılar > Yetkiler (yalnız admin; plan §6.1): kişinin rolleri, hassas verileri ve
 * modül yetkileri; Geçmiş sekmesi. Kaydetmeden önce sunucunun ön izlemesi ve gerekçe istenir.
 */
export function UserAccessPage() {
  const id = Number(useParams().userId);
  const valid = Number.isInteger(id) && id > 0;
  const [params, setParams] = useSearchParams();
  const tab = params.get("sekme") === "gecmis" ? "history" : "access";
  const queryClient = useQueryClient();
  const mobile = useMediaQuery("(max-width: 48em)") ?? false;
  const query = useQuery({
    queryKey: accessKeys.user(id),
    queryFn: () => fetchUserAccess(id),
    enabled: valid,
  });

  const [source, setSource] = useState<UserAccess | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [notes, setNotes] = useState<Note[]>([]);
  // Kullanıcının açtığı ya da kapattığı modüller; yoksa varsayılan (kayıtlı ayarı olan modül açık).
  const [expanded, setExpanded] = useState<ReadonlyMap<string, boolean>>(new Map());
  const [search, setSearch] = useState("");
  const [onlyPersonal, setOnlyPersonal] = useState(false);
  const [saving, setSaving] = useState<Omit<AccessSaveInput, "note" | "dry_run"> | null>(null);

  const base = useMemo(() => (source ? baseDraft(source) : null), [source]);
  const changes = base && draft ? diff(base, draft) : null;
  const dirty = Boolean(changes && changes.count > 0);

  const adopt = useCallback((data: UserAccess) => {
    setSource(data);
    setDraft(baseDraft(data));
    setNotes([]);
  }, []);

  // Yeni veri gelince taslak boşsa ya da değişmemişse benimsenir; değişmişse taslak korunur ve
  // eşzamanlı değişiklik uyarısı çıkar (sürüm farklıysa).
  const data = query.data;
  if (data && data !== source && (!source || !dirty)) adopt(data);
  const stale = Boolean(data && source && dirty && data.version !== source.version);

  const prompt = useUnsavedChangesPrompt(dirty, {
    title: ua.leaveTitle,
    text: ua.leaveText,
    stay: ua.stay,
    leave: ua.leave,
  });

  const savedRows = useMemo(
    () =>
      new Map<string, SavedOverride>(
        (source?.overrides ?? []).map((row) => [cellId(row.key, row.level), row]),
      ),
    [source],
  );
  const savedIneffective = useMemo(
    () =>
      new Set(
        (source?.overrides ?? [])
          .filter((row) => row.ineffective)
          .map((row) => `${cellId(row.key, row.level)}|${row.effect}`),
      ),
    [source],
  );
  const defaults = useMemo(() => (draft ? defaultLetters(draft.roles) : {}), [draft]);
  const preview = useMemo(
    () => (draft ? previewAccess(draft.roles, draft.overrides) : {}),
    [draft],
  );

  if (!valid) return <NotFound />;
  if (query.isError) {
    if (axios.isAxiosError(query.error) && query.error.response?.status === 403)
      return <ForbiddenPage error={query.error} />;
    if (axios.isAxiosError(query.error) && query.error.response?.status === 404)
      return <NotFound />;
    return (
      <Alert color="red" variant="light">
        {getErrorMessage(query.error)}
      </Alert>
    );
  }
  if (!source || !draft || !base || !changes) return <Loader />;

  const user = source.user;
  const name = user.full_name.trim() || user.username;
  const adminTarget = user.is_superuser || draft.roles.includes("admin");
  const readOnly = source.is_self;
  const catalogStale = source.catalog_hash !== ACCESS_CATALOG_HASH;
  const unknownRows = source.overrides.filter((row) => !row.known);
  // Yönetim rolü kaldırılınca biten kayıtlı KVKK eklemeleri (kaydedilmemişler taslaktan kalkar).
  const kvkkGrants = [...base.overrides].some(
    ([idText, effect]) =>
      effect === "grant" && Boolean(section(parseCellId(idText).key)?.restrictedToRole),
  );

  function change(next: Draft, rowNotes: Note[] = [], keys: string[] = []) {
    // Sunucunun reddedeceği kaydedilmemiş eklemeler taslakta kalmaz (ör. rol değişince).
    const settled = settle(next, base!.overrides);
    setDraft(settled.draft);
    setNotes((current) => [
      ...current.filter((note) => !keys.includes(note.key)),
      ...rowNotes,
      ...settled.notes,
    ]);
  }

  function onToggle(key: string, level: AccessLevel) {
    const result = toggle(draft!, key, level, base!.overrides);
    change(result.draft, result.notes, [key]);
  }

  function onColumn(moduleKey: string, level: GrantLevel, on: boolean) {
    const result = setColumn(draft!, moduleKey, level, on, base!.overrides);
    const keys = MODULES.find((item) => item.key === moduleKey)?.sections ?? [];
    change(result.draft, result.notes, [...keys]);
  }

  function onBulk(moduleKey: string, action: "reset" | "viewOnly" | "removeAll") {
    const next =
      action === "reset"
        ? resetModule(draft!, moduleKey)
        : action === "viewOnly"
          ? viewOnlyModule(draft!, moduleKey)
          : removeAllInModule(draft!, moduleKey);
    const keys = MODULES.find((item) => item.key === moduleKey)?.sections ?? [];
    change(next, [], [...keys]);
  }

  function startSave() {
    const rolesChanged = changes!.rolesAdded.length > 0 || changes!.rolesRemoved.length > 0;
    setSaving({
      version: source!.version,
      ...(rolesChanged ? { roles: draft!.roles } : {}),
      // Kişi admin oluyorsa kayıtlı ayarlar olduğu gibi gönderilir; sunucu hepsini bitirir.
      overrides: toOverrides(adminTarget ? base!.overrides : draft!.overrides),
    });
  }

  function onSaved(result: AccessSaveResult) {
    setSaving(null);
    if (result.matrix) {
      queryClient.setQueryData(accessKeys.user(id), result.matrix);
      adopt(result.matrix);
    } else {
      void query.refetch();
    }
    void queryClient.invalidateQueries({ queryKey: [...accessKeys.user(id), "history"] });
    void queryClient.invalidateQueries({ queryKey: USERS_LIST_KEY, exact: false });
    notifications.show({ color: "green", message: ua.saved(name) });
  }

  async function reload() {
    setSaving(null);
    const fresh = await query.refetch();
    if (fresh.data) adopt(fresh.data);
  }

  const needle = search.trim().toLocaleLowerCase("tr");
  const personalKeys = new Set(
    [...draft.overrides.keys(), ...base.overrides.keys()].map((idText) => parseCellId(idText).key),
  );
  const filtering = Boolean(needle) || onlyPersonal;
  function visibleKeys(keys: readonly string[]): string[] {
    return keys.filter(
      (key) =>
        (!needle || searchText(key).includes(needle)) && (!onlyPersonal || personalKeys.has(key)),
    );
  }
  const rowsBase = {
    draft,
    saved: base.overrides,
    savedRows,
    defaults,
    preview,
    notes,
    mobile,
    readOnly,
    onToggle,
  };
  const sensitiveKeys = visibleKeys(MODULES.find((item) => item.key === "sensitive")!.sections);
  const modules = MODULES.filter((item) => item.key !== "sensitive")
    .map((item) => ({ item, keys: visibleKeys(item.sections) }))
    .filter(({ keys }) => keys.length > 0);
  const menuUser = previewUser(draft.roles, preview);
  const cleanable = ineffectiveCount(draft, savedIneffective, base.roles);

  return (
    <Stack pb={dirty ? 96 : undefined}>
      <Anchor component={Link} to="/sistem/kullanicilar" size="sm">
        {ua.back}
      </Anchor>
      <Stack gap={4}>
        <Title order={2}>{ua.title(name)}</Title>
        <Group gap="xs">
          <Text size="sm" c="dimmed" ff="monospace">
            {user.username}
          </Text>
          {!user.is_active && (
            <Badge size="sm" color="gray">
              {ua.inactive}
            </Badge>
          )}
          {user.is_superuser && (
            <Badge size="sm" color="grape" variant="light">
              {ua.superuser}
            </Badge>
          )}
          {!user.otp_enabled && (
            <Badge size="sm" variant="outline" color="gray">
              {ua.noOtp}
            </Badge>
          )}
        </Group>
      </Stack>
      <Tabs
        value={tab}
        onChange={(value) =>
          setParams(value === "history" ? { sekme: "gecmis" } : {}, { replace: true })
        }
      >
        <Tabs.List>
          <Tabs.Tab value="access">{ua.tabAccess}</Tabs.Tab>
          <Tabs.Tab value="history">{ua.tabHistory}</Tabs.Tab>
        </Tabs.List>
      </Tabs>
      {tab === "history" ? (
        <AccessHistory userId={id} />
      ) : (
        <>
          {catalogStale && (
            <Alert color="red" variant="light" icon={<IconAlertTriangle size={18} />}>
              {ua.staleCatalog}
            </Alert>
          )}
          {stale && (
            <Alert color="orange" variant="light" icon={<IconAlertTriangle size={18} />}>
              <Stack gap="xs">
                <Text size="sm">{ua.changedWhileEditing}</Text>
                <Group>
                  <Button
                    size="xs"
                    variant="light"
                    color="orange"
                    onClick={() => data && adopt(data)}
                  >
                    {ua.discardAndReload}
                  </Button>
                </Group>
              </Stack>
            </Alert>
          )}
          {(!user.is_active || draft.roles.length === 0 || source.is_self) && (
            <Alert color="blue" variant="light" icon={<IconInfoCircle size={18} />}>
              <Stack gap={2}>
                {!user.is_active && <Text size="sm">{ua.inactiveWarning}</Text>}
                {draft.roles.length === 0 && <Text size="sm">{ua.noRoleWarning}</Text>}
                {source.is_self && <Text size="sm">{ua.selfWarning}</Text>}
              </Stack>
            </Alert>
          )}
          <RolesSection
            roles={draft.roles}
            savedRoles={base.roles}
            isSelf={source.is_self}
            activeOverrides={base.overrides.size}
            kvkkGrants={kvkkGrants}
            onChange={(roles) => change({ roles, overrides: draft.overrides })}
          />
          {adminTarget ? (
            <Alert color="grape" variant="light" icon={<IconInfoCircle size={18} />}>
              {ua.adminText}
            </Alert>
          ) : (
            <>
              <Group gap="md" align="flex-end" wrap="wrap">
                <TextInput
                  aria-label={ua.search}
                  placeholder={ua.search}
                  leftSection={<IconSearch size={16} />}
                  value={search}
                  onChange={(event) => setSearch(event.currentTarget.value)}
                  maw={320}
                  style={{ flex: 1 }}
                />
                <Switch
                  label={ua.onlyPersonal}
                  checked={onlyPersonal}
                  onChange={(event) => setOnlyPersonal(event.currentTarget.checked)}
                />
                {!readOnly && (
                  <Group gap="xs">
                    <Button
                      size="xs"
                      variant="default"
                      disabled={draft.overrides.size === 0}
                      onClick={() => change(resetAll(draft), [], [...personalKeys])}
                    >
                      {ua.resetAll}
                    </Button>
                    <Button
                      size="xs"
                      variant="default"
                      disabled={cleanable === 0}
                      onClick={() => change(cleanIneffective(draft, savedIneffective, base.roles))}
                    >
                      {ua.cleanIneffective}
                    </Button>
                  </Group>
                )}
              </Group>
              {unknownRows.length > 0 && (
                <Alert color="gray" variant="light" title={ua.retiredTitle}>
                  <Stack gap={2}>
                    <Text size="sm">{ua.retiredHelp}</Text>
                    {unknownRows.map((row) => (
                      <Text size="sm" ff="monospace" key={row.id}>
                        {row.key} ({row.level}, {row.effect})
                      </Text>
                    ))}
                  </Stack>
                </Alert>
              )}
              {sensitiveKeys.length > 0 && (
                <Paper withBorder radius="md" p="sm" role="region" aria-label={ua.sensitiveTitle}>
                  <Stack gap="xs">
                    <Title order={4}>{ua.sensitiveTitle}</Title>
                    <SectionRows {...rowsBase} keys={sensitiveKeys} effects={[]} />
                    <Text size="xs" c="dimmed">
                      {ua.kvkkNote}
                    </Text>
                  </Stack>
                </Paper>
              )}
              <Title order={4}>{ua.modulesTitle}</Title>
              {modules.length === 0 && <Text c="dimmed">{ua.noMatch}</Text>}
              {modules.map(({ item, keys }) => {
                const count = [...draft.overrides.keys()].filter((idText) =>
                  (item.sections as readonly string[]).includes(parseCellId(idText).key),
                ).length;
                // Kayıtlı kişiye özel ayarı olan modül açık başlar; aramada eşleşen modüller açıktır.
                const saved = [...base.overrides.keys()].some((idText) =>
                  (item.sections as readonly string[]).includes(parseCellId(idText).key),
                );
                const open = filtering || (expanded.get(item.key) ?? saved);
                return (
                  <ModuleBlock
                    key={item.key}
                    {...rowsBase}
                    keys={keys}
                    effects={source.open_records_effects[item.key] ?? []}
                    moduleKey={item.key}
                    label={item.label}
                    inMenu={item.menu ? moduleVisible(menuUser, item.key) : null}
                    overrideCount={count}
                    expanded={open}
                    onExpand={() => setExpanded((current) => new Map(current).set(item.key, !open))}
                    onColumn={(level, on) => onColumn(item.key, level, on)}
                    onBulk={(action) => onBulk(item.key, action)}
                  />
                );
              })}
            </>
          )}
          {dirty && (
            <SaveBar
              count={changes.count}
              disabled={catalogStale || stale}
              onDiscard={() => change(base)}
              onSave={startSave}
            />
          )}
        </>
      )}
      {saving && (
        <SaveSummaryModal
          userId={id}
          superuser={user.is_superuser}
          input={saving}
          onClose={() => setSaving(null)}
          onSaved={onSaved}
          onReload={() => void reload()}
        />
      )}
      {prompt}
    </Stack>
  );
}

function NotFound() {
  return (
    <Stack>
      <Anchor component={Link} to="/sistem/kullanicilar" size="sm">
        {ua.back}
      </Anchor>
      <Alert color="red" variant="light">
        {ua.notFound}
      </Alert>
    </Stack>
  );
}
