import { screen } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { AuthContext, type AuthContextValue } from "../auth/AuthContext";
import { makePersonas } from "../auth/parity/personas";
import { closed, decide, holdRequests } from "../auth/parity/probes";
import { routes } from "../routes";
import { userWith, withoutAccess } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import { RecordLink } from "./RecordLink";
import { canOpenRecord, RECORD_PAGES, RECORD_ROUTES } from "./recordLinks";

vi.mock("../layout/AppLayout", async () => {
  const { Outlet } = await import("react-router-dom");
  return { AppLayout: Outlet };
});

let release: () => void = () => undefined;
beforeAll(() => {
  release = holdRequests();
});
afterAll(() => release());

describe("kayıt bağlantılarının koruma tablosu", () => {
  it("her kayıt türünün detay sayfası için koruması var", () => {
    expect(Object.keys(RECORD_PAGES).sort()).toEqual(Object.keys(RECORD_ROUTES).sort());
  });

  it("canOpenRecord, hedef rotanın gerçek kararıyla aynı (her persona, her kayıt türü)", async () => {
    const mismatches: string[] = [];
    for (const [persona, user] of makePersonas()) {
      if (!user) continue;
      for (const model of Object.keys(RECORD_ROUTES)) {
        const decision = await decide(routes, RECORD_ROUTES[model](1), user);
        if (canOpenRecord(user, model, 1) === closed(decision)) {
          mismatches.push(`${persona} ${model}: ${decision}`);
        }
      }
    }
    expect(mismatches).toEqual([]);
  }, 60_000);
});

function renderAs(ui: React.ReactElement, user: ReturnType<typeof userWith>) {
  const value: AuthContextValue = {
    user,
    isLoading: false,
    sessionExpired: false,
    login: async () => undefined,
    logout: async () => undefined,
    refresh: async () => undefined,
  };
  return renderWithProviders(<AuthContext.Provider value={value}>{ui}</AuthContext.Provider>);
}

describe("RecordLink", () => {
  it("açılabilen kayıtta bağlantı, açılamayanda düz metin (plan §8 madde 2)", () => {
    renderAs(
      <>
        <RecordLink model="quality.sample" id={4}>
          NUM-1
        </RecordLink>
        <RecordLink model="inventory.lot" id={9}>
          LOT-1
        </RecordLink>
      </>,
      userWith("planlama"),
    );
    expect(screen.queryByRole("link", { name: "NUM-1" })).not.toBeInTheDocument();
    expect(screen.getByText("NUM-1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "LOT-1" })).toHaveAttribute("href", "/depo/lotlar/9");
  });

  it("kişiden kaldırılan okuma bağlantıyı düz metne çevirir", () => {
    const depo = withoutAccess(userWith("depo"), { "inventory.receipts": "rv" });
    // Açık okumalı bölümde okuma modülün "Kayıtları okur"una bağlı: o da kaldırılınca kapanır.
    const blind = withoutAccess(depo, { "inventory.open_records": "r" });
    renderAs(
      <RecordLink model="inventory.goodsreceipt" id={3}>
        MK-1
      </RecordLink>,
      blind,
    );
    expect(screen.queryByRole("link", { name: "MK-1" })).not.toBeInTheDocument();
  });
});
