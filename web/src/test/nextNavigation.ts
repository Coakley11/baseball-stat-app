/**
 * Test stand-in for next/navigation. Use with:
 *   vi.mock("next/navigation", async () => (await import("@/test/nextNavigation")).nextNavigationMock);
 * Set `nav.pathname` / `nav.search` before rendering; `nav.push` records navigations.
 */
import { vi } from "vitest";

export const nav = {
  pathname: "/",
  search: "",
  push: vi.fn<(href: string, options?: unknown) => void>(),
  reset(pathname = "/", search = "") {
    nav.pathname = pathname;
    nav.search = search;
    nav.push.mockReset();
  },
};

export const nextNavigationMock = {
  usePathname: () => nav.pathname,
  useSearchParams: () => new URLSearchParams(nav.search),
  useRouter: () => ({ push: nav.push, replace: nav.push, prefetch: vi.fn(), back: vi.fn(), forward: vi.fn(), refresh: vi.fn() }),
};
