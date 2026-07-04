import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronLeft, ChevronRight, Filter, Upload } from "lucide-react";
import { useVideos } from "@/hooks/queries";
import type { VideoFilters, VideoStatus } from "@/lib/types";
import { fileName, fmtClock, fmtDate } from "@/lib/format";
import { Badge, Button, EmptyState, ErrorState, Panel, SkeletonRows, cx } from "@/components/primitives";

const PAGE_SIZE = 20;

export function Library() {
  const nav = useNavigate();
  const [page, setPage] = useState(1);
  const [draft, setDraft] = useState<VideoFilters>({});
  const [filters, setFilters] = useState<VideoFilters>({});
  const { data, isLoading, isError, error, refetch, isFetching } = useVideos(page, PAGE_SIZE, filters);

  function apply() {
    setPage(1);
    setFilters(draft);
  }
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-bold">Library</h1>
          <p className="text-sm text-muted">
            {data ? <span className="num">{data.total}</span> : "…"} processed videos
          </p>
        </div>
        <Button onClick={() => nav("/ingest")}>
          <Upload size={15} /> Ingest
        </Button>
      </div>

      {/* filters */}
      <Panel className="flex flex-wrap items-center gap-2">
        <Filter size={15} className="text-faint" />
        <FInput placeholder="subject" v={draft.subject} on={(v) => setDraft({ ...draft, subject: v })} />
        <FInput placeholder="grade" v={draft.grade_level} on={(v) => setDraft({ ...draft, grade_level: v })} />
        <FInput placeholder="language" v={draft.language} on={(v) => setDraft({ ...draft, language: v })} />
        <FSelect
          v={draft.has_speech === undefined ? "" : String(draft.has_speech)}
          on={(v) => setDraft({ ...draft, has_speech: v === "" ? undefined : v === "true" })}
          opts={[["", "path: any"], ["true", "voice"], ["false", "silent"]]}
        />
        <FSelect
          v={draft.status ?? ""}
          on={(v) => setDraft({ ...draft, status: (v || undefined) as VideoStatus | undefined })}
          opts={[["", "status: any"], ["queued", "queued"], ["processing", "processing"], ["done", "done"], ["failed", "failed"], ["soft_deleted", "soft-deleted"]]}
        />
        <Button variant="ghost" onClick={apply}>
          Apply
        </Button>
        {isFetching && <span className="num text-xs text-faint">updating…</span>}
      </Panel>

      {isLoading ? (
        <SkeletonRows rows={8} />
      ) : isError ? (
        <ErrorState message={(error as Error).message} onRetry={() => refetch()} />
      ) : !data || data.items.length === 0 ? (
        <EmptyState
          title="No videos yet"
          hint="Register a server path, upload a file, or enqueue a folder to start processing."
          action={
            <Button onClick={() => nav("/ingest")}>
              <Upload size={15} /> Ingest a video
            </Button>
          }
        />
      ) : (
        <Panel className="overflow-hidden p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-faint">
                  <th className="px-4 py-3 font-medium">Source</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Path</th>
                  <th className="px-4 py-3 font-medium">Lang</th>
                  <th className="px-4 py-3 font-medium">Duration</th>
                  <th className="px-4 py-3 font-medium">Segments</th>
                  <th className="px-4 py-3 font-medium">Created</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((v) => (
                  <tr
                    key={v.video_id}
                    onClick={() => nav(`/videos/${v.video_id}`)}
                    className="cursor-pointer border-b border-line/60 transition-colors hover:bg-panel2"
                  >
                    <td className="max-w-[280px] truncate px-4 py-3" title={v.source_path}>
                      {fileName(v.source_path)}
                      {v.is_duplicate && <span className="ml-2 text-[11px] text-faint">↳ dup</span>}
                    </td>
                    <td className="px-4 py-3"><Badge status={v.status} /></td>
                    <td className="px-4 py-3 text-muted">{v.tagging_path ?? "—"}</td>
                    <td className="num px-4 py-3 text-muted">{v.language ?? "—"}</td>
                    <td className="num px-4 py-3">{fmtClock(v.duration_sec)}</td>
                    <td className="px-4 py-3">
                      <SegDensity count={v.segment_count} />
                    </td>
                    <td className="num px-4 py-3 text-muted">{fmtDate(v.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {data && pages > 1 && (
        <div className="flex items-center justify-center gap-3">
          <Button variant="ghost" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}>
            <ChevronLeft size={15} /> Prev
          </Button>
          <span className="num text-sm text-muted">
            {page} / {pages}
          </span>
          <Button variant="ghost" onClick={() => setPage((p) => Math.min(pages, p + 1))} disabled={page >= pages}>
            Next <ChevronRight size={15} />
          </Button>
        </div>
      )}
    </div>
  );
}

// compact segment-density sparkline (list endpoint returns count, not full segments)
function SegDensity({ count }: { count: number }) {
  const n = Math.min(count, 14);
  return (
    <div className="flex items-center gap-2">
      <div className="flex h-4 items-end gap-[2px]">
        {Array.from({ length: n }).map((_, i) => (
          <span key={i} className="w-[3px] rounded-sm bg-accent/50" style={{ height: `${40 + ((i * 37) % 60)}%` }} />
        ))}
      </div>
      <span className="num text-xs text-muted">{count}</span>
    </div>
  );
}

function FInput({ placeholder, v, on }: { placeholder: string; v?: string; on: (v: string) => void }) {
  return (
    <input
      value={v ?? ""}
      onChange={(e) => on(e.target.value)}
      placeholder={placeholder}
      className="w-28 rounded-lg border border-line bg-panel2 px-2.5 py-1.5 text-sm outline-none focus:border-accent"
    />
  );
}

function FSelect({ v, on, opts }: { v: string; on: (v: string) => void; opts: [string, string][] }) {
  return (
    <select
      value={v}
      onChange={(e) => on(e.target.value)}
      className={cx("rounded-lg border border-line bg-panel2 px-2.5 py-1.5 text-sm text-fg outline-none focus:border-accent")}
    >
      {opts.map(([val, label]) => (
        <option key={val} value={val} className="bg-panel">
          {label}
        </option>
      ))}
    </select>
  );
}
