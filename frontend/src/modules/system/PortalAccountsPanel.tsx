// Sistem > Portal hesapları (yalnız admin; docs/plan/musteri-siparis-takibi.md §4.2): müşteri ve
// tedarikçi yetkililerinin portal hesapları. Hesap silinmez, bağlı firma değişmez.
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Menu,
  Modal,
  Pagination,
  SegmentedControl,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconDots, IconInfoCircle, IconSearch, IconUserPlus } from "@tabler/icons-react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { getErrorMessage } from "../../api/client";
import { listRecords, type Partner } from "../../api/masterdata";
import {
  createPortalAccount,
  listPortalAccounts,
  resetPortalPassword,
  setPortalAccountActive,
  unlockPortalAccount,
  type IssuedAccountPassword,
  type PortalAccount,
  type PortalKind,
} from "../../api/portal";
import { formatDateTime } from "../../i18n/format";
import { ConfirmModal } from "../common/ConfirmModal";
import { TemporaryPasswordModal, type IssuedTemporaryPassword } from "./TemporaryPasswordModal";

const KEY = ["portal", "accounts"] as const;
const PAGE_SIZE = 50;

const pa = {
  note: "Müşteri ve tedarikçi yetkilileri portalda yalnız kendi firmalarının siparişlerini, sevkiyat ya da teslimatlarını ve cari hesabını görür. Hesabı yalnız sistem yöneticisi açar; ilk şifre geçicidir, kişi ilk girişte kendi şifresini belirler.",
  search: "Kullanıcı, ad ya da firma ara",
  newAccount: "Yeni portal hesabı",
  all: "Hepsi",
  customer: "Müşteri",
  supplier: "Tedarikçi",
  account: "Hesap",
  firm: "Firma",
  kind: "Tür",
  state: "Durum",
  lastLogin: "Son giriş",
  never: "Hiç girmedi",
  active: "Etkin",
  inactive: "Pasif",
  firmInactive: "Firma pasif",
  mustChange: "Geçici şifre",
  none: "Portal hesabı yok.",
  username: "Kullanıcı adı",
  usernameHint: "Küçük harf, rakam, nokta, alt çizgi ya da tire",
  fullName: "Ad soyad",
  email: "E-posta",
  phone: "Telefon",
  create: "Hesabı aç",
  cancel: "Vazgeç",
  resetPassword: "Şifre sıfırla",
  unlock: "Kilidi aç",
  deactivate: "Pasife al",
  activate: "Etkinleştir",
  confirmReset: (name: string) =>
    `${name} için yeni geçici şifre üretilsin mi? Kişi bir sonraki girişte kendi şifresini belirler.`,
  confirmDeactivate: (name: string) =>
    `${name} pasife alınsın mı? Portala giremez; yeniden etkinleştirilebilir.`,
  done: "İşlem tamamlandı.",
};

type Action = { kind: "reset" | "deactivate"; account: PortalAccount };

function toIssued(result: IssuedAccountPassword): IssuedTemporaryPassword {
  return {
    user: { full_name: result.account.full_name, username: result.account.username },
    temporary_password: result.temporary_password,
  };
}

function NewAccountModal({
  opened,
  onClose,
  onCreated,
}: {
  opened: boolean;
  onClose: () => void;
  onCreated: (result: IssuedAccountPassword) => void;
}) {
  const [kind, setKind] = useState<PortalKind>("customer");
  const [firm, setFirm] = useState<string | null>(null);
  const [username, setUsername] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const firms = useQuery({
    queryKey: ["portal", "firms", kind],
    queryFn: () =>
      listRecords<Partner>(kind === "customer" ? "customers" : "suppliers", {
        is_active: true,
        page_size: 500,
      }),
    enabled: opened,
  });
  const mutation = useMutation({
    mutationFn: () =>
      createPortalAccount({
        username: username.trim(),
        full_name: fullName.trim(),
        email: email.trim(),
        phone: phone.trim(),
        customer: kind === "customer" ? Number(firm) : null,
        supplier: kind === "supplier" ? Number(firm) : null,
      }),
    onSuccess: (result) => {
      onCreated(result);
      setFirm(null);
      setUsername("");
      setFullName("");
      setEmail("");
      setPhone("");
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    mutation.mutate();
  }

  return (
    <Modal opened={opened} onClose={onClose} title={pa.newAccount}>
      <form onSubmit={submit}>
        <Stack>
          <SegmentedControl
            value={kind}
            onChange={(value) => {
              setKind(value as PortalKind);
              setFirm(null);
            }}
            data={[
              { value: "customer", label: pa.customer },
              { value: "supplier", label: pa.supplier },
            ]}
          />
          <Select
            label={kind === "customer" ? pa.customer : pa.supplier}
            data={(firms.data?.results ?? []).map((row) => ({
              value: String(row.id),
              label: `${row.code} — ${row.name}`,
            }))}
            value={firm}
            onChange={setFirm}
            searchable
            required
          />
          <TextInput
            label={pa.username}
            description={pa.usernameHint}
            value={username}
            onChange={(event) => setUsername(event.currentTarget.value)}
            required
          />
          <TextInput
            label={pa.fullName}
            value={fullName}
            onChange={(event) => setFullName(event.currentTarget.value)}
            required
          />
          <TextInput
            label={pa.email}
            type="email"
            value={email}
            onChange={(event) => setEmail(event.currentTarget.value)}
          />
          <TextInput
            label={pa.phone}
            value={phone}
            onChange={(event) => setPhone(event.currentTarget.value)}
          />
          {mutation.isError && (
            <Alert color="red" variant="light">
              {getErrorMessage(mutation.error)}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {pa.cancel}
            </Button>
            <Button type="submit" loading={mutation.isPending} disabled={!firm}>
              {pa.create}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

export function PortalAccountsPanel() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search.trim(), 300);
  const [kind, setKind] = useState<PortalKind | "">("");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [issued, setIssued] = useState<IssuedTemporaryPassword | null>(null);
  const [action, setAction] = useState<Action | null>(null);
  const filters = { page, search: debounced, kind };
  const query = useQuery({
    queryKey: [...KEY, filters],
    queryFn: () => listPortalAccounts(filters),
    placeholderData: keepPreviousData,
  });
  const reload = () => queryClient.invalidateQueries({ queryKey: KEY });
  const failed = (error: unknown) =>
    notifications.show({ color: "red", message: getErrorMessage(error) });

  const confirm = useMutation({
    mutationFn: async (a: Action) =>
      a.kind === "reset"
        ? toIssued(await resetPortalPassword(a.account.id))
        : (await setPortalAccountActive(a.account.id, false), null),
    onSuccess: (result) => {
      setAction(null);
      if (result) setIssued(result);
      else notifications.show({ color: "green", message: pa.done });
      void reload();
    },
    onError: failed,
  });
  const quick = useMutation({
    mutationFn: (a: { id: number; op: "unlock" | "activate" }) =>
      a.op === "unlock" ? unlockPortalAccount(a.id) : setPortalAccountActive(a.id, true),
    onSuccess: () => {
      notifications.show({ color: "green", message: pa.done });
      void reload();
    },
    onError: failed,
  });

  const rows = query.data?.results ?? [];
  const pages = Math.max(1, Math.ceil((query.data?.count ?? 0) / PAGE_SIZE));
  const name = (account: PortalAccount) => account.full_name || account.username;

  return (
    <Stack>
      <Alert color="blue" variant="light" icon={<IconInfoCircle size={18} />}>
        <Text size="sm">{pa.note}</Text>
      </Alert>
      <Group justify="space-between" align="flex-end">
        <Group>
          <TextInput
            placeholder={pa.search}
            aria-label={pa.search}
            leftSection={<IconSearch size={16} />}
            value={search}
            onChange={(event) => {
              setSearch(event.currentTarget.value);
              setPage(1);
            }}
            w={300}
          />
          <SegmentedControl
            value={kind}
            onChange={(value) => {
              setKind(value as PortalKind | "");
              setPage(1);
            }}
            data={[
              { value: "", label: pa.all },
              { value: "customer", label: pa.customer },
              { value: "supplier", label: pa.supplier },
            ]}
          />
        </Group>
        <Button leftSection={<IconUserPlus size={18} />} onClick={() => setCreating(true)}>
          {pa.newAccount}
        </Button>
      </Group>
      {query.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(query.error)}
        </Alert>
      )}
      {query.isLoading ? (
        <Loader />
      ) : rows.length === 0 ? (
        <Text c="dimmed">{pa.none}</Text>
      ) : (
        <Table.ScrollContainer minWidth={820}>
          <Table striped data-testid="portal-accounts">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{pa.account}</Table.Th>
                <Table.Th>{pa.kind}</Table.Th>
                <Table.Th>{pa.firm}</Table.Th>
                <Table.Th>{pa.state}</Table.Th>
                <Table.Th>{pa.lastLogin}</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((account) => (
                <Table.Tr key={account.id}>
                  <Table.Td>
                    <Text size="sm" fw={500}>
                      {name(account)}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {account.username}
                      {account.email ? ` · ${account.email}` : ""}
                    </Text>
                  </Table.Td>
                  <Table.Td>{account.kind === "customer" ? pa.customer : pa.supplier}</Table.Td>
                  <Table.Td>
                    {account.firm_code} — {account.firm_name}
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4}>
                      <Badge color={account.is_active ? "green" : "gray"} variant="light">
                        {account.is_active ? pa.active : pa.inactive}
                      </Badge>
                      {!account.firm_is_active && (
                        <Badge color="red" variant="light">
                          {pa.firmInactive}
                        </Badge>
                      )}
                      {account.password_change_required && (
                        <Badge color="yellow" variant="light">
                          {pa.mustChange}
                        </Badge>
                      )}
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    {account.last_login ? formatDateTime(account.last_login) : pa.never}
                  </Table.Td>
                  <Table.Td ta="right">
                    <Menu position="bottom-end">
                      <Menu.Target>
                        <Button variant="subtle" size="compact-sm" aria-label={pa.account}>
                          <IconDots size={16} />
                        </Button>
                      </Menu.Target>
                      <Menu.Dropdown>
                        {account.is_active && (
                          <Menu.Item onClick={() => setAction({ kind: "reset", account })}>
                            {pa.resetPassword}
                          </Menu.Item>
                        )}
                        <Menu.Item onClick={() => quick.mutate({ id: account.id, op: "unlock" })}>
                          {pa.unlock}
                        </Menu.Item>
                        {account.is_active ? (
                          <Menu.Item
                            color="red"
                            onClick={() => setAction({ kind: "deactivate", account })}
                          >
                            {pa.deactivate}
                          </Menu.Item>
                        ) : (
                          <Menu.Item
                            onClick={() => quick.mutate({ id: account.id, op: "activate" })}
                          >
                            {pa.activate}
                          </Menu.Item>
                        )}
                      </Menu.Dropdown>
                    </Menu>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
      <NewAccountModal
        opened={creating}
        onClose={() => setCreating(false)}
        onCreated={(result) => {
          setCreating(false);
          setIssued(toIssued(result));
          void reload();
        }}
      />
      <ConfirmModal
        opened={action !== null}
        message={
          action
            ? action.kind === "reset"
              ? pa.confirmReset(name(action.account))
              : pa.confirmDeactivate(name(action.account))
            : ""
        }
        confirmLabel={action?.kind === "reset" ? pa.resetPassword : pa.deactivate}
        danger={action?.kind === "deactivate"}
        loading={confirm.isPending}
        onConfirm={() => action && confirm.mutate(action)}
        onClose={() => setAction(null)}
      />
      <TemporaryPasswordModal issued={issued} onClose={() => setIssued(null)} />
    </Stack>
  );
}
