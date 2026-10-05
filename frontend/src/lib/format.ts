// Display formatting helpers shared across pages.

export function fmt(v: unknown, digits = 3): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") {
    if (Number.isInteger(v)) return String(v);
    const p = v.toPrecision(Math.max(digits, Math.ceil(Math.log10(Math.abs(v) + 1))));
    return p.includes("e") ? p : p.includes(".") ? p.replace(/0+$/, "").replace(/\.$/, "") : p;
  }
  return String(v);
}

export function orgLabel(org: string): string {
  return org === "internal" ? "Internal" : org.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function initials(name: string): string {
  return name
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join("");
}
