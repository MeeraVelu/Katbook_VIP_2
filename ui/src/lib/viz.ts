// Shared visualization constants: subject color scale + the pipeline stage order
// used by SegmentTimeline and PipelineStepper.

// Categorical, dark-friendly palette for subject blocks (distinct from the amber
// accent / green-ok / red-bad / cyan-search reserved meanings).
const SUBJECT_PALETTE = [
  "#6EA8FE", // blue
  "#A78BFA", // violet
  "#F0A5C0", // pink
  "#7DD3A8", // sage
  "#E6B450", // gold
  "#5EC8C8", // teal
  "#C4A484", // tan
  "#9AA7FF", // periwinkle
];

export function subjectColor(subject: string | null | undefined): string {
  if (!subject) return "#3A4453"; // muted slab for untagged
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
