import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { Activity, KeyRound, Library, Search, Server, Upload } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useHealth, useReady } from "@/hooks/queries";
import { getApiKey, setApiKey } from "@/lib/api";
import { GpuTierChip } from "./GpuTierChip";
import { HealthDot } from "./HealthDot";
import { CommandBar } from "./CommandBar";
import { Button, cx } from "./primitives";

const NAV: { to: string; label: string; icon: LucideIcon }[] = [
  { to: "/library", label: "Library", icon: Library },
  { to: "/search", label: "Search", icon: Search },
  { to: "/ingest", label: "Ingest", icon: Upload },
  { to: "/jobs", label: "Jobs", icon: Activity },
  { to: "/system", label: "System", icon: Server },
];

export function Layout() {
  const [cmdOpen, setCmdOpen] = useState(false);
  const [keyOpen, setKeyOpen] = useState(false);
  const health = useHealth();
  const ready = useReady();

  // "/" opens the command bar (unless typing in a field)
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const el = document.activeElement;
      const typing = el instanceof HTMLElement && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
      if (e.key === "/" && !typing && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        setCmdOpen(true);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const healthState = health.isError ? "bad" : health.data ? "ok" : "unknown";
  const isReady = !!ready.data?.ready;

  return (
    // the white -> sky-blue-gray gradient lives on <body> (index.css); no aurora
    // blobs here — a flat, bright, clean SaaS shell.
    <div className="dot-grid flex h-screen text-fg">
      {/* left icon rail */}
      <nav className="flex w-16 flex-col items-center gap-2 border-r border-line bg-white py-4">
        {/* logo: sky-blue -> cyan gradient circle, white glyph */}
        <div className="mb-5 flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-accent to-cyan font-display text-base font-bold text-white shadow-panel">
          K
        </div>
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            title={label}
            className={({ isActive }) =>
              cx(
                "group relative flex h-11 w-11 items-center justify-center rounded-full transition-all duration-200 ease-out",
                isActive ? "bg-sky-100 text-sky-600" : "text-muted hover:bg-sky-50 hover:text-accent",
              )
            }
          >
            <Icon size={20} strokeWidth={1.8} className="transition-transform duration-200 group-hover:scale-110" />
          </NavLink>
        ))}
      </nav>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* sticky header */}
        <header className="sticky top-0 z-30 flex items-center justify-between gap-4 border-b border-line bg-white/90 px-6 py-3 backdrop-blur-sm">
          <div className="flex items-baseline gap-2">
            <span className="font-display text-lg font-bold tracking-tight text-fg">
              Video AI <span className="text-gradient">Pipeline</span>
            </span>
            <span className="num text-xs text-faint">{health.data ? `v${health.data.version}` : "·"}</span>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setCmdOpen(true)}
              className="hidden items-center gap-2 rounded-full border border-line bg-slate-50 px-3.5 py-1.5 text-xs text-muted transition-colors hover:border-accent/30 hover:bg-white sm:flex"
            >
              <Search size={13} /> Search <kbd className="num rounded-full bg-white px-1.5 py-0.5 text-[10px] shadow-sm">/</kbd>
            </button>
            <GpuTierChip />
            <div
              className={cx(
                "flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs transition-colors",
                isReady ? "border-sky-200 bg-sky-50 text-sky-700" : "border-line bg-slate-50 text-muted",
              )}
              title={ready.data ? (ready.data.ready ? "ready" : "not ready") : "checking"}
            >
              <HealthDot state={healthState} pulse />
              <span>{ready.data ? (ready.data.ready ? "ready" : "degraded") : "…"}</span>
            </div>
            <button
              onClick={() => setKeyOpen(true)}
              title="API key"
              className={cx(
                "flex h-8 w-8 items-center justify-center rounded-full border transition-all hover:scale-110",
                getApiKey()
                  ? "border-line bg-slate-50 text-muted hover:text-fg"
                  : "border-sky-200 bg-sky-50 text-accent",
              )}
            >
              <KeyRound size={15} />
            </button>
          </div>
        </header>

        <main className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
          <Outlet />
        </main>
      </div>

      <CommandBar open={cmdOpen} onClose={() => setCmdOpen(false)} />
      {keyOpen && <ApiKeyModal onClose={() => setKeyOpen(false)} />}
    </div>
  );
}

function ApiKeyModal({ onClose }: { onClose: () => void }) {
  const [val, setVal] = useState(getApiKey());
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/30 px-4 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-full max-w-md rounded-2xl border border-line bg-white p-5 shadow-glow"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-1 font-display text-lg font-semibold text-fg">API key</div>
        <p className="mb-3 text-sm text-muted">
          Sent as <span className="num text-fg">X-API-Key</span> on every request. Stored locally in this browser.
          Leave blank if the API has auth disabled.
        </p>
        <input
          value={val}
          onChange={(e) => setVal(e.target.value)}
          type="password"
          placeholder="X-API-Key"
          className="mb-4 w-full rounded-xl border border-line bg-slate-50 px-3.5 py-2.5 text-sm outline-none transition-colors placeholder:text-faint focus:border-accent/50 focus:ring-1 focus:ring-accent/30"
        />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={() => {
              setApiKey(val.trim());
              onClose();
            }}
          >
            Save
          </Button>
        </div>
      </div>
    </div>
  );
}
