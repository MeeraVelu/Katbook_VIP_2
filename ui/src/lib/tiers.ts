// GPU-tier display, driven by the worker heartbeat surfaced on /ready.details
// (see pipeline/gpu_profile.py). The chip shows tier + device + VRAM.

export type Tier = "cpu" | "t4_16gb" | "rtx_high" | "rtx5090" | "datacenter";

interface TierMeta {
  label: string;
  tone: "cpu" | "mid" | "high" | "flagship" | "dc";
}

const TIERS: Record<Tier, TierMeta> = {
  cpu: { label: "CPU", tone: "cpu" },
  t4_16gb: { label: "T4", tone: "mid" },
  rtx_high: { label: "RTX", tone: "high" },
  rtx5090: { label: "RTX 5090", tone: "flagship" },
  datacenter: { label: "Datacenter", tone: "dc" },
};

export interface TierInfo {
  tier: Tier | null;
  device: string | null;
  vramGb: number | null;
}

export function tierMeta(tier: Tier | null): TierMeta {
  return (tier && TIERS[tier]) || { label: "Unknown", tone: "cpu" };
}

export function tierLabel(info: TierInfo): string {
  const meta = tierMeta(info.tier);
  const vram = info.vramGb ? ` · ${Math.round(info.vramGb)}GB` : "";
  return `${meta.label}${vram}`;
}

// Read the tier info out of a /ready details bag (the worker publishes gpu info).
export function readTier(details: Record<string, unknown> | undefined): TierInfo {
  const gpu = (details?.gpu ?? details) as Record<string, unknown> | undefined;
  const tier = (gpu?.tier ?? details?.tier) as Tier | undefined;
  const device = (gpu?.device ?? details?.device) as string | undefined;
  const vram = (gpu?.vram_gb ?? details?.vram_gb) as number | undefined;
  return {
    tier: tier ?? null,
    device: device ?? null,
    vramGb: typeof vram === "number" ? vram : null,
  };
}
