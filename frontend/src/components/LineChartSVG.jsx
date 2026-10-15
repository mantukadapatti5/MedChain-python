import { useMemo, useState } from "react";

/**
 * Lightweight multi-series line chart built with plain SVG — no charting
 * library dependency, so it works without an `npm install` step.
 *
 * series: [{ key, label, color, points: [{x: number|string, y: number|null}] }]
 * `x` values across all series should be the same ordered categories (dates).
 */
export default function LineChartSVG({ series, xLabels, height = 260, splitIndex = null, splitLabel = "Today" }) {
  const [hoverIdx, setHoverIdx] = useState(null);
  const width = 720;
  const padding = { top: 16, right: 16, bottom: 28, left: 44 };
  const innerW = width - padding.left - padding.right;
  const innerH = height - padding.top - padding.bottom;

  const allY = series.flatMap((s) => s.points.map((p) => p.y)).filter((y) => y !== null && y !== undefined);
  const maxY = Math.max(...allY, 1) * 1.1;
  const minY = 0;
  const n = xLabels.length;

  const xPos = (i) => padding.left + (n <= 1 ? 0 : (i / (n - 1)) * innerW);
  const yPos = (v) => padding.top + innerH - ((v - minY) / (maxY - minY || 1)) * innerH;

  const pathFor = (points) => {
    let d = "";
    let started = false;
    points.forEach((p, i) => {
      if (p.y === null || p.y === undefined) { started = false; return; }
      const cmd = started ? "L" : "M";
      d += `${cmd}${xPos(i).toFixed(1)},${yPos(p.y).toFixed(1)} `;
      started = true;
    });
    return d.trim();
  };

  const yTicks = useMemo(() => {
    const steps = 4;
    return Array.from({ length: steps + 1 }, (_, i) => Math.round((maxY / steps) * i));
  }, [maxY]);

  const tickEvery = Math.max(1, Math.ceil(n / 8));

  return (
    <div className="relative w-full overflow-x-auto">
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" style={{ minWidth: 480 }}>
        {yTicks.map((t, i) => (
          <g key={i}>
            <line x1={padding.left} x2={width - padding.right} y1={yPos(t)} y2={yPos(t)}
                  stroke="#e2e8f0" strokeWidth={1} />
            <text x={padding.left - 8} y={yPos(t) + 3} textAnchor="end" fontSize="9" fill="#94a3b8">{t}</text>
          </g>
        ))}

        {splitIndex !== null && splitIndex >= 0 && splitIndex < n && (
          <g>
            <line x1={xPos(splitIndex)} x2={xPos(splitIndex)} y1={padding.top} y2={padding.top + innerH}
                  stroke="#cbd5e1" strokeWidth={1.5} strokeDasharray="4,3" />
            <text x={xPos(splitIndex)} y={padding.top - 4} textAnchor="middle" fontSize="9" fill="#64748b">
              {splitLabel}
            </text>
          </g>
        )}

        {series.map((s) => (
          <path key={s.key} d={pathFor(s.points)} fill="none" stroke={s.color} strokeWidth={s.emphasize ? 2.5 : 1.75}
                strokeDasharray={s.dashed ? "5,3" : undefined} opacity={s.emphasize ? 1 : 0.85} />
        ))}

        {xLabels.map((label, i) => (
          i % tickEvery === 0 && (
            <text key={i} x={xPos(i)} y={height - 8} textAnchor="middle" fontSize="8.5" fill="#94a3b8">
              {label.slice(5)}
            </text>
          )
        ))}

        {hoverIdx !== null && (
          <line x1={xPos(hoverIdx)} x2={xPos(hoverIdx)} y1={padding.top} y2={padding.top + innerH}
                stroke="#475569" strokeWidth={1} strokeDasharray="2,2" />
        )}

        <rect x={padding.left} y={padding.top} width={innerW} height={innerH} fill="transparent"
              onMouseMove={(e) => {
                const rect = e.currentTarget.getBoundingClientRect();
                const relX = e.clientX - rect.left;
                const idx = Math.round((relX / rect.width) * (n - 1));
                setHoverIdx(Math.max(0, Math.min(n - 1, idx)));
              }}
              onMouseLeave={() => setHoverIdx(null)} />
      </svg>

      {hoverIdx !== null && (
        <div className="absolute top-2 right-2 bg-white border border-slate-200 rounded-lg shadow-sm px-3 py-2 text-[11px] space-y-1">
          <p className="font-semibold text-ink-900">{xLabels[hoverIdx]}</p>
          {series.map((s) => {
            const v = s.points[hoverIdx]?.y;
            if (v === null || v === undefined) return null;
            return (
              <p key={s.key} className="flex items-center gap-1.5">
                <span className="inline-block w-2 h-2 rounded-full" style={{ background: s.color }} />
                {s.label}: <span className="font-medium">{v}</span>
              </p>
            );
          })}
        </div>
      )}

      <div className="flex flex-wrap gap-3 mt-2 justify-center">
        {series.map((s) => (
          <span key={s.key} className="flex items-center gap-1.5 text-[11px] text-slate-500">
            <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}
