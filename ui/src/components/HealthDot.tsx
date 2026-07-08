import { cx } from "./primitives";

type State = "ok" | "bad" | "unknown";

export function HealthDot({ state, pulse }: { state: State; pulse?: boolean }) {
  const tone =
    state === "ok" ? "bg-ok" : state === "bad" ? "bg-bad" : "bg-faint";
  const glow =
    state === "ok"
      ? "shadow-[0_0_6px_1px_rgba(34,197,94,0.5)]"
      : state === "bad"
        ? "shadow-[0_0_6px_1px_rgba(239,68,68,0.5)]"
        : "";
  return (
    <span className="relative inline-flex h-2.5 w-2.5">
      {/* color-matched expanding ring via Tailwind's built-in animate-ping — inherits
          whatever `tone` bg is passed, so "ready" pulses emerald, "bad" pulses rose */}
      {pulse && state !== "unknown" && (
        <span className={cx("absolute inline-flex h-full w-full rounded-full opacity-60", tone, "animate-ping")} />
      )}
      <span className={cx("relative inline-flex h-2.5 w-2.5 rounded-full", tone, glow)} />
    </span>
  );
}
