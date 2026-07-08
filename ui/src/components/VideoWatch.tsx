import { useMemo, useRef, useState } from "react";
import { PlayCircle, VideoOff } from "lucide-react";
import type { SegmentOut } from "@/lib/types";
import { streamUrl } from "@/lib/api";
import { fmtClock } from "@/lib/format";
import { subjectColor } from "@/lib/viz";
import { IconBadge, Panel, cx } from "./primitives";

// Video player + a Seg/Time/Topic/Subject/Grade table. Clicking a row seeks the
// player to that segment's start_sec; the segment under the playhead is tracked
// via the video's timeupdate event and highlighted, with its transcript shown
// below the table. If the source file isn't on disk (deleted after processing),
// a placeholder shows instead of the player and the table still renders.
export function VideoWatch({
  videoId,
  segments,
}: {
  videoId: string;
  segments: SegmentOut[];
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [current, setCurrent] = useState(0);
  const [available, setAvailable] = useState(true);

  const activeIndex = useMemo(
    () => segments.findIndex((s) => current >= s.start_sec && current < s.end_sec),
    [segments, current],
  );
  const active = activeIndex >= 0 ? segments[activeIndex] : null;

  function seekTo(s: SegmentOut) {
    const el = videoRef.current;
    if (!el) return;
    el.currentTime = s.start_sec;
    void el.play().catch(() => {});
  }

  return (
    <Panel glow="accent" className="space-y-4">
      <div className="flex items-center gap-2.5">
        <IconBadge icon={PlayCircle} tone="accent" size={30} iconSize={16} />
        <div className="text-xs uppercase tracking-wide text-faint">Watch</div>
      </div>

      {/* player — responsive, capped at ~800px, centered */}
      <div className="mx-auto w-full max-w-[800px]">
        {available ? (
          // eslint-disable-next-line jsx-a11y/media-has-caption
          <video
            ref={videoRef}
            src={streamUrl(videoId)}
            controls
            preload="metadata"
            onTimeUpdate={(e) => setCurrent(e.currentTarget.currentTime)}
            onError={() => setAvailable(false)}
            className="aspect-video w-full rounded-xl bg-black shadow-panel ring-1 ring-line"
          />
        ) : (
          <div className="flex aspect-video w-full flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-line bg-slate-50 px-4 text-center">
            <VideoOff size={28} className="text-faint" />
            <div className="text-sm font-medium text-muted">Video file not available for playback</div>
            <div className="max-w-xs text-xs text-faint">
              The source file may have been removed after processing. Segment data is still shown below.
            </div>
          </div>
        )}
      </div>

      {/* now playing */}
      <div className="text-sm">
        <span className="text-faint">Now playing: </span>
        {active ? (
          <span className="font-medium">
            Segment {activeIndex + 1} —{" "}
            <span style={{ color: subjectColor(active.subject) }}>{active.topic ?? "untitled segment"}</span>
          </span>
        ) : (
          <span className="text-muted">—</span>
        )}
      </div>

      {/* segment table */}
      <div className="overflow-hidden rounded-xl border border-line">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 text-left text-xs uppercase tracking-wide text-faint">
              <th className="px-3 py-2 font-medium">Seg</th>
              <th className="px-3 py-2 font-medium">Time</th>
              <th className="px-3 py-2 font-medium">Topic</th>
              <th className="px-3 py-2 font-medium">Subject</th>
              <th className="px-3 py-2 font-medium">Grade</th>
            </tr>
          </thead>
          <tbody>
            {segments.map((s, i) => (
              <tr
                key={s.seg_index}
                onClick={() => seekTo(s)}
                title={available ? `Jump to ${fmtClock(s.start_sec)}` : undefined}
                className={cx(
                  "border-t border-line transition-colors",
                  available && "cursor-pointer",
                  i === activeIndex ? "bg-sky-50" : "bg-white hover:bg-sky-50/60",
                )}
              >
                <td className="px-3 py-2">
                  <span className="flex items-center gap-1 font-medium text-fg">
                    {i === activeIndex && (
                      <PlayCircle size={13} className="shrink-0 text-accent" fill="currentColor" fillOpacity={0.25} />
                    )}
                    <span className="num">{i}</span>
                  </span>
                </td>
                <td className="num px-3 py-2 whitespace-nowrap text-muted">
                  {fmtClock(s.start_sec)}–{fmtClock(s.end_sec)}
                </td>
                <td className="max-w-[220px] truncate px-3 py-2" style={{ color: subjectColor(s.subject) }}>
                  {s.topic ?? "untitled segment"}
                </td>
                <td className="px-3 py-2 text-muted">{s.subject ?? "—"}</td>
                <td className="px-3 py-2 text-muted">{s.grade_level ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* transcript of the current segment */}
      <div>
        <div className="mb-1.5 text-xs uppercase tracking-wide text-faint">Transcript (current segment)</div>
        <p className="rounded-xl border border-line bg-slate-50 px-3.5 py-3 text-sm leading-relaxed text-fg/90">
          {active?.transcript_text || (
            <span className="text-muted">
              {available ? "Play the video or click a segment row to see its transcript." : "—"}
            </span>
          )}
        </p>
      </div>
    </Panel>
  );
}
