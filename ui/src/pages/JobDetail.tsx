import { useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, FileVideo } from "lucide-react";
import { useJob } from "@/hooks/queries";
import { rememberJob } from "@/lib/recents";
import { fmtDate, shortId } from "@/lib/format";
import { PipelineStepper } from "@/components/PipelineStepper";
import { Badge, Button, ErrorState, Panel, Skeleton, cx } from "@/components/primitives";

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

      <Panel className="space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="font-display text-xl font-bold">Job</h1>
              <Badge status={job.state} />
              {live && <span className="num text-xs text-accent">● live</span>}
            </div>
            <div className="num mt-1 text-xs text-faint">{job.job_id}</div>
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

        <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm sm:grid-cols-4">
          <Meta k="Current stage" val={job.current_stage ?? "—"} />
          <Meta k="Attempts" val={String(job.attempts)} mono />
          <Meta k="Elapsed" val={job.elapsed_sec != null ? `${job.elapsed_sec}s` : "—"} mono />
          <Meta k="Video" val={shortId(job.video_id)} mono />
          <Meta k="Enqueued" val={fmtDate(job.enqueued_at)} mono />
          <Meta k="Started" val={fmtDate(job.started_at)} mono />
          <Meta k="Finished" val={fmtDate(job.finished_at)} mono />
        </div>

        {job.error && <div className="rounded-xl border border-bad/30 bg-bad/5 px-3 py-2 text-sm text-bad">{job.error}</div>}
      </Panel>
    </div>
  );
}

function Meta({ k, val, mono }: { k: string; val: string; mono?: boolean }) {
  return (
    <div>
      <div className="text-xs text-faint">{k}</div>
      <div className={cx("truncate", mono && "num")}>{val}</div>
    </div>
  );
}
