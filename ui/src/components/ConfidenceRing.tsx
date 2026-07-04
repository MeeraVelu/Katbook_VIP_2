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
  // low confidence leans muted-cyan, high leans warm accent
  const color = value == null ? "#3A4453" : v >= 0.7 ? "#F59E0B" : v >= 0.45 ? "#4CC9D6" : "#8B94A7";
  return (
    <div className="relative inline-flex" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#232C3B" strokeWidth={stroke} />
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
