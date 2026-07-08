import { Cpu } from "lucide-react";
import { useReady } from "@/hooks/queries";
import { readTier, tierLabel, tierMeta } from "@/lib/tiers";
import { cx } from "./primitives";

const TONE: Record<string, string> = {
  cpu: "text-faint border-line bg-slate-50",
  mid: "text-cyan-700 border-cyan-200 bg-cyan-50",
  high: "text-sky-700 border-sky-200 bg-sky-50",
  flagship: "text-sky-700 bg-sky-100 border-sky-300 shadow-panel font-semibold",
  dc: "text-cyan-700 border-cyan-200 bg-cyan-50",
};

export function GpuTierChip() {
  const { data } = useReady();
  const info = readTier(data?.details);
  const meta = tierMeta(info.tier);
  const title = info.device ? `${info.device}${info.vramGb ? ` · ${Math.round(info.vramGb)} GB VRAM` : ""}` : "worker GPU tier";

  return (
    <div
      title={title}
      className={cx(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 transition-colors",
        TONE[meta.tone] ?? TONE.cpu,
      )}
    >
      <Cpu size={13} strokeWidth={2} />
      <span className="num text-xs font-medium tracking-tight">{tierLabel(info)}</span>
    </div>
  );
}
