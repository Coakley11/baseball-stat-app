"use client";

import { useEffect, useId, useState } from "react";

import { Button } from "@/components/ui/primitives";
import { useBaseballQuery, type PlayerSummary } from "@/lib/api";
import { formatYearRange } from "@/lib/format";

import shared from "../shared/questions.module.css";
import styles from "./historical.module.css";

function playerLine(p: PlayerSummary): string {
  const years = p.firstSeason !== null && p.lastSeason !== null ? formatYearRange({ start: p.firstSeason, end: p.lastSeason }) : null;
  return [p.primaryPosition, years].filter(Boolean).join(" · ");
}

/**
 * Search box + result buttons (simpler and more robust than a custom combobox). The search
 * itself is the API's; this only debounces typing and lists what comes back.
 */
export function PlayerPicker({
  selectedId,
  onSelect,
  onClear,
}: {
  selectedId: string | null;
  onSelect: (id: string) => void;
  onClear: () => void;
}) {
  const id = useId();
  const [text, setText] = useState("");
  const [term, setTerm] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => setTerm(text.trim()), 250);
    return () => clearTimeout(timer);
  }, [text]);

  const search = useBaseballQuery(selectedId === null && term.length >= 2 ? `search:${term}` : null, (client, options) =>
    client.searchPlayers(term, { ...options, limit: 8 }),
  );
  const selected = useBaseballQuery(selectedId ? `player:${selectedId}` : null, (client, options) =>
    client.getPlayer(selectedId!, options),
  );

  if (selectedId) {
    const player = selected.status === "success" ? selected.data : null;
    return (
      <div className={`${shared.field} ${styles.playerField}`}>
        <span className={shared.label}>Player</span>
        <div className={styles.selectedPlayer}>
          <span className={styles.selectedName}>
            {player ? player.name : selected.status === "loading" ? "Loading player…" : "Unknown player"}
            {player && <span className={styles.selectedSub}>{playerLine(player)}</span>}
          </span>
          <Button variant="ghost" onClick={onClear}>
            Change player
          </Button>
        </div>
      </div>
    );
  }

  let status = "Type at least 2 letters of a name.";
  if (term.length >= 2) {
    if (search.status === "loading") status = "Searching…";
    else if (search.status === "error") status = "Player search isn't available right now.";
    else if (search.status === "success") {
      status = search.data.length === 0 ? `No players match “${term}”.` : `${search.data.length} matching players.`;
    }
  }

  return (
    <div className={`${shared.field} ${styles.playerField}`}>
      <label className={shared.label} htmlFor={`${id}-search`}>
        Find a player
      </label>
      <input
        id={`${id}-search`}
        type="search"
        className={`${shared.input} ${styles.playerSearch}`}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="e.g. Aaron Judge"
        autoComplete="off"
        aria-describedby={`${id}-status`}
      />
      <p id={`${id}-status`} className={shared.hint} aria-live="polite">
        {status}
      </p>
      {search.status === "success" && search.data.length > 0 && (
        <ul className={styles.playerResults} aria-label="Matching players">
          {search.data.map((p) => (
            <li key={p.id}>
              <button type="button" className={styles.playerOption} onClick={() => onSelect(p.id)}>
                <span className={styles.selectedName}>{p.name}</span>
                <span className={styles.selectedSub}>{playerLine(p)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
