/** What the status shows for each party member (docs/LAYOUT.md 4): a short headline and the hit points with a tint. */

export type HpTone = "ok" | "low" | "critical" | "unknown";

/** "Human Paladin 3 (Oath of the Ancients)" -> "Paladin 3": the last class and level, or the headline cut at "(". */
export function shortHeadline(headline: unknown): string {
  const text = typeof headline === "string" ? headline.replace(/\s*\(.*$/, "").trim() : "";
  const m = text.match(/([A-Za-z][A-Za-z' -]*?)\s+(\d+)$/);
  if (!m) return text;
  const word = m[1].trim().split(/\s+/).pop() ?? "";
  return `${word} ${m[2]}`;
}

/** How hurt someone is by their "22/25": yellow below half, red below a quarter. */
export function hpTone(hp: unknown): HpTone {
  const m = typeof hp === "string" ? hp.match(/^\s*(-?\d+)\s*\/\s*(\d+)/) : null;
  if (!m || Number(m[2]) <= 0) return "unknown";
  const share = Number(m[1]) / Number(m[2]);
  return share < 0.25 ? "critical" : share < 0.5 ? "low" : "ok";
}
