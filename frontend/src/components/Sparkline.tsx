import type { TimeSeries } from "../api/types";
import { formatNumber } from "../lib/format";

export function Sparkline({
  series,
  width = 420,
  height = 120,
}: {
  series: TimeSeries;
  width?: number;
  height?: number;
}) {
  const points = series.points
    .map((point, index) => ({
      x: index,
      y: point.value,
      date: point.date || String(point.acquisition || index),
    }))
    .filter((point) => Number.isFinite(point.y));

  if (points.length < 2) {
    return <div className="sparkline-empty">Not enough points to plot a trend.</div>;
  }

  const values = points.map((point) => point.y);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pad = 14;
  const innerW = width - pad * 2;
  const innerH = height - pad * 2 - 16;

  const coordinates = points.map((point, index) => {
    const x = pad + (index / (points.length - 1)) * innerW;
    const y = pad + innerH - ((point.y - min) / span) * innerH;
    return { x, y, date: point.date, value: point.y };
  });

  const line = coordinates.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
  const area = `${pad},${pad + innerH} ${line} ${pad + innerW},${pad + innerH}`;
  const changePoints = new Set(
    series.change_points
      .map((entry) => Number(entry.index))
      .filter((value) => Number.isInteger(value)),
  );

  return (
    <svg
      className="sparkline"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`${series.series_type} time series`}
    >
      <defs>
        <linearGradient id={`spark-fill-${series.id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#59e1d0" stopOpacity="0.3" />
          <stop offset="100%" stopColor="#59e1d0" stopOpacity="0" />
        </linearGradient>
      </defs>
      {[0, 0.5, 1].map((fraction) => (
        <line
          key={fraction}
          x1={pad}
          x2={pad + innerW}
          y1={pad + innerH * fraction}
          y2={pad + innerH * fraction}
          className="spark-grid"
        />
      ))}
      <polygon points={area} fill={`url(#spark-fill-${series.id})`} />
      <polyline points={line} className="spark-line" />
      {coordinates.map((point, index) => (
        <g key={index}>
          <circle
            cx={point.x}
            cy={point.y}
            r={changePoints.has(index) ? 5 : 3}
            className={changePoints.has(index) ? "spark-point change" : "spark-point"}
          />
          <title>
            {point.date}: {formatNumber(point.value, 3)} {series.unit}
          </title>
        </g>
      ))}
      <text x={pad} y={height - 3} className="spark-label">
        {coordinates[0].date}
      </text>
      <text x={pad + innerW} y={height - 3} textAnchor="end" className="spark-label">
        {coordinates[coordinates.length - 1].date}
      </text>
      <text x={width - pad} y={pad - 3} textAnchor="end" className="spark-unit">
        {series.unit}
      </text>
    </svg>
  );
}
