import { useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, CalendarClock, FileVideo, Flag, Hourglass, PlayCircle, Repeat } from "lucide-react";
import { useJob } from "@/hooks/queries";
import { rememberJob } from "@/lib/recents";
import { fmtDate, shortId } from "@/lib/format";
import { PipelineStepper } from "@/components/PipelineStepper";
import { Badge, Button, ErrorState, IconBadge, Panel, Skeleton, StatTile } from "@/components/primitives";

export function JobDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const { data: job, isLoading, isError, error, refetch } = useJob(id);

  useEffect(() => {
    if (id) rememberJob(id);
  }, [id]);

  if (isLoading) return <Skeleton className="h-48 w-full" />;
  if (isError) return <ErrorState message={(error as Error).message} onRetry={() => refetch()} />;
  if (!job) return null;

  const live = job.state === "processing" || job.state === "queued";

  return (
    <div className="space-y-5">
      <button onClick={() => nav("/jobs")} className="flex items-center gap-1 text-sm text-muted hover:text-fg">
        <ArrowLeft size={15} /> Jobs
      </button>

      <Panel glow="accent" className="space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <IconBadge icon={Flag} tone={job.state === "failed" ? "bad" : job.state === "done" ? "ok" : "accent"} size={40} />
            <div>
              <div className="flex items-center gap-2">
                <h1 className="font-display text-xl font-bold">Job</h1>
                <Badge status={job.state} />
                {live && (
                  <span className="num flex items-center gap-1 text-xs text-accent">
                    <span className="h-1.5 w-1.5 rounded-full bg-accent animate-pulse-accent" /> live
                  </span>
                )}
              </div>
              <div className="num mt-1 text-xs text-faint">{job.job_id}</div>
            </div>
          </div>
          {job.video_id && (
            <Button variant="ghost" onClick={() => nav(`/videos/${job.video_id}`)}>
              <FileVideo size={15} /> View video
            </Button>
          )}
        </div>

        {/* hero: pipeline stepper */}
        <PipelineStepper
          state={job.state}
          currentStage={job.current_stage}
          elapsedSec={job.elapsed_sec}
          stageTimings={job.stage_timings}
        />

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <StatTile icon={PlayCircle} label="Current stage" value={job.current_stage ?? "—"} tone="accent" />
          <StatTile icon={Repeat} label="Attempts" value={job.attempts} tone="muted" mono />
          <StatTile icon={Hourglass} label="Elapsed" value={job.elapsed_sec != null ? `${job.elapsed_sec}s` : "—"} tone="cyan" mono />
          <StatTile icon={FileVideo} label="Video" value={shortId(job.video_id)} tone="muted" mono />
          <StatTile icon={CalendarClock} label="Enqueued" value={fmtDate(job.enqueued_at)} tone="muted" mono />
          <StatTile icon={CalendarClock} label="Started" value={fmtDate(job.started_at)} tone="muted" mono />
          <StatTile icon={CalendarClock} label="Finished" value={fmtDate(job.finished_at)} tone="muted" mono />
        </div>

        {job.error && <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{job.error}</div>}
      </Panel>
    </div>
  );
}
