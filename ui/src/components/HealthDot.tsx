import { cx } from "./primitives";

type State = "ok" | "bad" | "unknown";

export function HealthDot({ state, pulse }: { state: State; pulse?: boolean }) {
  const tone =
    state === "ok" ? "bg-ok" : state === "bad" ? "bg-bad" : "bg-faint";
  return (
    <span className="relative inline-flex h-2.5 w-2.5">
      {pulse && state === "ok" && (
        <span className={cx("absolute inline-flex h-full w-full rounded-full opacity-60", tone, "animate-pulse-accent")} />
      )}
      <span className={cx("relative inline-flex h-2.5 w-2.5 rounded-full", tone)} />
    </span>
  );
}
