import { ArrowRight } from "lucide-react";
import type { SearchHit } from "@/lib/types";
import { fmtClock, fmtScore, shortId } from "@/lib/format";
import { cx } from "./primitives";

export function HitRow({
  hit,
  maxScore,
  mode,
  selected,
  onClick,
}: {
  hit: SearchHit;
  maxScore: number;
  mode: string;
  selected?: boolean;
  onClick?: () => void;
}) {
  const pct = maxScore > 0 ? Math.max(6, (hit.score / maxScore) * 100) : 0;
  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(
        "group flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition-all duration-200",
        selected ? "border-accent/30 bg-sky-50" : "border-transparent hover:border-line hover:bg-sky-50/60",
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-fg">{hit.topic ?? "untitled segment"}</div>
        <div className="num truncate text-[11px] text-muted">
          {hit.subject ?? "—"} · {hit.grade_level ?? "—"} · {fmtClock(hit.start_sec)}–{fmtClock(hit.end_sec)} ·
          video {shortId(hit.video_id)} · seg {hit.seg_index}
        </div>
        {hit.summary && <div className="mt-0.5 truncate text-[11px] text-faint">{hit.summary}</div>}
      </div>
      <div className="flex w-28 flex-col items-end gap-1">
        <span className="num text-xs text-cyan-600">{fmtScore(hit.score, mode)}</span>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
          <div className="h-full rounded-full bg-gradient-to-r from-accent to-cyan" style={{ width: `${pct}%` }} />
        </div>
      </div>
      <ArrowRight size={15} className="text-faint transition-all group-hover:translate-x-0.5 group-hover:text-accent" />
    </button>
  );
}
