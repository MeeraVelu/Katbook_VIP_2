import { CheckCircle2, Cpu, XCircle } from "lucide-react";
import { useHealth, useReady } from "@/hooks/queries";
import { readTier, tierLabel } from "@/lib/tiers";
import { Panel, Skeleton, cx } from "@/components/primitives";

export function System() {
  const health = useHealth();
  const ready = useReady();
  const tier = readTier(ready.data?.details);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="font-display text-2xl font-bold">System</h1>
        <p className="text-sm text-muted">Liveness, readiness per-check, and the worker GPU tier.</p>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Panel className="space-y-2">
          <div className="text-xs uppercase tracking-wide text-faint">API</div>
          {health.isLoading ? (
            <Skeleton className="h-6 w-24" />
          ) : health.isError ? (
            <div className="text-bad">unreachable</div>
          ) : (
            <>
              <div className="flex items-center gap-2 text-ok">
                <CheckCircle2 size={18} /> <span className="font-display text-lg">{health.data?.status}</span>
              </div>
              <div className="num text-xs text-muted">v{health.data?.version}</div>
            </>
          )}
        </Panel>

        <Panel className="space-y-2">
          <div className="text-xs uppercase tracking-wide text-faint">Readiness</div>
          {ready.isLoading ? (
            <Skeleton className="h-6 w-24" />
          ) : (
            <div className={cx("font-display text-lg", ready.data?.ready ? "text-ok" : "text-accent")}>
              {ready.data?.ready ? "ready" : "degraded"}
            </div>
          )}
        </Panel>

        <Panel className="space-y-2">
          <div className="text-xs uppercase tracking-wide text-faint">Worker GPU tier</div>
          <div className="flex items-center gap-2">
            <Cpu size={18} className="text-accent" />
            <span className="num font-display text-lg">{tierLabel(tier)}</span>
          </div>
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
              <div key={name} className="flex items-center justify-between py-2.5">
                <span className="text-sm capitalize text-fg">{name.replace(/_/g, " ")}</span>
                {ok ? (
                  <span className="flex items-center gap-1.5 text-sm text-ok">
                    <CheckCircle2 size={16} /> pass
                  </span>
                ) : (
                  <span className="flex items-center gap-1.5 text-sm text-bad">
                    <XCircle size={16} /> fail
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
          <pre className="num overflow-x-auto whitespace-pre-wrap rounded-xl bg-panel2 p-3 text-xs text-muted">
            {JSON.stringify(ready.data.details, null, 2)}
          </pre>
        </Panel>
      )}
    </div>
  );
}
