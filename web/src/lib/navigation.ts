/**
 * The one navigation map, shared by the desktop sidebar, the phone menu and Home.
 *
 * Sections and order follow the accepted U1 grouping (nav_groups.NAV_SECTIONS). `streamlitKey`
 * is the page key in the current app (`?active_page=`), kept so old deep links can be
 * redirected once each page moves. Only `ready` pages have routes in WEB-M1; the rest are shown
 * as "Later" and are not links.
 */

export type NavStatus = "ready" | "later";

export interface NavItem {
  id: string;
  label: string;
  /** Route once the page exists in the web app (reserved for `later` pages). */
  href: string;
  status: NavStatus;
  streamlitKey: string;
}

export interface NavSection {
  id: string;
  label: string;
  items: NavItem[];
}

const ready = (id: string, label: string, href: string, streamlitKey: string): NavItem =>
  ({ id, label, href, status: "ready", streamlitKey });
const later = (id: string, label: string, href: string, streamlitKey: string): NavItem =>
  ({ id, label, href, status: "later", streamlitKey });

export const NAV_SECTIONS: NavSection[] = [
  { id: "home", label: "Home", items: [ready("home", "Home", "/", "Home")] },
  {
    id: "players",
    label: "Players",
    items: [
      ready("historical", "Historical Explorer", "/players/historical", "Historical Explorer"),
      later("career", "Career Totals", "/players/career", "Career Totals"),
      later("compare", "Compare Players", "/players/compare", "Comparison Tool"),
      ready("leaderboards", "Leaderboards", "/players/leaderboards", "Leaderboards"),
    ],
  },
  {
    id: "insights",
    label: "Insights",
    items: [
      later("trend-value", "Trend Value", "/insights/trend-value", "Trend Value"),
      later("valuation", "Valuation", "/insights/valuation", "Valuation"),
      later("ml", "ML Predictions", "/insights/ml-predictions", "ML Predictions"),
      later("sleepers", "Sleepers & Busts", "/insights/sleepers-busts", "Fantasy Sleepers & Busts"),
    ],
  },
  {
    id: "draft",
    label: "Draft",
    items: [
      later("draft-room", "Draft Room Simulator", "/draft/room", "Draft Room Simulator"),
      later("draft-assistant", "Draft Assistant Simulator", "/draft/assistant", "Draft Assistant Simulator"),
      later("draft-lab", "Draft Lab", "/draft/lab", "Draft Lab / Simulation"),
      later("live-draft", "Live Draft", "/draft/live", "Live Draft Room"),
    ],
  },
  {
    id: "league",
    label: "My League",
    items: [
      later("library", "Saved Draft Library", "/league/drafts", "Saved Draft Library"),
      later("standings", "League Standings", "/league/standings", "Fantasy Standings Tracker"),
      later("lineup", "Lineup & Trades", "/league/lineup", "Fantasy Lineup Assistant"),
      later("waivers", "Waiver Wire", "/league/waivers", "Waiver Wire / Add-Drop Center"),
    ],
  },
  {
    id: "account",
    label: "Account",
    items: [later("pricing", "Pricing & Upgrade", "/account/pricing", "Pricing & Upgrade")],
  },
];

export const NAV_ITEMS: NavItem[] = NAV_SECTIONS.flatMap((s) => s.items);

/** The nav item a pathname belongs to (exact match, or the closest ready parent route). */
export function activeNavItem(pathname: string): NavItem | undefined {
  const path = pathname.replace(/\/+$/, "") || "/";
  const readyItems = NAV_ITEMS.filter((i) => i.status === "ready");
  return (
    readyItems.find((i) => i.href === path) ??
    readyItems.filter((i) => i.href !== "/" && path.startsWith(`${i.href}/`)).sort((a, b) => b.href.length - a.href.length)[0]
  );
}
