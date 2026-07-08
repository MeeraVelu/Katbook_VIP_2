import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Activity, ArrowRight, Radio } from "lucide-react";
import { useVideos } from "@/hooks/queries";
import { recentJobs } from "@/lib/recents";
import { fileName, fmtClock, shortId } from "@/lib/format";
import { Badge, Button, EmptyState, IconBadge, Panel, SkeletonRows } from "@/components/primitives";

export function Jobs() {
  const nav = useNavigate();
  const [jobId, setJobId] = useState("");
  const recents = recentJobs();

  // in-flight board: processing first, then queued (the API has no list-jobs)
  const processing = useVideos(1, 12, { status: "processing" });
  const queued = useVideos(1, 12, { status: "queued" });
  const active = [...(processing.data?.items ?? []), ...(queued.data?.items ?? [])];
  const loading = processing.isLoading || queued.isLoading;

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <IconBadge icon={Activity} tone="accent" size={40} />
        <div>
          <h1 className="font-display text-2xl font-bold">Jobs</h1>
          <p className="text-sm text-muted">Watch a specific job, or track everything in flight.</p>
        </div>
      </div>

      {!loading && (processing.data || queued.data) && (
        <div className="flex flex-wrap gap-3">
          <StatChip
            label="processing"
            count={processing.data?.total ?? 0}
            tone="text-sky-700 bg-sky-50 border-sky-200"
            pulse
          />
          <StatChip label="queued" count={queued.data?.total ?? 0} tone="text-cyan-700 bg-cyan-50 border-cyan-200" />
        </div>
      )}

      <Panel glow="accent" className="flex flex-wrap items-center gap-2">
        <Radio size={15} className="text-accent" />
        <input
          value={jobId}
          onChange={(e) => setJobId(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && jobId.trim() && nav(`/jobs/${jobId.trim()}`)}
          placeholder="job id (uuid)…"
          className="num flex-1 rounded-full border border-line bg-slate-50 px-4 py-2 text-sm outline-none transition-colors focus:border-accent/50 focus:bg-white focus:ring-1 focus:ring-accent/30"
        />
        <Button disabled={!jobId.trim()} onClick={() => nav(`/jobs/${jobId.trim()}`)}>
          Watch <ArrowRight size={15} />
        </Button>
      </Panel>

      <section>
        <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-wide text-faint">
          <Activity size={13} /> In flight
        </div>
        {loading ? (
          <SkeletonRows rows={3} />
        ) : active.length === 0 ? (
          <EmptyState icon={Activity} title="Nothing processing" hint="Queued and processing videos show up here while the worker runs." />
        ) : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {active.map((v) => (
              <Panel key={v.video_id} hover glow="accent" className="cursor-pointer hover:scale-[1.01]">
                <button className="w-full text-left" onClick={() => nav(`/videos/${v.video_id}`)}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-medium">{fileName(v.source_path)}</span>
                    <Badge status={v.status} />
                  </div>
                  <div className="num mt-1 text-[11px] text-faint">
                    {shortId(v.video_id)} · {fmtClock(v.duration_sec)}
                  </div>
                </button>
              </Panel>
            ))}
          </div>
        )}
      </section>

      {recents.length > 0 && (
        <section>
          <div className="mb-2 text-xs uppercase tracking-wide text-faint">Recently watched jobs</div>
          <div className="flex flex-wrap gap-2">
            {recents.map((id) => (
              <button
                key={id}
                onClick={() => nav(`/jobs/${id}`)}
                className="num rounded-full border border-line bg-slate-50 px-3 py-1.5 text-xs text-muted transition-colors hover:border-accent/30 hover:bg-white hover:text-fg"
              >
                {shortId(id, 8)}
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function StatChip({ label, count, tone, pulse }: { label: string; count: number; tone: string; pulse?: boolean }) {
  return (
    <div className={`flex items-center gap-2 rounded-full border px-3.5 py-2 text-sm ${tone}`}>
      {pulse && count > 0 && <span className="h-1.5 w-1.5 rounded-full bg-current animate-pulse-accent" />}
      <span className="num text-base font-semibold">{count}</span>
      <span className="text-xs uppercase tracking-wide opacity-80">{label}</span>
    </div>
  );
}
