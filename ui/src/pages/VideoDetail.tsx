import { useEffect } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  BarChart3,
  Clock,
  Fingerprint,
  GraduationCap,
  Languages,
  Layers,
  Trash2,
} from "lucide-react";
import { useSoftDelete, useVideo } from "@/hooks/queries";
import type { SegmentOut } from "@/lib/types";
import { fileName, fmtClock, shortId } from "@/lib/format";
import { subjectColor } from "@/lib/viz";
import { SegmentTimeline } from "@/components/SegmentTimeline";
import { VideoWatch } from "@/components/VideoWatch";
import { ConfidenceRing } from "@/components/ConfidenceRing";
import { Badge, Button, ErrorState, IconBadge, Panel, Skeleton, StatTile } from "@/components/primitives";

export function VideoDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const { hash } = useLocation();
  const { data: v, isLoading, isError, error, refetch } = useVideo(id);
  const del = useSoftDelete();

  // deep-link: /videos/:id#seg-N → scroll to that segment card
  useEffect(() => {
    if (v && hash) {
      const el = document.getElementById(hash.slice(1));
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        el.classList.add("ring-2", "ring-accent");
        const t = setTimeout(() => el.classList.remove("ring-2", "ring-accent"), 1600);
        return () => clearTimeout(t);
      }
    }
  }, [v, hash]);

  function scrollToSeg(i: number) {
    document.getElementById(`seg-${i}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  if (isLoading)
    return (
      <div className="space-y-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  if (isError) return <ErrorState message={(error as Error).message} onRetry={() => refetch()} />;
  if (!v) return null;

  return (
    <div className="space-y-5">
      <button onClick={() => nav("/library")} className="flex items-center gap-1 text-sm text-muted hover:text-fg">
        <ArrowLeft size={15} /> Library
      </button>

      {/* header */}
      <Panel glow="accent" className="space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <IconBadge icon={Layers} tone="accent" size={44} />
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h1 className="truncate font-display text-2xl font-bold">{fileName(v.source_path)}</h1>
                <Badge status={v.status} />
              </div>
              <div className="num mt-1 text-xs text-faint">{v.video_id}</div>
            </div>
          </div>
          <Button
            variant="danger"
            disabled={del.isPending || v.status === "soft_deleted"}
            onClick={() => {
              if (confirm("Soft-delete this video? Content and segments are retained (status flag only).")) {
                del.mutate(v.video_id, { onSuccess: () => nav("/library") });
              }
            }}
          >
            <Trash2 size={15} /> Soft-delete
          </Button>
        </div>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <StatTile icon={Clock} label="Duration" value={fmtClock(v.duration_sec)} tone="cyan" mono />
          <StatTile icon={BarChart3} label="Segments" value={v.segment_count} tone="accent" mono />
          <StatTile icon={Languages} label="Language" value={v.language ?? "—"} tone="muted" />
          <StatTile icon={GraduationCap} label="Grade" value={v.rollup.grade ?? "—"} tone="muted" />
          <StatTile icon={Layers} label="Path" value={v.tagging_path ?? "—"} tone="muted" />
          <StatTile
            icon={BarChart3}
            label="Subject"
            value={<span style={{ color: subjectColor(v.rollup.subject) }}>{v.rollup.subject ?? "—"}</span>}
            tone="muted"
          />
          <StatTile icon={GraduationCap} label="Difficulty" value={v.rollup.difficulty ?? "—"} tone="muted" />
          <StatTile icon={Fingerprint} label="Hash" value={shortId(v.content_hash, 12)} tone="muted" mono />
        </div>

        {v.rollup.primary_topic && (
          <div className="text-sm">
            <span className="text-faint">Primary topic · </span>
            <span className="text-fg">{v.rollup.primary_topic}</span>
          </div>
        )}

        {v.error_message && (
          <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{v.error_message}</div>
        )}

        {v.segments.length > 0 && (
          <div>
            <div className="mb-2 text-xs uppercase tracking-wide text-faint">Segment timeline</div>
            <SegmentTimeline segments={v.segments} duration={v.duration_sec} onSelect={scrollToSeg} />
          </div>
        )}
      </Panel>

      {/* video player + click-to-seek segment list */}
      {v.segments.length > 0 && <VideoWatch videoId={v.video_id} segments={v.segments} />}

      {/* segment cards */}
      <div className="space-y-3">
        {v.segments.map((s) => (
          <SegmentCard key={s.seg_index} s={s} />
        ))}
      </div>
    </div>
  );
}

function SegmentCard({ s }: { s: SegmentOut }) {
  const silentEvidence = s.scenes.length || s.objects.length || s.captions.length;
  const color = subjectColor(s.subject);
  return (
    <Panel id={`seg-${s.seg_index}`} hover className="scroll-mt-24">
      <div aria-hidden className="absolute inset-y-0 left-0 w-1" style={{ background: color }} />
      <div className="flex items-start gap-4 pl-1.5">
        <div className="flex flex-col items-center gap-1.5">
          <ConfidenceRing value={s.confidence} />
          <span className="num rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] text-faint">#{s.seg_index + 1}</span>
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="font-display text-lg font-semibold" style={{ color }}>
              {s.topic ?? "untitled segment"}
            </h3>
            <span className="num rounded-full bg-slate-100 px-2 py-0.5 text-xs text-muted">
              {fmtClock(s.start_sec)}–{fmtClock(s.end_sec)}
            </span>
          </div>
          <div className="mt-0.5 text-xs text-muted">
            {[s.subject, s.grade_level, s.content_type, s.difficulty].filter(Boolean).join(" · ") || "—"}
          </div>
          {s.summary && <p className="mt-2 text-sm text-fg/90">{s.summary}</p>}
          {s.tags.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {s.tags.map((t) => (
                <span
                  key={t}
                  className="rounded-full border border-line bg-slate-50 px-2.5 py-0.5 text-[11px] text-muted transition-colors hover:border-accent/30 hover:bg-sky-50 hover:text-fg"
                >
                  {t}
                </span>
              ))}
            </div>
          )}
          {silentEvidence > 0 && (
            <div className="mt-2 space-y-0.5 text-[11px] text-faint">
              {s.scenes.length > 0 && <div>scenes · {s.scenes.join(", ")}</div>}
              {s.objects.length > 0 && <div>objects · {s.objects.join(", ")}</div>}
              {s.captions.length > 0 && <div>captions · {s.captions.join(" · ")}</div>}
            </div>
          )}
        </div>
      </div>
    </Panel>
  );
}
