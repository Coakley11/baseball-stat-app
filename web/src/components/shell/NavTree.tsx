import Link from "next/link";

import { NAV_SECTIONS, type NavItem } from "@/lib/navigation";

import styles from "./shell.module.css";

interface NavTreeProps {
  activeId: string | undefined;
  /** Distinguishes the sidebar and phone-menu copies for heading ids. */
  idPrefix: string;
  onNavigate?: () => void;
}

/**
 * Grouped navigation (U1 sections). Ready pages are links; the current one carries
 * aria-current plus a bar and weight change (never colour alone). Pages that haven't moved to
 * the web app yet are listed as plain text marked "Later", so the map is complete without
 * pretending they work.
 */
export function NavTree({ activeId, idPrefix, onNavigate }: NavTreeProps) {
  return (
    <div className={styles.navTree}>
      {NAV_SECTIONS.map((section) => {
        const headingId = `${idPrefix}-nav-${section.id}`;
        const showHeading = section.id !== "home";
        return (
          <div key={section.id} className={styles.navSection}>
            {showHeading && (
              <h2 id={headingId} className={styles.navHeading}>
                {section.label}
              </h2>
            )}
            <ul className={styles.navList} aria-labelledby={showHeading ? headingId : undefined}>
              {section.items.map((item) => (
                <NavEntry key={item.id} item={item} active={item.id === activeId} onNavigate={onNavigate} />
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

function NavEntry({ item, active, onNavigate }: { item: NavItem; active: boolean; onNavigate?: () => void }) {
  if (item.status === "later") {
    return (
      <li className={styles.navLater}>
        <span>{item.label}</span>
        <span className={styles.laterTag}>
          <span className="sr-only">, </span>Later
        </span>
      </li>
    );
  }
  return (
    <li>
      <Link
        href={item.href}
        className={styles.navLink}
        aria-current={active ? "page" : undefined}
        data-active={active || undefined}
        onClick={onNavigate}
      >
        {item.label}
      </Link>
    </li>
  );
}
