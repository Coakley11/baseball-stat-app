/**
 * SAMPLE DATA for interface development only. Names are real players so layouts can be judged
 * with realistic text; every number in the fixtures is illustrative and may not match official
 * records. Long names, suffixes ("Jr."), accents and apostrophes are deliberate.
 */
import type { PlayerSummary } from "../../types";

function player(
  id: string,
  name: string,
  bats: string | null,
  primaryPosition: string | null,
  firstSeason: number | null,
  lastSeason: number | null,
): PlayerSummary {
  return { id, name, bats, primaryPosition, firstSeason, lastSeason };
}

export const PLAYERS: PlayerSummary[] = [
  player("judgeaa01", "Aaron Judge", "R", "RF", 2016, 2025),
  player("guerrvl02", "Vladimir Guerrero Jr.", "R", "1B", 2019, 2025),
  player("ohtansh01", "Shohei Ohtani", "L", "DH", 2018, 2025),
  player("raleica01", "Cal Raleigh", "B", "C", 2021, 2025),
  player("stantmi03", "Giancarlo Stanton", "R", "RF", 2010, 2025),
  player("schwaky01", "Kyle Schwarber", "L", "DH", 2015, 2025),
  player("bautijo02", "José Bautista", "R", "RF", 2004, 2018),
  player("olsonma02", "Matt Olson", "L", "1B", 2016, 2025),
  player("alonspe01", "Pete Alonso", "R", "1B", 2019, 2025),
  player("davisch02", "Chris Davis", "L", "1B", 2008, 2020),
  player("perezsa02", "Salvador Perez", "R", "C", 2011, 2025),
  player("harpebr03", "Bryce Harper", "L", "1B", 2012, 2025),
  player("yelicch01", "Christian Yelich", "L", "LF", 2013, 2025),
  player("troutmi01", "Mike Trout", "R", "CF", 2011, 2025),
  player("cabremi01", "Miguel Cabrera", "R", "1B", 2003, 2023),
  player("vottojo01", "Joey Votto", "L", "1B", 2007, 2023),
  player("sotoju01", "Juan Soto", "L", "RF", 2018, 2025),
  player("ramirjo01", "José Ramírez", "B", "3B", 2013, 2025),
  player("rileyau01", "Austin Riley", "R", "3B", 2019, 2025),
  player("acunaro01", "Ronald Acuña Jr.", "R", "RF", 2018, 2025),
  player("freemfr01", "Freddie Freeman", "L", "1B", 2010, 2025),
  player("tatisfe02", "Fernando Tatis Jr.", "R", "RF", 2019, 2025),
  player("wittbo02", "Bobby Witt Jr.", "R", "SS", 2022, 2025),
  player("seageco01", "Corey Seager", "L", "SS", 2015, 2025),
  player("hayeske01", "Ke'Bryan Hayes", "R", "3B", 2020, 2025),
  player("kinerisi01", "Isiah Kiner-Falefa", "R", null, 2018, 2025),
];

export function playerRef(id: string): Pick<PlayerSummary, "id" | "name"> {
  const found = PLAYERS.find((p) => p.id === id);
  if (!found) throw new Error(`Fixture player missing: ${id}`);
  return { id: found.id, name: found.name };
}
