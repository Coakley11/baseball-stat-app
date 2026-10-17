"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, type ReactNode } from "react";

import { activeNavItem } from "@/lib/navigation";

import { NavTree } from "./NavTree";
import styles from "./shell.module.css";

interface AppShellProps {
  children: ReactNode;
  /**
   * Bottom of the desktop sidebar. Reserved for league context and account controls (not
   * built in WEB-M1); today it carries the data-source notice.
   */
  sidebarFooter?: ReactNode;
  /** Phone header, left of the Menu button. Reserved for Ask AMI / account; today the data-source badge. */
  headerExtras?: ReactNode;
}

/**
 * Desktop (≥ 960px): fixed left sidebar with grouped navigation.
 * Phones/tablets: compact sticky header + a full-height grouped menu (native modal <dialog>:
 * focus stays inside, Esc closes, focus returns to the Menu button).
 */
export function AppShell({ children, sidebarFooter, headerExtras }: AppShellProps) {
  const pathname = usePathname();
  const active = activeNavItem(pathname);
  const menuRef = useRef<HTMLDialogElement>(null);

  const openMenu = () => menuRef.current?.showModal();
  const closeMenu = () => menuRef.current?.close();

  // Close the phone menu when the route changes (e.g. browser Back while it is open).
  useEffect(() => {
    menuRef.current?.close();
  }, [pathname]);

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <div className={styles.shell}>
        <aside className={styles.sidebar} aria-label="Sidebar">
          <Brand />
          <nav aria-label="Main" className={styles.sidebarNav}>
            <NavTree activeId={active?.id} idPrefix="side" />
          </nav>
          {sidebarFooter && <div className={styles.sidebarFooter}>{sidebarFooter}</div>}
        </aside>

        <header className={styles.mobileHeader}>
          <Brand compact />
          <div className={styles.headerActions}>
            {headerExtras}
            <button
              type="button"
              className={styles.menuButton}
              onClick={openMenu}
              aria-haspopup="dialog"
              aria-controls="site-menu"
            >
              <MenuIcon />
              Menu
            </button>
          </div>
        </header>

        <dialog
          id="site-menu"
          ref={menuRef}
          className={styles.menu}
          aria-labelledby="site-menu-title"
          onClick={(event) => {
            // A click on the backdrop lands on the <dialog> itself.
            if (event.target === event.currentTarget) closeMenu();
          }}
        >
          <div className={styles.menuInner}>
            <div className={styles.menuHeader}>
              <h2 id="site-menu-title" className={styles.menuTitle}>
                Menu
              </h2>
              <button type="button" className={styles.menuClose} onClick={closeMenu}>
                Close
              </button>
            </div>
            {active && (
              <p className={styles.menuCurrent}>
                You are on <strong>{active.label}</strong>
              </p>
            )}
            <nav aria-label="Main">
              <NavTree activeId={active?.id} idPrefix="menu" onNavigate={closeMenu} />
            </nav>
          </div>
        </dialog>

        <main id="main" className={styles.main} tabIndex={-1}>
          {children}
        </main>
      </div>
    </>
  );
}

function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <Link href="/" className={compact ? `${styles.brand} ${styles.brandCompact}` : styles.brand}>
      <Image src="/brand/dcbe_logo_128.png" alt="" width={compact ? 30 : 36} height={compact ? 30 : 36} priority />
      <span className={styles.brandName}>Baseball Explorer</span>
    </Link>
  );
}

function MenuIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" focusable="false">
      <path d="M2 4.5h14M2 9h14M2 13.5h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}
