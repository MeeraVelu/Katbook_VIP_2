import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search as SearchIcon, CornerDownLeft } from "lucide-react";
import type { SearchMode } from "@/lib/types";
import { useSearch } from "@/hooks/queries";
import { HitRow } from "./HitRow";
import { cx } from "./primitives";

const MODES: SearchMode[] = ["semantic", "keyword", "hybrid"];

// Press "/" anywhere → overlay search with a mode toggle and fused-score bars.
// Enter deep-links to the segment (video detail, scrolled to the segment).
export function CommandBar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [mode, setMode] = useState<SearchMode>("semantic");
  const [sel, setSel] = useState(0);
  const navigate = useNavigate();

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 220);
    return () => clearTimeout(t);
  }, [q]);

  const { data, isFetching } = useSearch(debounced, mode, 8, open);
  const results = useMemo(() => data?.results ?? [], [data]);
  const maxScore = results.reduce((m, r) => Math.max(m, r.score), 0);

  useEffect(() => setSel(0), [debounced, mode, results.length]);

  function go(i: number) {
    const hit = results[i];
    if (!hit) return;
    onClose();
    navigate(`/videos/${hit.video_id}#seg-${hit.seg_index}`);
  }

  function onKey(e: React.KeyboardEvent) {
    if (e.key === "Escape") onClose();
    else if (e.key === "ArrowDown") {
      e.preventDefault();
      setSel((s) => Math.min(s + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSel((s) => Math.max(s - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      go(sel);
    }
  }

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-slate-900/30 px-4 pt-[12vh] backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl overflow-hidden rounded-2xl border border-line bg-white shadow-glow"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={onKey}
      >
        <div className="p-3">
          <div className="flex items-center gap-3 rounded-full border border-line bg-slate-50 px-4 py-2.5 transition-colors focus-within:border-accent/50 focus-within:shadow-[0_0_0_3px_rgba(14,165,233,0.15)]">
            <SearchIcon size={18} className="shrink-0 text-cyan" />
            {/* eslint-disable-next-line jsx-a11y/no-autofocus */}
            <input
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search segments by meaning or keyword…"
              className="flex-1 bg-transparent text-sm text-fg outline-none placeholder:text-faint"
            />
            <div className="flex gap-1 rounded-full border border-line bg-white p-0.5">
              {MODES.map((m) => (
                <button
                  key={m}
                  onClick={() => setMode(m)}
                  className={cx(
                    "rounded-full px-2.5 py-1 text-[11px] capitalize transition-all",
                    mode === m ? "bg-sky-100 text-sky-700 font-medium shadow-sm" : "text-muted hover:text-fg",
                  )}
                >
                  {m}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="max-h-[52vh] overflow-y-auto p-2">
          {debounced.trim() === "" ? (
            <div className="px-3 py-8 text-center text-sm text-faint">Type to search across every processed segment.</div>
          ) : isFetching ? (
            <div className="px-3 py-8 text-center text-sm text-muted">Searching…</div>
          ) : results.length === 0 ? (
            <div className="px-3 py-8 text-center text-sm text-faint">No matches for “{debounced}”.</div>
          ) : (
            <div className="space-y-1">
              {results.map((hit, i) => (
                <HitRow
                  key={`${hit.video_id}-${hit.seg_index}`}
                  hit={hit}
                  maxScore={maxScore}
                  mode={data?.mode ?? mode}
                  selected={i === sel}
                  onClick={() => go(i)}
                />
              ))}
            </div>
          )}
        </div>

        <div className="divider-fade" />
        <div className="flex items-center justify-between px-4 py-2.5 text-[11px] text-faint">
          <span className="flex items-center gap-1">
            <CornerDownLeft size={12} /> open · ↑↓ navigate · esc close
          </span>
          <span className="num">{data ? `${data.count} results · ${data.mode}` : ""}</span>
        </div>
      </div>
    </div>
  );
}
