// Mirrors the backend Pydantic schemas 1:1 (api/schemas/*.py). Keep in sync.

export type VideoStatus =
  | "queued"
  | "processing"
  | "done"
  | "failed"
  | "soft_deleted";

export type JobState = "queued" | "processing" | "done" | "failed";

export type SearchMode = "semantic" | "keyword" | "hybrid";

export interface DedupVerdict {
  is_duplicate: boolean;
  canonical_video_id: string | null;
  content_hash: string | null;
  reason: string;
}

export interface RegisterVideoRequest {
  source_path: string;
  force?: boolean;
}

export interface RegisterVideoResponse {
  job_id: string | null;
  video_id: string;
  status: string; // queued | duplicate | exists
  dedup: DedupVerdict;
  message: string;
}

export interface BatchRequest {
  glob?: string | null;
  folder?: string | null;
  force?: boolean;
}

export interface BatchItem {
  source_path: string;
  video_id: string;
  job_id: string | null;
  status: string;
  is_duplicate: boolean;
}

export interface BatchResponse {
  enqueued: number;
  duplicates: number;
  skipped_existing: number;
  total: number;
  items: BatchItem[];
}

export interface SegmentOut {
  seg_index: number;
  start_sec: number;
  end_sec: number;
  topic: string | null;
  subject: string | null;
  grade_level: string | null;
  difficulty: string | null;
  content_type: string | null;
  tags: string[];
  subtopics: string[];
  summary: string | null;
  confidence: number | null;
  transcript_text: string | null;
  ocr: string | null;
  scenes: string[];
  objects: string[];
  captions: string[];
}

export interface VideoSummary {
  video_id: string;
  source_path: string;
  status: VideoStatus;
  language: string | null;
  has_speech: boolean | null;
  tagging_path: string | null;
  duration_sec: number | null;
  file_size_bytes: number | null;
  is_duplicate: boolean;
  canonical_video_id: string | null;
  segment_count: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface VideoRollup {
  subject: string | null;
  grade: string | null;
  difficulty: string | null;
  primary_topic: string | null;
  topics: string[];
  all_tags: string[];
}

export interface VideoDetail extends VideoSummary {
  content_hash: string | null;
  error_message: string | null;
  stage_timings: Record<string, number>;
  runtime: Record<string, unknown>;
  rollup: VideoRollup;
  segments: SegmentOut[];
}

export interface SoftDeleteResponse {
  video_id: string;
  status: string;
  message: string;
}

export interface FacetsResponse {
  subjects: string[];
  grades: string[];
  languages: string[];
}

export interface JobStatus {
  job_id: string;
  video_id: string | null;
  state: JobState;
  current_stage: string | null;
  attempts: number;
  stage_timings: Record<string, number>;
  error: string | null;
  enqueued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  elapsed_sec: number | null;
}

export interface SearchHit {
  video_id: string;
  seg_index: number;
  start_sec: number;
  end_sec: number;
  topic: string | null;
  subject: string | null;
  grade_level: string | null;
  summary: string | null;
  score: number;
}

export interface SearchResponse {
  query: string;
  mode: SearchMode;
  count: number;
  results: SearchHit[];
}

export interface Page<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}

export interface HealthResponse {
  status: string;
  version: string;
}

export interface ReadyResponse {
  ready: boolean;
  checks: Record<string, boolean>;
  details: Record<string, unknown>;
}

export interface ErrorEnvelope {
  code: string;
  message: string;
  request_id: string | null;
  details: Record<string, unknown> | null;
}

export interface VideoFilters {
  subject?: string;
  grade_level?: string;
  language?: string;
  has_speech?: boolean;
  status?: VideoStatus;
  include_deleted?: boolean;
}
