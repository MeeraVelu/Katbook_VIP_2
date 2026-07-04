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
    primary: "bg-accent text-ink hover:bg-accent-soft font-semibold",
    ghost: "bg-transparent text-fg border border-line hover:bg-panel2",
    danger: "bg-transparent text-bad border border-bad/40 hover:bg-bad/10",
    cyan: "bg-cyan/15 text-cyan border border-cyan/30 hover:bg-cyan/25",
  };
  return (
    <button
      className={cx(
        "inline-flex items-center gap-2 rounded-xl px-3.5 py-2 text-sm transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-50",
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
  id,
}: {
  className?: string;
  children: ReactNode;
  hover?: boolean;
  id?: string;
}) {
  return (
    <div id={id} className={cx("panel p-4", hover && "panel-hover", className)}>
      {children}
    </div>
  );
}

const STATUS_TONE: Record<string, string> = {
  done: "text-ok bg-ok/10 border-ok/25",
  processing: "text-accent bg-accent/10 border-accent/25",
  queued: "text-cyan bg-cyan/10 border-cyan/25",
  failed: "text-bad bg-bad/10 border-bad/25",
  soft_deleted: "text-faint bg-panel2 border-line",
  duplicate: "text-muted bg-panel2 border-line",
  exists: "text-muted bg-panel2 border-line",
};

export function Badge({ status }: { status: string }) {
  const tone = STATUS_TONE[status] ?? "text-muted bg-panel2 border-line";
  return (
    <span
      className={cx(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide",
        tone,
      )}
    >
      {status.replace("_", " ")}
    </span>
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
    <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-line bg-panel/40 py-16 text-center">
      <div className="rounded-2xl border border-line bg-panel2 p-3 text-faint">
        <Icon size={22} strokeWidth={1.6} />
      </div>
      <div className="font-display text-lg text-fg">{title}</div>
      {hint && <div className="max-w-md text-sm text-muted">{hint}</div>}
      {action}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-bad/25 bg-bad/5 py-12 text-center">
      <AlertTriangle className="text-bad" size={22} />
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
