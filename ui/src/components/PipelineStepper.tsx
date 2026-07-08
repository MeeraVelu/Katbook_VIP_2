import { Check, X } from "lucide-react";
import type { JobState } from "@/lib/types";
import { PIPELINE_STAGES, stageIndex } from "@/lib/viz";
import { cx } from "./primitives";

interface Props {
  state: JobState;
  currentStage: string | null;
  elapsedSec: number | null;
  stageTimings: Record<string, number>;
}

export function PipelineStepper({ state, currentStage, elapsedSec, stageTimings }: Props) {
  const done = state === "done";
  const failed = state === "failed";
  const activeIdx = done ? PIPELINE_STAGES.length : stageIndex(currentStage);

  return (
    <div className="flex w-full items-start gap-1 overflow-x-auto pb-2">
      {PIPELINE_STAGES.map((stage, i) => {
        const isDone = done || i < activeIdx;
        const isCurrent = !done && !failed && i === activeIdx;
        const isFailed = failed && i === activeIdx;
        const t = stageTimings[stage.key];

        return (
          <div key={stage.key} className="flex min-w-[84px] flex-1 flex-col items-center">
            <div className="flex w-full items-center">
              <span
                className={cx(
                  "h-px flex-1",
                  i === 0 ? "opacity-0" : isDone || isCurrent ? "bg-gradient-to-r from-accent to-cyan" : "bg-line",
                )}
              />
              <span
                className={cx(
                  "flex h-8 w-8 items-center justify-center rounded-full border text-xs transition-all duration-300",
                  isDone && "border-transparent bg-gradient-to-br from-accent to-cyan text-white shadow-panel",
                  isCurrent && "border-accent text-accent animate-pulse-accent",
                  isFailed && "border-bad bg-bad/10 text-bad",
                  !isDone && !isCurrent && !isFailed && "border-line bg-slate-50 text-faint",
                )}
              >
                {isDone ? <Check size={15} /> : isFailed ? <X size={15} /> : <span className="num">{i + 1}</span>}
              </span>
              <span
                className={cx(
                  "h-px flex-1",
                  i === PIPELINE_STAGES.length - 1
                    ? "opacity-0"
                    : i < activeIdx
                      ? "bg-gradient-to-r from-accent to-cyan"
                      : "bg-line",
                )}
              />
            </div>
            <div className={cx("mt-2 text-xs", isCurrent ? "font-semibold text-accent" : isDone ? "text-fg" : "text-faint")}>
              {stage.label}
            </div>
            <div className="num mt-0.5 h-4 text-[11px] text-muted">
              {isCurrent ? `${(elapsedSec ?? 0).toFixed(0)}s` : t != null ? `${t.toFixed(1)}s` : ""}
            </div>
          </div>
        );
      })}
    </div>
  );
}
