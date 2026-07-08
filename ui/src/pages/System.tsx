import { Activity, CheckCircle2, Cpu, Server, XCircle } from "lucide-react";
import { useHealth, useReady } from "@/hooks/queries";
import { readTier, tierLabel } from "@/lib/tiers";
import { IconBadge, Panel, Skeleton, cx } from "@/components/primitives";

export function System() {
  const health = useHealth();
  const ready = useReady();
  const tier = readTier(ready.data?.details);

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <IconBadge icon={Server} tone="accent" size={40} />
        <div>
          <h1 className="font-display text-2xl font-bold">System</h1>
          <p className="text-sm text-muted">Liveness, readiness per-check, and the worker GPU tier.</p>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Panel glow="cyan" className="space-y-2">
          <div className="flex items-center gap-2">
            <IconBadge icon={CheckCircle2} tone={health.isError ? "bad" : "ok"} size={28} iconSize={15} />
            <div className="text-xs uppercase tracking-wide text-faint">API</div>
          </div>
          {health.isLoading ? (
            <Skeleton className="h-6 w-24" />
          ) : health.isError ? (
            <div className="text-bad">unreachable</div>
          ) : (
            <>
              <div className="flex items-center gap-2 text-ok">
                <span className="font-display text-lg">{health.data?.status}</span>
              </div>
              <div className="num text-xs text-muted">v{health.data?.version}</div>
            </>
          )}
        </Panel>

        <Panel glow="accent" className="space-y-2">
          <div className="flex items-center gap-2">
            <IconBadge icon={Activity} tone={ready.data?.ready ? "ok" : "accent"} size={28} iconSize={15} />
            <div className="text-xs uppercase tracking-wide text-faint">Readiness</div>
          </div>
          {ready.isLoading ? (
            <Skeleton className="h-6 w-24" />
          ) : (
            <div className={cx("font-display text-lg", ready.data?.ready ? "text-ok" : "text-accent")}>
              {ready.data?.ready ? "ready" : "degraded"}
            </div>
          )}
        </Panel>

        <Panel glow="cyan" className="space-y-2">
          <div className="flex items-center gap-2">
            <IconBadge icon={Cpu} tone="cyan" size={28} iconSize={15} />
            <div className="text-xs uppercase tracking-wide text-faint">Worker GPU tier</div>
          </div>
          <span className="num font-display text-lg">{tierLabel(tier)}</span>
          {tier.device && <div className="num text-xs text-muted">{tier.device}</div>}
        </Panel>
      </div>

      <Panel className="space-y-3">
        <div className="text-xs uppercase tracking-wide text-faint">Readiness checks</div>
        {ready.isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          <div className="divide-y divide-line">
            {Object.entries(ready.data?.checks ?? {}).map(([name, ok]) => (
              <div
                key={name}
                className="flex items-center justify-between rounded-lg px-2 py-2.5 transition-colors hover:bg-sky-50/60"
              >
                <span className="text-sm capitalize text-fg">{name.replace(/_/g, " ")}</span>
                {ok ? (
                  <span className="flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs text-emerald-700">
                    <CheckCircle2 size={13} /> pass
                  </span>
                ) : (
                  <span className="flex items-center gap-1.5 rounded-full border border-red-200 bg-red-50 px-2.5 py-1 text-xs text-red-700">
                    <XCircle size={13} /> fail
                  </span>
                )}
              </div>
            ))}
            {Object.keys(ready.data?.checks ?? {}).length === 0 && (
              <div className="py-2 text-sm text-faint">No checks reported.</div>
            )}
          </div>
        )}
      </Panel>

      {ready.data?.details && Object.keys(ready.data.details).length > 0 && (
        <Panel className="space-y-2">
          <div className="text-xs uppercase tracking-wide text-faint">Details</div>
          <pre className="num overflow-x-auto whitespace-pre-wrap rounded-xl border border-line bg-slate-50 p-3 text-xs text-muted">
            {JSON.stringify(ready.data.details, null, 2)}
          </pre>
        </Panel>
      )}
    </div>
  );
}
