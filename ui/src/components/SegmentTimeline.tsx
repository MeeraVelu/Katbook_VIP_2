import { useState } from "react";
import type { SegmentOut } from "@/lib/types";
import { subjectColor } from "@/lib/viz";
import { fmtClock } from "@/lib/format";

interface Props {
  segments: SegmentOut[];
  duration: number | null;
  onSelect?: (segIndex: number) => void;
  mini?: boolean;
}

// Horizontal bar scaled to the video duration. Each segment is a block: x/width by
// time, color by subject, height by confidence. Hover → tooltip; click → onSelect.
export function SegmentTimeline({ segments, duration, onSelect, mini }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const total = duration && duration > 0 ? duration : Math.max(1, ...segments.map((s) => s.end_sec));
  const trackH = mini ? 12 : 46;

  return (
    <div className="relative w-full" style={{ height: trackH }}>
      <div className="absolute inset-0 rounded-lg border border-line bg-slate-50" />
      {segments.map((s) => {
        const left = (s.start_sec / total) * 100;
        const width = Math.max(((s.end_sec - s.start_sec) / total) * 100, mini ? 0.8 : 1.2);
        const conf = s.confidence == null ? 0.5 : Math.max(0.15, Math.min(1, s.confidence));
        const h = mini ? 100 : 30 + conf * 70; // % of track height
        const active = hover === s.seg_index;
        return (
          <button
            key={s.seg_index}
            type="button"
            aria-label={`Segment ${s.seg_index + 1}: ${s.topic ?? "untitled"}`}
            onMouseEnter={() => setHover(s.seg_index)}
            onMouseLeave={() => setHover(null)}
            onClick={() => onSelect?.(s.seg_index)}
            className="absolute bottom-0 rounded-[3px] transition-[filter,transform] focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            style={{
              left: `${left}%`,
              width: `${width}%`,
              height: `${h}%`,
              background: subjectColor(s.subject),
              opacity: active ? 1 : 0.82,
              filter: active ? "brightness(1.15)" : "none",
              cursor: onSelect ? "pointer" : "default",
            }}
            title={mini ? `${s.topic ?? "untitled"} · ${s.subject ?? ""}` : undefined}
          />
        );
      })}

      {!mini && hover !== null && (() => {
        const s = segments.find((x) => x.seg_index === hover);
        if (!s) return null;
        const left = (s.start_sec / total) * 100;
        return (
          <div
            className="pointer-events-none absolute -top-1 z-10 -translate-y-full whitespace-nowrap rounded-lg border border-line bg-white px-2.5 py-1.5 text-xs shadow-glow"
            style={{ left: `${Math.min(left, 82)}%` }}
          >
            <div className="font-medium text-fg">{s.topic ?? "untitled"}</div>
            <div className="num text-[11px] text-muted">
              {fmtClock(s.start_sec)}–{fmtClock(s.end_sec)} · {s.subject ?? "—"} ·{" "}
              {s.confidence == null ? "—" : `${Math.round(s.confidence * 100)}%`}
            </div>
          </div>
        );
      })()}
    </div>
  );
}
