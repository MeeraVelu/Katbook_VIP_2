import { Cpu } from "lucide-react";
import { useReady } from "@/hooks/queries";
import { readTier, tierLabel, tierMeta } from "@/lib/tiers";
import { cx } from "./primitives";

const TONE: Record<string, string> = {
  cpu: "text-faint border-line",
  mid: "text-cyan border-cyan/30",
  high: "text-accent-soft border-accent/30",
  flagship: "text-accent border-accent/50 shadow-glow",
  dc: "text-cyan border-cyan/40",
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
        "inline-flex items-center gap-1.5 rounded-lg border bg-panel px-2.5 py-1",
        TONE[meta.tone] ?? TONE.cpu,
      )}
    >
      <Cpu size={13} strokeWidth={2} />
      <span className="num text-xs font-medium tracking-tight">{tierLabel(info)}</span>
    </div>
  );
}
