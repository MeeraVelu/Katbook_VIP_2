// Small SVG ring gauge shown on every segment card.
export function ConfidenceRing({
  value,
  size = 40,
  label = true,
}: {
  value: number | null;
  size?: number;
  label?: boolean;
}) {
  const v = value == null ? 0 : Math.max(0, Math.min(1, value));
  const stroke = 4;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const dash = c * v;
  // low confidence leans slate, mid leans cyan, high leans sky-blue accent
  const color = value == null ? "#CBD5E1" : v >= 0.7 ? "#0369A1" : v >= 0.45 ? "#06B6D4" : "#94A3B8";
  return (
    <div className="relative inline-flex" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#E2E8F0" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${c - dash}`}
        />
      </svg>
      {label && (
        <span className="num absolute inset-0 flex items-center justify-center text-[10px] text-fg">
          {value == null ? "—" : Math.round(v * 100)}
        </span>
      )}
    </div>
  );
}
