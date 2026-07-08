import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import {
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Filter,
  GraduationCap,
  Globe2,
  Library as LibraryIcon,
  SlidersHorizontal,
  Upload,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useFacets, useVideos } from "@/hooks/queries";
import type { VideoFilters, VideoStatus } from "@/lib/types";
import { fileName, fmtClock, fmtDate } from "@/lib/format";
import { Badge, Button, EmptyState, ErrorState, IconBadge, Panel, SkeletonRows, cx } from "@/components/primitives";

const PAGE_SIZE = 20;

export function Library() {
  const nav = useNavigate();
  const [page, setPage] = useState(1);
  const [draft, setDraft] = useState<VideoFilters>({});
  const [filters, setFilters] = useState<VideoFilters>({});
  const { data, isLoading, isError, error, refetch, isFetching } = useVideos(page, PAGE_SIZE, filters);
  const { data: facets } = useFacets();

  function apply() {
    setPage(1);
    setFilters(draft);
  }
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-4">
        <div className="flex items-center gap-3">
          <IconBadge icon={LibraryIcon} tone="accent" size={40} />
          <div>
            <h1 className="font-display text-2xl font-bold">Library</h1>
            <p className="text-sm text-muted">
              {data ? <span className="num text-fg">{data.total}</span> : "…"} processed videos
            </p>
          </div>
        </div>
        <Button onClick={() => nav("/ingest")}>
          <Upload size={15} /> Ingest
        </Button>
      </div>

      {/* filters */}
      <Panel className="space-y-3">
        <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-faint">
          <Filter size={13} /> Filters
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <FInput
            icon={BookOpen}
            placeholder="subject"
            v={draft.subject}
            on={(v) => setDraft({ ...draft, subject: v })}
            options={facets?.subjects}
          />
          <FInput
            icon={GraduationCap}
            placeholder="grade"
            v={draft.grade_level}
            on={(v) => setDraft({ ...draft, grade_level: v })}
            options={facets?.grades}
          />
          <FInput
            icon={Globe2}
            placeholder="language"
            v={draft.language}
            on={(v) => setDraft({ ...draft, language: v })}
            options={facets?.languages}
          />

          <span aria-hidden className="mx-1 h-6 w-px shrink-0 bg-line" />

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

          <Button onClick={apply} className="shrink-0">
            <SlidersHorizontal size={14} /> Apply
          </Button>
          {isFetching && <span className="num shrink-0 text-xs text-faint">updating…</span>}
        </div>
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
                <tr className="bg-slate-50 text-left text-xs uppercase tracking-wide text-faint">
                  <th className="px-4 py-3 font-medium">Source</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Path</th>
                  <th className="px-4 py-3 font-medium">Lang</th>
                  <th className="px-4 py-3 font-medium">Duration</th>
                  <th className="px-4 py-3 font-medium">Segments</th>
                  <th className="px-4 py-3 font-medium">Created</th>
                </tr>
              </thead>
              {/* gradient-fade divider separating the header from rows */}
              <tbody>
                <tr aria-hidden>
                  <td colSpan={7} className="p-0">
                    <div className="divider-fade" />
                  </td>
                </tr>
                {data.items.map((v) => (
                  <tr
                    key={v.video_id}
                    onClick={() => nav(`/videos/${v.video_id}`)}
                    className="group scale-100 cursor-pointer border-b border-line transition-all duration-200 ease-out last:border-b-0 hover:scale-[1.004] hover:bg-sky-50"
                  >
                    <td className="max-w-[280px] truncate px-4 py-3 font-medium text-fg group-hover:text-accent" title={v.source_path}>
                      {fileName(v.source_path)}
                      {v.is_duplicate && <span className="ml-2 text-[11px] font-normal text-faint">↳ dup</span>}
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
          <span className="num rounded-full border border-line bg-slate-50 px-3.5 py-1.5 text-sm text-muted">
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
          <span
            key={i}
            className="w-[3px] rounded-sm bg-gradient-to-t from-accent/40 to-accent-soft/80"
            style={{ height: `${40 + ((i * 37) % 60)}%` }}
          />
        ))}
      </div>
      <span className="num text-xs text-muted">{count}</span>
    </div>
  );
}

// Custom-styled autocomplete — NOT a native <datalist>. Datalist popups are
// rendered by the OS/browser and can't be styled with CSS at all (a real
// platform limitation, not a bug we can fix with a class name), so on a page
// that follows the light theme it can still render with dark/mismatched
// native chrome. This dropdown is plain React state, fully on-brand.
//
// The dropdown is portaled straight to document.body (not rendered inline).
// Every Panel uses `overflow-hidden` (needed to clip the top accent-edge and
// the results table to its rounded corners) — an inline absolutely-positioned
// popover living INSIDE a Panel gets silently clipped to that box, which is
// why it only ever showed a sliver at the panel's bottom edge. Portaling +
// `position: fixed` with real getBoundingClientRect() coordinates escapes
// that clipping entirely, which is the standard fix for "popover trapped
// inside a clipped/scrollable ancestor."
function FInput({
  icon: Icon,
  placeholder,
  v,
  on,
  options,
}: {
  icon: LucideIcon;
  placeholder: string;
  v?: string;
  on: (v: string) => void;
  options?: string[];
}) {
  const [open, setOpen] = useState(false);
  const [rect, setRect] = useState<{ top: number; left: number; width: number } | null>(null);
  // fixed width + shrink-0: a bare block <div> as a flex child otherwise has no
  // intrinsic size cue and was stretching to fill the row, forcing every filter
  // onto its own line instead of sitting side by side.
  const wrapRef = useRef<HTMLDivElement>(null);

  function openDropdown() {
    const r = wrapRef.current?.getBoundingClientRect();
    if (r) setRect({ top: r.bottom + 6, left: r.left, width: Math.max(r.width, 190) });
    setOpen(true);
  }

  useEffect(() => {
    if (!open) return;
    function onDocMouseDown(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    }
    // scrolling/resizing invalidates the captured rect — close rather than show a stale popover
    function onScrollOrResize() {
      setOpen(false);
    }
    document.addEventListener("mousedown", onDocMouseDown);
    window.addEventListener("scroll", onScrollOrResize, true);
    window.addEventListener("resize", onScrollOrResize);
    return () => {
      document.removeEventListener("mousedown", onDocMouseDown);
      window.removeEventListener("scroll", onScrollOrResize, true);
      window.removeEventListener("resize", onScrollOrResize);
    };
  }, [open]);

  const query = (v ?? "").trim().toLowerCase();
  const suggestions = (options ?? []).filter((o) => !query || o.toLowerCase().includes(query)).slice(0, 8);

  return (
    <div ref={wrapRef} className="relative w-36 shrink-0">
      <Icon size={13} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
      <input
        value={v ?? ""}
        onChange={(e) => {
          on(e.target.value);
          openDropdown();
        }}
        onFocus={openDropdown}
        placeholder={placeholder}
        autoComplete="off"
        className="w-full rounded-full border border-line bg-slate-50 py-1.5 pl-8 pr-3 text-sm text-fg outline-none transition-colors focus:border-accent/50 focus:bg-white focus:ring-1 focus:ring-accent/30"
      />
      {open &&
        suggestions.length > 0 &&
        rect &&
        createPortal(
          <div
            style={{ position: "fixed", top: rect.top, left: rect.left, width: rect.width }}
            className="z-50 overflow-hidden rounded-xl border border-line bg-white py-1 shadow-glow"
          >
            {suggestions.map((o) => (
              <button
                key={o}
                type="button"
                // fires before the input's onBlur/document mousedown-close, so the click registers
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  on(o);
                  setOpen(false);
                }}
                className="block w-full truncate px-3 py-1.5 text-left text-sm text-fg transition-colors hover:bg-sky-50 hover:text-accent"
              >
                {o}
              </button>
            ))}
          </div>,
          document.body,
        )}
    </div>
  );
}

function FSelect({ v, on, opts }: { v: string; on: (v: string) => void; opts: [string, string][] }) {
  return (
    <select
      value={v}
      onChange={(e) => on(e.target.value)}
      className={cx(
        "shrink-0 rounded-full border border-line bg-slate-50 px-3.5 py-1.5 text-sm text-fg outline-none transition-colors focus:border-accent/50 focus:bg-white",
      )}
    >
      {opts.map(([val, label]) => (
        <option key={val} value={val}>
          {label}
        </option>
      ))}
    </select>
  );
}
