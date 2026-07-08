// Shared visualization constants: subject color scale + the pipeline stage order
// used by SegmentTimeline and PipelineStepper.

// Categorical palette for subject blocks, tuned for legibility on WHITE (600-ish
// shades read as text; distinct from the sky-blue accent / green-ok / red-bad).
const SUBJECT_PALETTE = [
  "#7C3AED", // violet
  "#DB2777", // pink
  "#D97706", // amber
  "#EA580C", // orange
  "#0D9488", // teal
  "#4F46E5", // indigo
  "#92400E", // brown/tan
  "#475569", // slate
];

export function subjectColor(subject: string | null | undefined): string {
  if (!subject) return "#94A3B8"; // muted slab for untagged
  let h = 0;
  for (let i = 0; i < subject.length; i++) h = (h * 31 + subject.charCodeAt(i)) >>> 0;
  return SUBJECT_PALETTE[h % SUBJECT_PALETTE.length];
}

export interface Stage {
  key: string;
  label: string;
}

// Order + labels for the worker's per-stage progress (pipeline.process_one_video
// reports these via the `progress` callback; job.current_stage matches a key).
export const PIPELINE_STAGES: Stage[] = [
  { key: "ingest_audio", label: "Ingest" },
  { key: "route", label: "Route" },
  { key: "extract_frames", label: "Frames" },
  { key: "visual", label: "Visual" },
  { key: "segmentation", label: "Segment" },
  { key: "llm", label: "Tag" },
  { key: "store", label: "Store" },
];

export function stageIndex(current: string | null): number {
  if (!current) return -1;
  if (current === "done" || current === "store") return PIPELINE_STAGES.length; // all done
  if (current === "start") return 0;
  const i = PIPELINE_STAGES.findIndex((s) => s.key === current);
  return i;
}
