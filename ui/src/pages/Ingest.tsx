import { useState } from "react";
import type { DragEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  FileVideo,
  FolderGit2,
  HardDriveUpload,
  Loader2,
  Upload,
  UploadCloud,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useBatch, useRegisterVideo, useUploadVideo } from "@/hooks/queries";
import type { RegisterVideoResponse, DuplicateDetails } from "@/lib/types";
import { ApiError } from "@/lib/api";
import { fmtBytes } from "@/lib/format";
import { Button, IconBadge, Panel, cx } from "@/components/primitives";

export function Ingest() {
  const nav = useNavigate();

  function handleRegister(res: RegisterVideoResponse) {
    nav(`/jobs/${res.job_id}`);
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <IconBadge icon={Upload} tone="accent" size={40} />
        <div>
          <h1 className="font-display text-2xl font-bold">Ingest</h1>
          <p className="text-sm text-muted">
            Register a server path, upload a file, or enqueue a whole folder. Each runs the SHA-256 dedup pre-check before queueing.
          </p>
        </div>
      </div>

      <div className="grid items-stretch gap-4 md:grid-cols-2 xl:grid-cols-3">
        <RegisterPath onDone={handleRegister} />
        <UploadFile onDone={handleRegister} />
        <BatchEnqueue onDone={() => nav("/jobs")} />
      </div>
    </div>
  );
}

function CardShell({
  icon,
  title,
  hint,
  children,
}: {
  icon: LucideIcon;
  title: string;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <Panel hover glow="accent" className="flex h-full flex-col gap-4 p-5">
      <div className="flex items-start gap-3">
        <IconBadge icon={icon} tone="accent" size={36} />
        <div className="min-w-0 pt-0.5">
          <h3 className="font-display text-base font-semibold text-fg">{title}</h3>
          <p className="mt-0.5 text-xs leading-relaxed text-muted">{hint}</p>
        </div>
      </div>
      <div className="flex flex-1 flex-col gap-3">{children}</div>
    </Panel>
  );
}

const inputCls =
  "w-full rounded-xl border border-line bg-slate-50 px-3.5 py-2.5 text-sm outline-none transition-colors placeholder:text-faint/70 focus:border-accent/50 focus:bg-white focus:ring-1 focus:ring-accent/30";
const captionCls = "text-[11px] leading-relaxed text-faint";

// Renders the 409 "duplicate" response as a yellow warning with a link to the
// existing video; any other error falls back to the plain red message.
function MutationError({ error }: { error: unknown }) {
  if (!error) return null;
  if (error instanceof ApiError && error.code === "duplicate" && error.details) {
    const d = error.details as unknown as DuplicateDetails;
    return (
      <Panel className="flex items-start gap-2.5 border-amber-200 bg-amber-50 p-3 text-xs">
        <AlertTriangle size={16} className="mt-0.5 shrink-0 text-amber-600" />
        <div className="space-y-1">
          <p className="text-fg">{error.message}</p>
          <Link to={`/videos/${d.existing_video_id}`} className="font-medium text-accent hover:underline">
            View existing video ({d.existing_segment_count} segment{d.existing_segment_count === 1 ? "" : "s"}
            {d.processed_at ? `, processed ${new Date(d.processed_at).toLocaleString()}` : ""})
          </Link>
        </div>
      </Panel>
    );
  }
  return <p className="text-xs text-bad">{(error as Error).message}</p>;
}

function RegisterPath({ onDone }: { onDone: (r: RegisterVideoResponse) => void }) {
  const [path, setPath] = useState("");
  const [force, setForce] = useState(false);
  const m = useRegisterVideo();
  return (
    <CardShell icon={HardDriveUpload} title="Register server path" hint="Point the API at a file already visible inside its container.">
      <div className="space-y-1.5">
        <input className={inputCls} placeholder="/data/inbox/lesson.mp4" value={path} onChange={(e) => setPath(e.target.value)} />
        <p className={captionCls}>Must be reachable from the API container (the shared inbox volume, not your host path).</p>
      </div>
      <label className="flex items-center gap-2 text-xs text-muted">
        <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} className="accent-accent" />
        Force reprocess if already done
      </label>
      <div className="mt-auto space-y-2">
        <MutationError error={m.error} />
        <Button
          className="w-full"
          disabled={!path.trim() || m.isPending}
          onClick={() => m.mutate({ source_path: path.trim(), force }, { onSuccess: onDone })}
        >
          {m.isPending ? <Loader2 size={15} className="animate-spin" /> : <HardDriveUpload size={15} />} Register
        </Button>
      </div>
    </CardShell>
  );
}

function UploadFile({ onDone }: { onDone: (r: RegisterVideoResponse) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [force, setForce] = useState(false);
  const m = useUploadVideo();

  function onDrop(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) setFile(f);
  }

  return (
    <CardShell icon={UploadCloud} title="Upload a file" hint="Send a video straight from this browser into the shared inbox.">
      <label
        htmlFor="ingest-file-input"
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className={cx(
          "flex cursor-pointer flex-col items-center justify-center gap-1.5 rounded-xl border border-dashed px-4 py-6 text-center transition-all duration-200",
          dragOver ? "scale-[1.01] border-accent bg-sky-50" : "border-line bg-slate-50 hover:border-accent/40 hover:bg-sky-50/60",
        )}
      >
        {file ? (
          <>
            <IconBadge icon={FileVideo} tone="accent" size={30} />
            <div className="max-w-full truncate text-sm text-fg">{file.name}</div>
            <div className="num text-xs text-faint">{fmtBytes(file.size)} · click or drop to replace</div>
          </>
        ) : (
          <>
            <IconBadge icon={UploadCloud} tone="muted" size={30} />
            <div className="text-sm text-fg">Click to browse or drop a video</div>
            <div className="text-xs text-faint">MP4, WebM, MOV, MKV</div>
          </>
        )}
        <input
          id="ingest-file-input"
          type="file"
          accept="video/*"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="sr-only"
        />
      </label>

      {m.isPending && (
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
          <div className="h-full w-1/3 animate-shimmer rounded-full bg-gradient-to-r from-accent to-cyan" />
        </div>
      )}

      <label className="flex items-center gap-2 text-xs text-muted">
        <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} className="accent-accent" />
        Force reprocess if already done
      </label>

      <div className="mt-auto space-y-2">
        <MutationError error={m.error} />
        <Button
          className="w-full"
          disabled={!file || m.isPending}
          onClick={() => file && m.mutate({ file, force }, { onSuccess: onDone })}
        >
          {m.isPending ? <Loader2 size={15} className="animate-spin" /> : <Upload size={15} />}
          {m.isPending ? "Uploading…" : "Upload & register"}
        </Button>
      </div>
    </CardShell>
  );
}

function BatchEnqueue({ onDone }: { onDone: () => void }) {
  const [folder, setFolder] = useState("");
  const [glob, setGlob] = useState("");
  const m = useBatch();
  return (
    <CardShell icon={FolderGit2} title="Enqueue folder / glob" hint="Sweep a whole directory (or a glob pattern) in one batch.">
      <div className="space-y-1.5">
        <input className={inputCls} placeholder="/data/inbox  (folder)" value={folder} onChange={(e) => setFolder(e.target.value)} />
        <input className={inputCls} placeholder="/data/inbox/**/*.mp4  (glob)" value={glob} onChange={(e) => setGlob(e.target.value)} />
        <p className={captionCls}>Provide either one — a folder is scanned recursively, a glob matches a specific pattern.</p>
      </div>
      <div className="mt-auto space-y-2">
        {m.data && (
          <p className="num rounded-xl border border-line bg-slate-50 px-2.5 py-1.5 text-xs text-muted">
            <span className="text-fg">{m.data.enqueued}</span> queued · {m.data.skipped_existing} skipped · {m.data.total} total
          </p>
        )}
        {m.isError && <p className="text-xs text-bad">{(m.error as Error).message}</p>}
        <Button
          className="w-full"
          disabled={(!folder.trim() && !glob.trim()) || m.isPending}
          onClick={() =>
            m.mutate({ folder: folder.trim() || undefined, glob: glob.trim() || undefined }, { onSuccess: onDone })
          }
        >
          {m.isPending ? <Loader2 size={15} className="animate-spin" /> : <FolderGit2 size={15} />} Enqueue batch
        </Button>
      </div>
    </CardShell>
  );
}
