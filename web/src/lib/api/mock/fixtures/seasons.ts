/**
 * SAMPLE DATA: single-season batting lines. Illustrative numbers only (see players.ts).
 * Deliberate gaps: Vladimir Guerrero Jr. 2025 has no SB value and Salvador Perez 2021 has no
 * position, so the UI's missing-value handling is always exercised.
 */
import type { PlayerSeason, StatLine } from "../../types";
import { playerRef } from "./players";

type Line = [AB: number, H: number, HR: number, RBI: number, SB: number | null, BB: number | null,
  BA: number, OBP: number, SLG: number, OPS: number];

function season(playerId: string, year: number, team: string | null, position: string | null, line: Line): PlayerSeason {
  const [AB, H, HR, RBI, SB, BB, BA, OBP, SLG, OPS] = line;
  const stats: StatLine = { AB, H, HR, RBI, SB, BB, BA, OBP, SLG, OPS };
  return { id: `${playerId}-${year}`, player: playerRef(playerId), year, team, teamName: null, position, stats, qualified: true, rank: null };
}

const ALL: PlayerSeason[] = [
  // Aaron Judge
  season("judgeaa01", 2016, "NYY", "RF", [84, 15, 4, 10, 0, 9, 0.179, 0.263, 0.345, 0.608]),
  season("judgeaa01", 2017, "NYY", "RF", [542, 154, 52, 114, 9, 127, 0.284, 0.422, 0.627, 1.049]),
  season("judgeaa01", 2018, "NYY", "RF", [413, 115, 27, 67, 6, 76, 0.278, 0.392, 0.528, 0.919]),
  season("judgeaa01", 2019, "NYY", "RF", [378, 103, 27, 55, 3, 64, 0.272, 0.381, 0.540, 0.921]),
  season("judgeaa01", 2020, "NYY", "RF", [101, 26, 9, 22, 0, 10, 0.257, 0.336, 0.554, 0.891]),
  season("judgeaa01", 2021, "NYY", "RF", [550, 158, 39, 98, 6, 75, 0.287, 0.373, 0.544, 0.916]),
  season("judgeaa01", 2022, "NYY", "RF", [570, 177, 62, 131, 16, 111, 0.311, 0.425, 0.686, 1.111]),
  season("judgeaa01", 2023, "NYY", "RF", [367, 98, 37, 75, 3, 88, 0.267, 0.406, 0.613, 1.019]),
  season("judgeaa01", 2024, "NYY", "CF", [559, 180, 58, 144, 10, 133, 0.322, 0.458, 0.701, 1.159]),
  season("judgeaa01", 2025, "NYY", "RF", [541, 179, 53, 114, 12, 124, 0.331, 0.457, 0.688, 1.145]),
  // Vladimir Guerrero Jr.
  season("guerrvl02", 2019, "TOR", "3B", [464, 126, 15, 69, 0, 46, 0.272, 0.339, 0.433, 0.772]),
  season("guerrvl02", 2020, "TOR", "1B", [221, 58, 9, 33, 1, 20, 0.262, 0.329, 0.462, 0.791]),
  season("guerrvl02", 2021, "TOR", "1B", [604, 188, 48, 111, 4, 86, 0.311, 0.401, 0.601, 1.002]),
  season("guerrvl02", 2022, "TOR", "1B", [604, 175, 32, 97, 8, 58, 0.274, 0.339, 0.480, 0.818]),
  season("guerrvl02", 2023, "TOR", "1B", [602, 159, 26, 94, 5, 67, 0.264, 0.345, 0.444, 0.788]),
  season("guerrvl02", 2024, "TOR", "1B", [616, 199, 30, 103, 2, 72, 0.323, 0.396, 0.544, 0.940]),
  season("guerrvl02", 2025, "TOR", "1B", [589, 172, 23, 84, null, 81, 0.292, 0.381, 0.467, 0.848]),
  // Other leaders
  season("raleica01", 2025, "SEA", "C", [596, 147, 60, 125, 14, 97, 0.247, 0.359, 0.589, 0.948]),
  season("stantmi03", 2017, "MIA", "RF", [597, 168, 59, 132, 2, 85, 0.281, 0.376, 0.631, 1.007]),
  season("schwaky01", 2025, "PHI", "DH", [600, 145, 56, 132, 10, 108, 0.240, 0.365, 0.563, 0.928]),
  season("ohtansh01", 2025, "LAD", "DH", [611, 172, 55, 102, 20, 109, 0.282, 0.392, 0.622, 1.014]),
  season("ohtansh01", 2024, "LAD", "DH", [636, 197, 54, 130, 59, 81, 0.310, 0.390, 0.646, 1.036]),
  season("bautijo02", 2010, "TOR", "RF", [569, 148, 54, 124, 9, 100, 0.260, 0.378, 0.617, 0.995]),
  season("olsonma02", 2023, "ATL", "1B", [608, 172, 54, 139, 1, 104, 0.283, 0.389, 0.604, 0.993]),
  season("alonspe01", 2019, "NYM", "1B", [597, 155, 53, 120, 1, 72, 0.260, 0.358, 0.583, 0.941]),
  season("davisch02", 2013, "BAL", "1B", [584, 167, 53, 138, 4, 72, 0.286, 0.370, 0.634, 1.004]),
  season("perezsa02", 2021, "KC", null, [620, 169, 48, 121, 1, 28, 0.273, 0.316, 0.544, 0.860]),
  season("harpebr03", 2015, "WSH", "RF", [521, 172, 42, 99, 6, 124, 0.330, 0.460, 0.649, 1.109]),
  season("yelicch01", 2019, "MIL", "RF", [489, 161, 44, 97, 30, 80, 0.329, 0.429, 0.671, 1.100]),
  season("troutmi01", 2018, "LAA", "CF", [471, 147, 39, 79, 24, 122, 0.312, 0.460, 0.628, 1.088]),
  season("cabremi01", 2013, "DET", "3B", [555, 193, 44, 137, 3, 90, 0.348, 0.442, 0.636, 1.078]),
  season("vottojo01", 2010, "CIN", "1B", [547, 177, 37, 113, 16, 91, 0.324, 0.424, 0.600, 1.024]),
];

const BY_ID = new Map(ALL.map((s) => [s.id, s]));

/**
 * The listed seasons, in the listed order. `unqualified` marks rows below the at-bat minimum,
 * as declared by the fixture author (the mock never evaluates the rule itself).
 */
export function seasonRows(ids: string[], unqualified: string[] = []): PlayerSeason[] {
  let rank = 0;
  return ids.map((id) => {
    const found = BY_ID.get(id);
    if (!found) throw new Error(`Fixture season missing: ${id}`);
    const qualified = !unqualified.includes(id);
    return { ...found, qualified, rank: qualified ? ++rank : null };
  });
}
