import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { FileUp, FolderGit2, HardDriveUpload, Loader2 } from "lucide-react";
import { useBatch, useRegisterVideo, useUploadVideo } from "@/hooks/queries";
import type { RegisterVideoResponse } from "@/lib/types";
import { Badge, Button, Panel } from "@/components/primitives";

export function Ingest() {
  const nav = useNavigate();
  const [note, setNote] = useState<string | null>(null);

  function handleRegister(res: RegisterVideoResponse) {
    if (res.job_id) nav(`/jobs/${res.job_id}`);
    else setNote(`${res.status}: ${res.message}`);
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="font-display text-2xl font-bold">Ingest</h1>
        <p className="text-sm text-muted">
          Register a server path, upload a file, or enqueue a whole folder. Each runs the SHA-256 dedup pre-check before queueing.
        </p>
      </div>

      {note && (
        <Panel className="flex items-center gap-2 border-cyan/30 bg-cyan/5 text-sm">
          <Badge status={note.split(":")[0]} /> <span className="text-fg">{note}</span>
        </Panel>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <RegisterPath onDone={handleRegister} />
        <UploadFile onDone={handleRegister} />
        <BatchEnqueue onDone={() => nav("/jobs")} />
      </div>
    </div>
  );
}

function CardShell({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <Panel hover className="flex flex-col gap-3">
      <div className="flex items-center gap-2 text-fg">
        <span className="text-accent">{icon}</span>
        <h3 className="font-display text-base">{title}</h3>
      </div>
      {children}
    </Panel>
  );
}

const inputCls = "w-full rounded-xl border border-line bg-panel2 px-3 py-2 text-sm outline-none focus:border-accent";

function RegisterPath({ onDone }: { onDone: (r: RegisterVideoResponse) => void }) {
  const [path, setPath] = useState("");
  const [force, setForce] = useState(false);
  const m = useRegisterVideo();
  return (
    <CardShell icon={<HardDriveUpload size={18} />} title="Register server path">
      <input className={inputCls} placeholder="/data/inbox/lesson.mp4" value={path} onChange={(e) => setPath(e.target.value)} />
      <label className="flex items-center gap-2 text-xs text-muted">
        <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> force reprocess
      </label>
      <Button
        disabled={!path.trim() || m.isPending}
        onClick={() => m.mutate({ source_path: path.trim(), force }, { onSuccess: onDone })}
      >
        {m.isPending ? <Loader2 size={15} className="animate-spin" /> : null} Register
      </Button>
      {m.isError && <p className="text-xs text-bad">{(m.error as Error).message}</p>}
    </CardShell>
  );
}

function UploadFile({ onDone }: { onDone: (r: RegisterVideoResponse) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const m = useUploadVideo();
  return (
    <CardShell icon={<FileUp size={18} />} title="Upload a file">
      <input
        type="file"
        accept="video/*"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        className="block w-full text-xs text-muted file:mr-3 file:rounded-lg file:border-0 file:bg-accent file:px-3 file:py-1.5 file:text-ink hover:file:bg-accent-soft"
      />
      {m.isPending && (
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-panel2">
          <div className="h-full w-1/3 animate-shimmer rounded-full bg-accent" />
        </div>
      )}
      <Button disabled={!file || m.isPending} onClick={() => file && m.mutate({ file, force: false }, { onSuccess: onDone })}>
        {m.isPending ? "Uploading…" : "Upload & register"}
      </Button>
      {m.isError && <p className="text-xs text-bad">{(m.error as Error).message}</p>}
    </CardShell>
  );
}

function BatchEnqueue({ onDone }: { onDone: () => void }) {
  const [folder, setFolder] = useState("");
  const [glob, setGlob] = useState("");
  const m = useBatch();
  return (
    <CardShell icon={<FolderGit2 size={18} />} title="Enqueue folder / glob">
      <input className={inputCls} placeholder="/data/inbox  (folder)" value={folder} onChange={(e) => setFolder(e.target.value)} />
      <input className={inputCls} placeholder="/data/inbox/**/*.mp4  (glob)" value={glob} onChange={(e) => setGlob(e.target.value)} />
      <Button
        disabled={(!folder.trim() && !glob.trim()) || m.isPending}
        onClick={() =>
          m.mutate({ folder: folder.trim() || undefined, glob: glob.trim() || undefined }, { onSuccess: onDone })
        }
      >
        {m.isPending ? <Loader2 size={15} className="animate-spin" /> : null} Enqueue batch
      </Button>
      {m.data && (
        <p className="num text-xs text-muted">
          {m.data.enqueued} queued · {m.data.skipped_existing} skipped · {m.data.total} total
        </p>
      )}
      {m.isError && <p className="text-xs text-bad">{(m.error as Error).message}</p>}
    </CardShell>
  );
}
