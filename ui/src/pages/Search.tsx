import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Hash, Layers, Search as SearchIcon, Sparkles } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { SearchMode } from "@/lib/types";
import { useSearch } from "@/hooks/queries";
import { HitRow } from "@/components/HitRow";
import { Button, EmptyState, ErrorState, IconBadge, Panel, SkeletonRows, cx } from "@/components/primitives";

const MODES: SearchMode[] = ["semantic", "keyword", "hybrid"];
const MODE_ICON: Record<SearchMode, LucideIcon> = { semantic: Sparkles, keyword: Hash, hybrid: Layers };

export function Search() {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [mode, setMode] = useState<SearchMode>("semantic");
  const [limit] = useState(25);
  const [submitted, setSubmitted] = useState("");
  const { data, isFetching, isError, error } = useSearch(submitted, mode, limit, submitted !== "");
  const maxScore = (data?.results ?? []).reduce((m, r) => Math.max(m, r.score), 0);

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <IconBadge icon={SearchIcon} tone="cyan" size={40} />
        <div>
          <h1 className="font-display text-2xl font-bold">Search</h1>
          <p className="text-sm text-muted">Semantic (pgvector), keyword (FTS), or hybrid (RRF) over every segment.</p>
        </div>
      </div>

      <Panel glow="cyan" className="space-y-3">
        {/* light pill search bar with sky-blue border glow on focus */}
        <div className="flex items-center gap-3 rounded-full border border-line bg-slate-50 px-4 py-2.5 transition-all focus-within:border-cyan/50 focus-within:bg-white focus-within:shadow-[0_0_0_3px_rgba(6,182,212,0.15)]">
          <SearchIcon size={18} className="shrink-0 text-cyan-600" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && setSubmitted(q)}
            placeholder="e.g. time period of a pendulum"
            className="flex-1 bg-transparent text-base outline-none placeholder:text-faint"
          />
          <Button variant="cyan" onClick={() => setSubmitted(q)}>
            Search
          </Button>
        </div>
        <div className="flex w-fit gap-1 rounded-full border border-line bg-slate-50 p-0.5">
          {MODES.map((m) => {
            const Icon = MODE_ICON[m];
            return (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={cx(
                  "flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs capitalize transition-all duration-200",
                  mode === m ? "bg-cyan-100 text-cyan-700 font-medium shadow-sm" : "text-muted hover:text-fg",
                )}
              >
                <Icon size={13} /> {m}
              </button>
            );
          })}
        </div>
      </Panel>

      {submitted === "" ? (
        <EmptyState icon={SearchIcon} title="Search your library" hint="Results link straight to the matching segment." />
      ) : isFetching ? (
        <SkeletonRows rows={6} />
      ) : isError ? (
        <ErrorState message={(error as Error).message} />
      ) : !data || data.results.length === 0 ? (
        <EmptyState icon={SearchIcon} title="No matches" hint={`Nothing found for “${submitted}”. Try another mode or query.`} />
      ) : (
        <Panel className="space-y-1 p-2">
          <div className="flex items-center gap-2 px-3 py-1.5 text-xs text-faint">
            <span className="num text-fg">{data.count}</span> results
            <span className="rounded-full border border-cyan-200 bg-cyan-50 px-2 py-0.5 text-[10px] uppercase tracking-wide text-cyan-700">
              {data.mode}
            </span>
          </div>
          {data.results.map((hit) => (
            <HitRow
              key={`${hit.video_id}-${hit.seg_index}`}
              hit={hit}
              maxScore={maxScore}
              mode={data.mode}
              onClick={() => nav(`/videos/${hit.video_id}#seg-${hit.seg_index}`)}
            />
          ))}
        </Panel>
      )}
    </div>
  );
}
