import type { AlertVolumeBucket } from "../api/types";
import { formatHour } from "../lib/format";

export function AlertVolumeChart({ buckets }: { buckets: AlertVolumeBucket[] }) {
  const width = 640;
  const height = 180;
  const padding = { top: 18, right: 12, bottom: 30, left: 28 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const max = Math.max(1, ...buckets.map((bucket) => bucket.count));
  const slot = plotWidth / Math.max(buckets.length, 1);
  const barWidth = Math.max(10, slot * 0.62);
  const total = buckets.reduce((sum, bucket) => sum + bucket.count, 0);

  return (
    <figure className="chart">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`Alert volume for the last ${buckets.length} hours. ${total} alerts received.`}
        className="chart__svg"
      >
        {[0, 0.5, 1].map((fraction) => {
          const y = padding.top + plotHeight * (1 - fraction);
          return (
            <g key={fraction}>
              <line
                x1={padding.left}
                x2={width - padding.right}
                y1={y}
                y2={y}
                className="chart__grid"
              />
              <text x={padding.left - 8} y={y + 4} textAnchor="end" className="chart__axis">
                {Math.round(max * fraction)}
              </text>
            </g>
          );
        })}
        {buckets.map((bucket, index) => {
          const barHeight = (bucket.count / max) * plotHeight;
          const x = padding.left + index * slot + (slot - barWidth) / 2;
          const y = padding.top + plotHeight - barHeight;
          return (
            <g key={bucket.bucket_start}>
              <rect
                x={x}
                y={y}
                width={barWidth}
                height={Math.max(barHeight, bucket.count > 0 ? 3 : 1)}
                rx={3}
                className={bucket.count > 0 ? "chart__bar" : "chart__bar chart__bar--empty"}
              >
                <title>
                  {formatHour(bucket.bucket_start)}: {bucket.count} alerts
                </title>
              </rect>
              {index % 2 === 0 ? (
                <text
                  x={x + barWidth / 2}
                  y={height - 10}
                  textAnchor="middle"
                  className="chart__axis"
                >
                  {formatHour(bucket.bucket_start)}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
      <figcaption className="chart__caption">
        <span>Last 12 hours</span>
        <span>
          <strong>{total}</strong> alerts received
        </span>
      </figcaption>
    </figure>
  );
}
