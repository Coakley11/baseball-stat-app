/**
 * Home: "What can I do in Baseball Explorer?" Four task entry points (home_page.TASKS), a few
 * ready-made questions, and the reserved Ask AMI spot. Not a dashboard: no statistics here.
 * Unfinished tasks say so and offer no button.
 */
import Link from "next/link";
import type { ReactNode } from "react";

import { Badge, ButtonLink, Card, PageHeader, SectionHeader } from "@/components/ui/primitives";

import styles from "./home.module.css";

interface Task {
  id: string;
  title: string;
  body: string;
  icon: ReactNode;
  /** Present only when the destination exists in the web app. */
  primary?: { label: string; href: string };
  secondary?: { label: string; href: string };
}

const TASKS: Task[] = [
  {
    id: "explore",
    title: "Explore Players",
    body: "Find seasons, stats and player histories, back to 1871.",
    icon: <SearchIcon />,
    primary: { label: "Find the best seasons", href: "/players/historical" },
    secondary: { label: "Leaderboards", href: "/players/leaderboards" },
  },
  {
    id: "compare",
    title: "Compare Players",
    body: "Put players side by side across the stats and years you choose.",
    icon: <CompareIcon />,
  },
  {
    id: "draft",
    title: "Prepare for a Draft",
    body: "Mock drafts, the draft lab, strategy and live drafts with your league.",
    icon: <DraftIcon />,
  },
  {
    id: "league",
    title: "Manage My League",
    body: "Standings, lineups, waivers and trades.",
    icon: <TrophyIcon />,
  },
];

const QUESTIONS: { text: string; href: string }[] = [
  { text: "Most home runs in a season since 2010", href: "/players/historical" },
  { text: "Best OPS seasons since 2010", href: "/players/historical?metric=OPS" },
  { text: "Who leads 2020–2025 in home runs?", href: "/players/leaderboards?metric=HR" },
  { text: "Highest OPS since 2020, qualified hitters", href: "/players/leaderboards?metric=OPS" },
];

export function HomeView() {
  return (
    <div className={styles.home}>
      <PageHeader
        title="What would you like to do?"
        purpose="Look up players, spot who's rising, prepare for your draft and run your fantasy league."
      />

      <section aria-labelledby="home-tasks">
        <h2 id="home-tasks" className="sr-only">
          Start here
        </h2>
        <ul className={styles.tasks}>
          {TASKS.map((task) => (
            <li key={task.id}>
              <TaskCard task={task} />
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="home-questions">
        <SectionHeader id="home-questions" title="Try a question" />
        <ul className={styles.questions}>
          {QUESTIONS.map((q) => (
            <li key={q.href}>
              <Link href={q.href} className={styles.question}>
                <span>{q.text}</span>
                <ArrowIcon />
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="home-ami">
        <SectionHeader id="home-ami" title="Ask a question in plain English" />
        <Card muted className={styles.ami}>
          <div className={styles.amiText}>
            <p className={styles.amiTitle}>
              Ask AMI <Badge>Coming later</Badge>
            </p>
            <p className={styles.amiBody}>
              AMI, the Baseball Explorer assistant, will be available here. For now, ask it in the current app.
            </p>
          </div>
        </Card>
      </section>
    </div>
  );
}

function TaskCard({ task }: { task: Task }) {
  const ready = Boolean(task.primary);
  const titleId = `task-${task.id}`;
  return (
    <Card className={ready ? styles.task : `${styles.task} ${styles.taskLater}`} aria-labelledby={titleId} role="group">
      <div className={styles.taskHead}>
        <span className={styles.taskIcon} aria-hidden="true">
          {task.icon}
        </span>
        <h3 id={titleId} className={styles.taskTitle}>
          {task.title}
        </h3>
        {!ready && <Badge>Coming later</Badge>}
      </div>
      <p className={styles.taskBody}>{task.body}</p>
      {ready ? (
        <div className={styles.taskActions}>
          <ButtonLink variant="primary" href={task.primary!.href}>
            {task.primary!.label}
          </ButtonLink>
          {task.secondary && (
            <ButtonLink variant="ghost" href={task.secondary.href}>
              {task.secondary.label}
            </ButtonLink>
          )}
        </div>
      ) : (
        <p className={styles.taskLaterNote}>Still in the current Baseball Explorer app for now.</p>
      )}
    </Card>
  );
}

function Icon({ children }: { children: ReactNode }) {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" focusable="false">
      {children}
    </svg>
  );
}

function SearchIcon() {
  return (
    <Icon>
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4.5 4.5" />
    </Icon>
  );
}

function CompareIcon() {
  return (
    <Icon>
      <path d="M6 20V10M12 20V4M18 20v-7" />
    </Icon>
  );
}

function DraftIcon() {
  return (
    <Icon>
      <rect x="5" y="4" width="14" height="17" rx="2" />
      <path d="M9 4.5V3h6v1.5M9 10h6M9 14h6M9 18h3" />
    </Icon>
  );
}

function TrophyIcon() {
  return (
    <Icon>
      <path d="M8 4h8v5a4 4 0 0 1-8 0V4ZM8 6H5a3 3 0 0 0 3 4M16 6h3a3 3 0 0 1-3 4M12 13v4M9 21h6M10 17h4v4h-4z" />
    </Icon>
  );
}

function ArrowIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}
