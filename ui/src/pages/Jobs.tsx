import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Activity,
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  Clock,
  FileVideo,
  Flag,
  Hourglass,
  ListOrdered,
  PlayCircle,
  Radio,
  Repeat,
  XCircle,
} from "lucide-react";
import { useActiveJobs, useJobHistory, useVideos } from "@/hooks/queries";
import { recentJobs } from "@/lib/recents";
import { fileName, fmtClock, fmtDate, fmtDuration, shortId } from "@/lib/format";
import { PipelineStepper } from "@/components/PipelineStepper";
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  IconBadge,
  Panel,
  SkeletonRows,
  StatTile,
  cx,
} from "@/components/primitives";

const HISTORY_PAGE_SIZE = 10;
type Tab = "processing" | "queued" | "processed";

export function Jobs() {
  const nav = useNavigate();
  const [jobId, setJobId] = useState("");
  const [tab, setTab] = useState<Tab>("processing");
  const recents = recentJobs();

  // Every tab's count is fetched unconditionally so the tab bar's badges are
  // always accurate, not just when that tab happens to be open. This history
  // query is UNFILTERED so the "Processed" badge shows the total (done+failed);
  // the Processed tab's Done/Failed/All sub-filter is owned inside ProcessedTab.
  const active = useActiveJobs();
  const queued = useVideos(1, 50, { status: "queued" });
  const history = useJobHistory(1, HISTORY_PAGE_SIZE);

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <IconBadge icon={Activity} tone="accent" size={40} />
        <div>
          <h1 className="font-display text-2xl font-bold">Jobs</h1>
          <p className="text-sm text-muted">Watch a specific job, or track everything in flight.</p>
        </div>
      </div>

      {/* tab bar */}
      <div className="flex flex-wrap gap-2">
        <TabButton
          label="Processing"
          count={active.data?.length ?? 0}
          activeTone="text-sky-700 bg-sky-50 border-sky-200"
          selected={tab === "processing"}
          onClick={() => setTab("processing")}
          pulse={(active.data?.length ?? 0) > 0}
        />
        <TabButton
          label="Queued"
          count={queued.data?.total ?? 0}
          activeTone="text-cyan-700 bg-cyan-50 border-cyan-200"
          selected={tab === "queued"}
          onClick={() => setTab("queued")}
        />
        <TabButton
          label="Processed"
          count={history.data?.total ?? 0}
          activeTone="text-emerald-700 bg-emerald-50 border-emerald-200"
          selected={tab === "processed"}
          onClick={() => setTab("processed")}
        />
      </div>

      {tab === "processing" && <ProcessingTab query={active} onOpenVideo={(id) => nav(`/videos/${id}`)} />}
      {tab === "queued" && <QueuedTab query={queued} onOpenVideo={(id) => nav(`/videos/${id}`)} />}
      {tab === "processed" && <ProcessedTab onOpenVideo={(id) => nav(`/videos/${id}`)} />}

      {/* watch a specific job by id */}
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

function TabButton({
  label,
  count,
  activeTone,
  selected,
  onClick,
  pulse,
}: {
  label: string;
  count: number;
  activeTone: string;
  selected: boolean;
  onClick: () => void;
  pulse?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      className={cx(
        "flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-medium transition-all duration-150",
        selected ? cx(activeTone, "shadow-sm") : "border-line bg-white text-muted hover:bg-slate-50",
      )}
    >
      {pulse && <span className="h-1.5 w-1.5 rounded-full bg-current animate-pulse-accent" />}
      <span>{label}</span>
      <span className="num rounded-full bg-white/70 px-1.5 py-0.5 text-xs">{count}</span>
    </button>
  );
}

// ---- PROCESSING ------------------------------------------------------------

function ProcessingTab({
  query,
  onOpenVideo,
}: {
  query: ReturnType<typeof useActiveJobs>;
  onOpenVideo: (videoId: string) => void;
}) {
  if (query.isLoading) return <SkeletonRows rows={2} />;
  if (query.isError) return <ErrorState message={(query.error as Error).message} onRetry={() => query.refetch()} />;
  const jobs = query.data ?? [];
  if (jobs.length === 0) {
    return (
      <EmptyState
        icon={Activity}
        title="No jobs currently processing"
        hint="The worker processes one video at a time — this shows it live, refreshing every few seconds."
      />
    );
  }
  return (
    <div className="space-y-4">
      {jobs.map((j) => (
        <Panel key={j.job_id} glow="accent" className="space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <IconBadge icon={Flag} tone="accent" size={40} />
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="font-display text-lg font-bold">{j.video_filename ?? "Job"}</h2>
                  <Badge status={j.state} />
                  <span className="num flex items-center gap-1 text-xs text-accent">
                    <span className="h-1.5 w-1.5 rounded-full bg-accent animate-pulse-accent" /> live
                  </span>
                </div>
                <div className="num mt-1 text-xs text-faint">{j.job_id}</div>
              </div>
            </div>
            {j.video_id && (
              <Button variant="ghost" onClick={() => onOpenVideo(j.video_id!)}>
                <FileVideo size={15} /> View video
              </Button>
            )}
          </div>

          {/* hero: pipeline stepper — same component as the Job Detail page */}
          <PipelineStepper
            state={j.state}
            currentStage={j.current_stage}
            elapsedSec={j.elapsed_sec}
            stageTimings={j.stage_timings}
          />

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <StatTile icon={PlayCircle} label="Current stage" value={j.current_stage ?? "—"} tone="accent" />
            <StatTile icon={Repeat} label="Attempts" value={j.attempts} tone="muted" mono />
            <StatTile icon={Hourglass} label="Elapsed" value={j.elapsed_sec != null ? `${j.elapsed_sec}s` : "—"} tone="cyan" mono />
            <StatTile icon={FileVideo} label="Video" value={shortId(j.video_id)} tone="muted" mono />
            <StatTile icon={CalendarClock} label="Enqueued" value={fmtDate(j.enqueued_at)} tone="muted" mono />
            <StatTile icon={CalendarClock} label="Started" value={fmtDate(j.started_at)} tone="muted" mono />
          </div>
        </Panel>
      ))}
    </div>
  );
}

// ---- QUEUED -----------------------------------------------------------------

function QueuedTab({
  query,
  onOpenVideo,
}: {
  query: ReturnType<typeof useVideos>;
  onOpenVideo: (videoId: string) => void;
}) {
  if (query.isLoading) return <SkeletonRows rows={3} />;
  if (query.isError) return <ErrorState message={(query.error as Error).message} onRetry={() => query.refetch()} />;
  // the API returns newest-first; queue order (first in = first out) is oldest-first
  const items = [...(query.data?.items ?? [])].reverse();
  if (items.length === 0) {
    return <EmptyState icon={ListOrdered} title="No jobs in queue" hint="Videos wait here until the worker is free to process them." />;
  }
  return (
    <div className="space-y-2">
      {items.map((v, i) => (
        <Panel key={v.video_id} hover>
          <button type="button" className="flex w-full items-center gap-3 text-left" onClick={() => onOpenVideo(v.video_id)}>
            <span className="num flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-cyan-50 text-xs font-semibold text-cyan-700">
              {ordinalShort(i + 1)}
            </span>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium text-fg">{fileName(v.source_path)}</div>
              <div className="num text-xs text-faint">
                {shortId(v.video_id)} · {fmtClock(v.duration_sec)}
              </div>
            </div>
            <div className="shrink-0 text-right">
              <div className="text-xs text-muted">waiting</div>
              <div className="num text-xs font-medium text-fg">{waitingSince(v.created_at)}</div>
            </div>
          </button>
        </Panel>
      ))}
    </div>
  );
}

function ordinalShort(n: number): string {
  return `${n}${["th", "st", "nd", "rd"][n % 10 > 3 || Math.floor((n % 100) / 10) === 1 ? 0 : n % 10]}`;
}

function waitingSince(iso: string | null): string {
  if (!iso) return "—";
  const sec = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  return fmtDuration(sec);
}

// ---- PROCESSED ---------------------------------------------------------------

type HistoryFilter = "all" | "done" | "failed";
const HISTORY_FILTERS: { key: HistoryFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "done", label: "Done" },
  { key: "failed", label: "Failed" },
];

// Self-contained: owns its Done/Failed/All sub-filter + pagination, and runs
// its own history query. The parent's unfiltered history query (for the tab
// badge) and this one share a React Query key when filter === "all", so there's
// no duplicate fetch in the default view.
function ProcessedTab({ onOpenVideo }: { onOpenVideo: (videoId: string) => void }) {
  const [filter, setFilter] = useState<HistoryFilter>("all");
  const [page, setPage] = useState(1);
  const query = useJobHistory(page, HISTORY_PAGE_SIZE, filter === "all" ? undefined : filter);

  function changeFilter(f: HistoryFilter) {
    setFilter(f);
    setPage(1); // page counts differ per filter — always restart at page 1
  }

  const data = query.data;
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const emptyTitle =
    filter === "failed" ? "No failed jobs" : filter === "done" ? "No completed jobs yet" : "No processed videos yet";

  return (
    <div className="space-y-3">
      {/* Done / Failed / All sub-filter */}
      <div className="flex w-fit gap-1 rounded-full border border-line bg-slate-50 p-0.5">
        {HISTORY_FILTERS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => changeFilter(key)}
            className={cx(
              "rounded-full px-3.5 py-1.5 text-xs font-medium transition-all",
              filter === key
                ? key === "failed"
                  ? "bg-red-100 text-red-700 shadow-sm"
                  : key === "done"
                    ? "bg-emerald-100 text-emerald-700 shadow-sm"
                    : "bg-white text-fg shadow-sm"
                : "text-muted hover:text-fg",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {query.isLoading ? (
        <SkeletonRows rows={5} />
      ) : query.isError ? (
        <ErrorState message={(query.error as Error).message} onRetry={() => query.refetch()} />
      ) : !data || data.items.length === 0 ? (
        <EmptyState
          icon={filter === "failed" ? XCircle : CheckCircle2}
          title={emptyTitle}
          hint="Completed and failed jobs show up here once the worker finishes them."
        />
      ) : (
        <>
          <Panel className="overflow-hidden p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-slate-50 text-left text-xs uppercase tracking-wide text-faint">
                    <th className="px-4 py-3 font-medium">Filename</th>
                    <th className="px-4 py-3 font-medium">Subject</th>
                    <th className="px-4 py-3 font-medium">Segments</th>
                    <th className="px-4 py-3 font-medium">Time</th>
                    <th className="px-4 py-3 font-medium">Date</th>
                    <th className="px-4 py-3 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((h) => (
                    <tr
                      key={h.job_id}
                      onClick={() => onOpenVideo(h.video_id)}
                      className="cursor-pointer border-t border-line transition-colors hover:bg-sky-50/60"
                    >
                      <td className="max-w-[240px] truncate px-4 py-3 font-medium text-fg">
                        {h.video_filename ?? shortId(h.video_id)}
                      </td>
                      {h.status === "failed" ? (
                        <td colSpan={2} className="px-4 py-3 text-red-600">
                          {h.error ?? "processing failed"}
                        </td>
                      ) : (
                        <>
                          <td className="px-4 py-3 text-muted">{h.subject ?? "—"}</td>
                          <td className="num px-4 py-3 text-muted">{h.segment_count}</td>
                        </>
                      )}
                      <td className="num px-4 py-3 text-muted">{fmtDuration(h.processing_duration_sec)}</td>
                      <td className="num px-4 py-3 text-muted">{fmtDate(h.completed_at)}</td>
                      <td className="px-4 py-3">
                        {h.status === "failed" ? (
                          <span className="flex items-center gap-1 text-xs font-medium text-red-600">
                            <XCircle size={13} /> failed
                          </span>
                        ) : (
                          <Badge status="done" />
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          {pages > 1 && (
            <div className="flex items-center justify-center gap-3">
              <Button variant="ghost" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
                Prev
              </Button>
              <span className="num flex items-center gap-1 text-sm text-muted">
                <Clock size={13} /> {page} / {pages}
              </span>
              <Button variant="ghost" disabled={page >= pages} onClick={() => setPage((p) => Math.min(pages, p + 1))}>
                Next
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
