import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => cleanup());

// Mantine'in jsdom'da ihtiyaç duyduğu tarayıcı API'leri.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});
window.HTMLElement.prototype.scrollIntoView = () => {};
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
window.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;

// Testlerde gerçek WebSocket bağlantısı açılmaz (bkz. fakeWebSocket.ts).
import { FakeWebSocket } from "./fakeWebSocket";
window.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
afterEach(() => {
  FakeWebSocket.instances = [];
});
