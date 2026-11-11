import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render } from "@testing-library/react";
import type { AxiosAdapter, AxiosResponse, InternalAxiosRequestConfig } from "axios";
import { cloneElement, isValidElement, type ReactElement, type ReactNode } from "react";
import { createMemoryRouter, type RouteObject } from "react-router-dom";
import { api } from "../../api/client";
import type { CurrentUser } from "../../api/types";
import { AppRouterProvider } from "../../AppRouterProvider";
import { tr } from "../../i18n/tr";
import { theme } from "../../theme";
import { AuthContext, type AuthContextValue } from "../AuthContext";

/**
 * Eşlik testinin sondaları: sayfaları gerçek rota ağacıyla, verilen persona oturum açmış gibi
 * çizer ve kullanıcının gördüğünü okur (kapalı mı, nereye yönlendi, hangi sekmeler var).
 *
 * API istekleri hiç yanıtlanmaz: her ekran ilk yükleme hâlinde kalır, veri biçimine bağlı bir
 * karar sondaya karışmaz. İstekler `requests` listesine yazılır (arama kaynakları).
 */

/** Sondanın kararı: `open`, `forbidden`, `login`, `not-found` ya da `redirect <adres>`. */
export type Decision = string;
export const OPEN = "open";
export const FORBIDDEN = "forbidden";
export const LOGIN = "login";
export const NOT_FOUND = "not-found";

/** Sayfa açıldı ama başka bir adrese yönlendi (ör. görünmeyen sekmeden modülün ilk sekmesine). */
export function redirect(pathname: string): Decision {
  return `redirect ${pathname}`;
}

/** Sayfa hiç açılamadı mı (kapalı, girişe yönlendi ya da yok)? */
export function closed(decision: Decision): boolean {
  return decision === FORBIDDEN || decision === LOGIN || decision === NOT_FOUND;
}

export const requests: InternalAxiosRequestConfig[] = [];

/** API'yi yanıtsız bekletir; geri almak için dönen işlevi çağırın. */
export function holdRequests(): () => void {
  const original = api.defaults.adapter;
  const hold: AxiosAdapter = (config) => {
    requests.push(config);
    return new Promise<AxiosResponse>(() => undefined);
  };
  api.defaults.adapter = hold;
  return () => {
    api.defaults.adapter = original;
  };
}

/** Oturum bağlamı: `me` yanıtı yüklenmiş, persona giriş yapmış. */
function authValue(user: CurrentUser | null): AuthContextValue {
  return {
    user,
    isLoading: false,
    sessionExpired: false,
    login: async () => undefined,
    logout: async () => undefined,
    refresh: async () => undefined,
  };
}

type Router = ReturnType<typeof createMemoryRouter>;

export interface Rendered {
  router: Router;
  container: HTMLElement;
  unmount: () => void;
}

/** Yönlendirmeler (Navigate) bitene kadar bekler. */
export async function settle(router: Router): Promise<void> {
  let previous = "";
  for (let round = 0; round < 25; round += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    const { location, navigation } = router.state;
    const current = `${location.key} ${navigation.state}`;
    if (current === previous && navigation.state === "idle") return;
    previous = current;
  }
  throw new Error(`Yönlendirme durulmadı: ${router.state.location.pathname}`);
}

/** Rota ağacını verilen adreste, persona oturum açmış olarak çizer. */
export async function renderAt(
  tree: RouteObject[],
  path: string,
  user: CurrentUser | null,
): Promise<Rendered> {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(tree, { initialEntries: [path] });
  const view = render(
    <MantineProvider theme={theme}>
      <QueryClientProvider client={queryClient}>
        <AuthContext.Provider value={authValue(user)}>
          <AppRouterProvider router={router} />
        </AuthContext.Provider>
      </QueryClientProvider>
    </MantineProvider>,
  );
  await settle(router);
  return {
    router,
    container: view.container,
    unmount: () => {
      view.unmount();
      queryClient.clear();
      router.dispose();
    },
  };
}

function headings(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll("h1, h2"), (node) => node.textContent ?? "");
}

/** Çizilen sayfanın sonucu: kapalı mı, girişe mi gitti, başka bir adrese mi yönlendi? */
export function outcome(rendered: Rendered, requested: string): Decision {
  const { pathname } = rendered.router.state.location;
  const titles = headings(rendered.container);
  if (titles.includes(tr.errors.crashTitle)) throw new Error(`${requested}: sayfa hata verdi.`);
  if (pathname === "/login") return LOGIN;
  if (titles.includes(tr.errors.forbiddenTitle)) return FORBIDDEN;
  if (titles.includes(tr.errors.notFoundTitle)) return NOT_FOUND;
  const target = new URL(requested, "http://eslik.test").pathname;
  return pathname === target ? OPEN : redirect(pathname);
}

/** Adresi çizer, sonucu okur ve sayfayı kaldırır. */
export async function decide(
  tree: RouteObject[],
  path: string,
  user: CurrentUser | null,
): Promise<Decision> {
  const rendered = await renderAt(tree, path, user);
  try {
    return outcome(rendered, path);
  } finally {
    rendered.unmount();
  }
}

// --- sekmeler -----------------------------------------------------------------------------------

/** Mantine sekmesinin değeri: kimliği `<tabs>-tab-<değer>` biçimindedir. */
function tabValue(tab: Element): string {
  const marker = tab.id.indexOf("-tab-");
  if (marker < 0) throw new Error(`Sekmenin kimliği okunamadı: ${tab.id}`);
  return tab.id.slice(marker + "-tab-".length);
}

function tabList(container: HTMLElement): Element[] {
  const list = container.querySelector('[role="tablist"]');
  return list ? Array.from(list.querySelectorAll('[role="tab"]')) : [];
}

/** Sayfanın ilk sekme listesi: görünen sekmelerin değerleri ve seçili olan. */
export function readTabs(container: HTMLElement): { values: string[]; selected: string | null } {
  const tabs = tabList(container);
  const selected = tabs.find((tab) => tab.getAttribute("aria-selected") === "true");
  return { values: tabs.map(tabValue), selected: selected ? tabValue(selected) : null };
}

const tabPaths = new Map<string, string>();

/**
 * Sekmenin adresi: sekmeye basınca gidilen adres. Sayfa başına bir kez tıklanarak bulunur;
 * sekme değeri adresin son parçası olmayabilir (ör. Maliyet'te "lots" → `/maliyet/lotlar`).
 */
export async function tabPath(rendered: Rendered, page: string, value: string): Promise<string> {
  const key = `${page} ${value}`;
  const known = tabPaths.get(key);
  if (known) return known;
  const tab = tabList(rendered.container).find((item) => tabValue(item) === value);
  if (!tab) throw new Error(`${page}: "${value}" sekmesi bulunamadı.`);
  fireEvent.click(tab);
  await settle(rendered.router);
  const path = rendered.router.state.location.pathname;
  tabPaths.set(key, path);
  return path;
}

// --- rota korumaları ----------------------------------------------------------------------------

export interface RouteCase {
  /** Rotanın tam deseni, ör. `/uretim/emirler/:orderId`; dizin rotası `/ (index)`. */
  name: string;
  /** Kökten bu rotaya kadar eşleşen rotalar (düzen rotaları dahil). */
  chain: RouteObject[];
}

function joinPath(parent: string, path: string | undefined): string {
  if (!path) return parent;
  if (path.startsWith("/")) return path;
  return `${parent.replace(/\/$/, "")}/${path}`;
}

/** Rota ağacındaki her yaprak rota, tam deseniyle. */
export function routeCases(
  tree: RouteObject[],
  parent = "",
  chain: RouteObject[] = [],
): RouteCase[] {
  return tree.flatMap((route) => {
    if (route.Component || route.lazy || route.loader) {
      // Koruma bunlarda da olabilir; sonda yalnız `element`'i değerlendirir.
      throw new Error(`Sonda bu rota biçimini bilmiyor: ${route.path ?? "(yolsuz)"}`);
    }
    const path = route.index ? parent : joinPath(parent, route.path);
    const next = [...chain, route];
    if (route.children) return routeCases(route.children, path, next);
    return [{ name: route.index ? `${path || "/"} (index)` : path || "/", chain: next }];
  });
}

const PROBE_ATTRIBUTE = "data-parity-probe";
/** Korunan sayfanın yerine çizilen işaret: çizildiyse koruma içeri aldı. */
const PROBE = <span data-parity-probe="" />;

/** Koruma sondayı çizdiyse açık; değilse girişe mi, "Yetkiniz yok"a mı, başka yere mi gitti? */
function probeOutcome(rendered: Rendered): Decision {
  if (rendered.container.querySelector(`[${PROBE_ATTRIBUTE}]`)) return OPEN;
  const { pathname } = rendered.router.state.location;
  if (pathname === "/login") return LOGIN;
  if (headings(rendered.container).includes(tr.errors.forbiddenTitle)) return FORBIDDEN;
  return redirect(pathname);
}

const PROBE_PATH = "/eslik-sondasi";
const decisions = new Map<string, Decision>();
const identities = new Map<unknown, number>();

/** Bileşenin ya da rota nesnesinin önbellek için sıra numarası. */
function identity(value: unknown): number {
  let key = identities.get(value);
  if (key === undefined) {
    key = identities.size + 1;
    identities.set(value, key);
  }
  return key;
}

/**
 * Korumanın önbellek anahtarı: bileşen ve `children` dışındaki özellikleri. Aynı rollerle
 * kurulmuş iki koruma aynı kararı verir; işlev ya da öğe taşıyan özelliklerde önbellek yok.
 */
function guardKey(element: ReactElement, persona: string): string | null {
  const props = Object.entries(element.props as Record<string, unknown>).filter(
    ([name]) => name !== "children",
  );
  const plain = props.every(([, value]) => typeof value !== "function" && !isValidElement(value));
  if (!plain) return null;
  return `${identity(element.type)} ${JSON.stringify(props)} ${persona}`;
}

async function cached(key: string | null, compute: () => Promise<Decision>): Promise<Decision> {
  if (key !== null) {
    const known = decisions.get(key);
    if (known) return known;
  }
  const decision = await compute();
  if (key !== null) decisions.set(key, decision);
  return decision;
}

/** Düzen rotası (alt rotayı `Outlet` ile çizen koruma, ör. `RequireAuth`) sondayı çiziyor mu? */
function layoutDecision(route: RouteObject, persona: string, user: CurrentUser | null) {
  return cached(`layout ${identity(route)} ${persona}`, async () => {
    const tree: RouteObject[] = [
      { path: "/login", element: null },
      { path: "/", element: route.element, children: [{ path: "*", element: PROBE }] },
    ];
    const rendered = await renderAt(tree, PROBE_PATH, user);
    try {
      return probeOutcome(rendered);
    } finally {
      rendered.unmount();
    }
  });
}

/**
 * Yaprak rotanın öğesi: tek bir öğeyi saran her bileşen koruma sayılır (`RequireRole` gibi) ve
 * sayfanın yerine sondayla çizilir; açıksa içteki öğeye geçilir. Sarmayan öğe sayfadır.
 */
async function elementDecision(
  element: ReactNode,
  persona: string,
  user: CurrentUser | null,
): Promise<Decision> {
  if (!isValidElement(element)) return OPEN;
  const child = (element.props as { children?: ReactNode }).children;
  if (!isValidElement(child)) return OPEN;
  const decision = await cached(guardKey(element, persona), async () => {
    const guard = cloneElement(element as ReactElement<{ children?: ReactNode }>, undefined, PROBE);
    const tree: RouteObject[] = [
      { path: "/login", element: null },
      { path: "*", element: guard },
    ];
    const rendered = await renderAt(tree, PROBE_PATH, user);
    try {
      return probeOutcome(rendered);
    } finally {
      rendered.unmount();
    }
  });
  return decision === OPEN ? elementDecision(child, persona, user) : decision;
}

/** Rotanın korumaları personayı içeri alıyor mu? İlk kapalı korumanın kararı döner. */
export async function routeDecision(
  chain: RouteObject[],
  persona: string,
  user: CurrentUser | null,
): Promise<Decision> {
  for (const route of chain) {
    const decision = route.children
      ? await layoutDecision(route, persona, user)
      : await elementDecision(route.element, persona, user);
    if (decision !== OPEN) return decision;
  }
  return OPEN;
}
