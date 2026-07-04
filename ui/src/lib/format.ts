// Formatting helpers. All numeric output is meant to render in the `.num` (mono,
// tabular) class at the call site.

export function fmtClock(sec: number | null | undefined): string {
  if (sec == null || Number.isNaN(sec)) return "—";
  const s = Math.max(0, Math.floor(sec));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

export function fmtDuration(sec: number | null | undefined): string {
  if (sec == null) return "—";
  if (sec < 60) return `${sec.toFixed(0)}s`;
  return fmtClock(sec);
}

export function fmtBytes(n: number | null | undefined): string {
  if (n == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function fmtScore(score: number, mode: string): string {
  // hybrid uses fused RRF (small values); semantic/keyword are 0..1-ish
  return mode === "hybrid" ? score.toFixed(4) : score.toFixed(3);
}

export function shortId(id: string | null | undefined, n = 8): string {
  return id ? id.slice(0, n) : "—";
}

export function fileName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}
