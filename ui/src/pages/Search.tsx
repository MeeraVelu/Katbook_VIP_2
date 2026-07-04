import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search as SearchIcon } from "lucide-react";
import type { SearchMode } from "@/lib/types";
import { useSearch } from "@/hooks/queries";
import { HitRow } from "@/components/HitRow";
import { Button, EmptyState, ErrorState, Panel, SkeletonRows, cx } from "@/components/primitives";

const MODES: SearchMode[] = ["semantic", "keyword", "hybrid"];

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
      <div>
        <h1 className="font-display text-2xl font-bold">Search</h1>
        <p className="text-sm text-muted">Semantic (pgvector), keyword (FTS), or hybrid (RRF) over every segment.</p>
      </div>

      <Panel className="space-y-3">
        <div className="flex items-center gap-2">
          <SearchIcon size={18} className="text-cyan" />
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
        <div className="flex gap-1 rounded-lg border border-line p-0.5 w-fit">
          {MODES.map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={cx(
                "rounded-md px-3 py-1 text-xs capitalize transition-colors",
                mode === m ? "bg-cyan/20 text-cyan" : "text-muted hover:text-fg",
              )}
            >
              {m}
            </button>
          ))}
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
          <div className="num px-3 py-1 text-xs text-faint">
            {data.count} results · mode {data.mode}
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
