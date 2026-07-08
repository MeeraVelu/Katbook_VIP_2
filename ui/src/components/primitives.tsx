import type { ButtonHTMLAttributes, ReactNode } from "react";
import { AlertTriangle, Inbox, RotateCw } from "lucide-react";
import type { LucideIcon } from "lucide-react";

function cx(...parts: (string | false | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

type Variant = "primary" | "ghost" | "danger" | "cyan";

export function Button({
  variant = "primary",
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  const styles: Record<Variant, string> = {
    primary: "bg-accent text-white font-semibold shadow-panel hover:bg-accent-dim hover:shadow-glow",
    ghost: "bg-white text-fg border border-line hover:bg-accent-soft/15 hover:border-accent/30",
    danger: "bg-bad/10 text-bad border border-bad/25 hover:bg-bad/15",
    cyan: "bg-cyan/10 text-cyan border border-cyan/25 hover:bg-cyan/15",
  };
  return (
    <button
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-full px-4 py-2 text-sm transition-all duration-200 ease-out hover:scale-[1.02] active:scale-[0.97]",
        "disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:scale-100",
        styles[variant],
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

export function Panel({
  className,
  children,
  hover,
  glow,
  id,
}: {
  className?: string;
  children: ReactNode;
  hover?: boolean;
  /** Thin accent-colored top edge — a restrained nod to emphasis, no glow/blob on light surfaces. */
  glow?: "accent" | "cyan";
  id?: string;
}) {
  return (
    <div id={id} className={cx("panel p-4", hover && "panel-hover", className)}>
      {glow && (
        <div
          aria-hidden
          className={cx("absolute inset-x-0 top-0 h-0.5", glow === "accent" ? "bg-accent/50" : "bg-cyan/50")}
        />
      )}
      <div className="relative">{children}</div>
    </div>
  );
}

// pill-shaped, soft-tint background + matching darker text + a small leading dot
const STATUS_TONE: Record<string, string> = {
  done: "text-emerald-700 bg-emerald-50 border-emerald-200",
  processing: "text-sky-700 bg-sky-50 border-sky-200",
  queued: "text-cyan-700 bg-cyan-50 border-cyan-200",
  failed: "text-red-700 bg-red-50 border-red-200",
  soft_deleted: "text-slate-500 bg-slate-100 border-slate-200",
  duplicate: "text-slate-500 bg-slate-100 border-slate-200",
  exists: "text-slate-500 bg-slate-100 border-slate-200",
};

const STATUS_DOT: Record<string, string> = {
  done: "bg-emerald-500",
  processing: "bg-sky-500 animate-pulse-accent",
  queued: "bg-cyan-500",
  failed: "bg-red-500",
};

export function Badge({ status }: { status: string }) {
  const tone = STATUS_TONE[status] ?? "text-slate-500 bg-slate-100 border-slate-200";
  const dot = STATUS_DOT[status];
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide",
        tone,
      )}
    >
      {dot && <span className={cx("h-1.5 w-1.5 rounded-full", dot)} />}
      {status.replace("_", " ")}
    </span>
  );
}

type IconTone = "accent" | "cyan" | "ok" | "bad" | "muted";

// flat pastel chip — icon in a matching darker shade, no glow (Notion/Linear-style flat icon tiles)
const ICON_TONE: Record<IconTone, string> = {
  accent: "bg-sky-50 text-sky-600",
  cyan: "bg-cyan-50 text-cyan-600",
  ok: "bg-emerald-50 text-emerald-600",
  bad: "bg-red-50 text-red-600",
  muted: "bg-slate-100 text-slate-500",
};

/** Circular flat pastel icon container — the app's recurring "glyph in a soft chip" motif. */
export function IconBadge({
  icon: Icon,
  tone = "accent",
  size = 34,
  iconSize,
  className,
}: {
  icon: LucideIcon;
  tone?: IconTone;
  size?: number;
  iconSize?: number;
  className?: string;
}) {
  return (
    <span
      className={cx("inline-flex shrink-0 items-center justify-center rounded-full", ICON_TONE[tone], className)}
      style={{ width: size, height: size }}
    >
      <Icon size={iconSize ?? Math.round(size * 0.46)} strokeWidth={1.9} />
    </span>
  );
}

/** Icon + label + value tile — the recurring stat/meta block used across detail pages. */
export function StatTile({
  icon: Icon,
  label,
  value,
  tone = "muted",
  mono,
}: {
  icon: LucideIcon;
  label: string;
  value: ReactNode;
  tone?: IconTone;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-line bg-panel2/60 px-3 py-2.5 transition-colors hover:bg-panel2">
      <IconBadge icon={Icon} tone={tone} size={30} />
      <div className="min-w-0">
        <div className="truncate text-[11px] uppercase tracking-wide text-faint">{label}</div>
        <div className={cx("truncate text-sm text-fg", mono && "num")}>{value}</div>
      </div>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("shimmer rounded-xl", className)} />;
}

export function SkeletonRows({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-12 w-full" />
      ))}
    </div>
  );
}

export function EmptyState({
  icon: Icon = Inbox,
  title,
  hint,
  action,
}: {
  icon?: LucideIcon;
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-line bg-white py-16 text-center">
      <IconBadge icon={Icon} tone="accent" size={48} iconSize={22} />
      <div className="font-display text-lg font-semibold text-fg">{title}</div>
      {hint && <div className="max-w-md text-sm text-muted">{hint}</div>}
      {action}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-bad/20 bg-red-50/50 py-12 text-center">
      <IconBadge icon={AlertTriangle} tone="bad" size={48} iconSize={22} />
      <div className="font-display text-fg">Something went wrong</div>
      <div className="max-w-md text-sm text-muted">{message}</div>
      {onRetry && (
        <Button variant="ghost" onClick={onRetry}>
          <RotateCw size={15} /> Retry
        </Button>
      )}
    </div>
  );
}

export { cx };
