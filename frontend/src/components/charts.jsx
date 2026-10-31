import { useMemo } from "react";
import { money, percent } from "../lib/format";
import { cn } from "./ui";

const PALETTE = [
  "#059669",
  "#34d399",
  "#0ea5e9",
  "#f59e0b",
  "#8b5cf6",
  "#ef4444",
  "#14b8a6",
  "#64748b",
  "#d946ef",
  "#84cc16",
];

function collapseRows(rows, total) {
  if (rows.length <= 7) return rows;
  const major = rows.filter((row) => row.value / total >= 0.03);
  const minor = rows.filter((row) => row.value / total < 0.03);
  if (minor.length < 2) return rows;
  const other = minor.reduce(
    (acc, row) => ({ label: "Other", value: acc.value + row.value, color: "#94a3b8" }),
    { label: "Other", value: 0, color: "#94a3b8" },
  );
  return [...major, other];
}

export function DonutChart({
  title,
  subtitle,
  data = [],
  labelKey = "label",
  valueKey = "value",
  centerLabel = "Total",
  emptyText = "No data for this period.",
  className = "",
}) {
  const { rows, total } = useMemo(() => {
    const clean = data
      .map((row, index) => ({
        label: String(row[labelKey] ?? row.category ?? row.method ?? row.name ?? "—"),
        value: Number(row[valueKey] ?? row.amount ?? row.sales_total ?? 0) || 0,
        color: row.color || PALETTE[index % PALETTE.length],
      }))
      .filter((row) => row.value > 0);
    const sum = clean.reduce((acc, row) => acc + row.value, 0);
    return { rows: collapseRows(clean, sum || 1), total: sum };
  }, [data, labelKey, valueKey]);

  const radius = 68;
  const circumference = 2 * Math.PI * radius;
  const segments = useMemo(
    () =>
      rows.map((row, index) => ({
        ...row,
        length: (row.value / total) * circumference,
        offset:
          rows
            .slice(0, index)
            .reduce((sum, previous) => sum + (previous.value / total) * circumference, 0),
      })),
    [rows, total, circumference],
  );

  return (
    <div className={cn("flex h-full flex-col", className)}>
      {(title || subtitle) && (
        <div className="mb-4">
          {title && <h3 className="font-display text-base font-semibold text-ink-950">{title}</h3>}
          {subtitle && <p className="mt-0.5 text-xs text-ink-400">{subtitle}</p>}
        </div>
      )}

      {total <= 0 ? (
        <p className="flex flex-1 items-center justify-center px-4 py-10 text-center text-sm text-ink-500">
          {emptyText}
        </p>
      ) : (
        <div className="flex flex-col items-center gap-5">
          <div className="relative h-44 w-44 shrink-0">
            <svg viewBox="0 0 180 180" className="h-full w-full" role="img" aria-label={title}>
              <circle cx="90" cy="90" r={radius} fill="none" stroke="#f1f5f9" strokeWidth="22" />
              {segments.map((row) => {
                const fraction = row.value / total;
                return (
                  <circle
                    key={row.label}
                    cx="90"
                    cy="90"
                    r={radius}
                    fill="none"
                    stroke={row.color}
                    strokeWidth="22"
                    strokeDasharray={`${Math.max(row.length - 2, 0.5)} ${circumference}`}
                    strokeDashoffset={-row.offset}
                    transform="rotate(-90 90 90)"
                  >
                    <title>{`${row.label}: KES ${money(row.value)} (${percent(fraction * 100)}%)`}</title>
                  </circle>
                );
              })}
            </svg>
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
              <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-ink-400">
                {centerLabel}
              </span>
              <span className="tabular mt-0.5 font-display text-lg font-semibold text-ink-950">
                KES {money(total)}
              </span>
            </div>
          </div>

          <ul className="w-full space-y-2">
            {rows.map((row) => {
              const share = (row.value / total) * 100;
              return (
                <li key={row.label} className="flex items-center gap-2 text-xs">
                  <span
                    className="h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: row.color }}
                  />
                  <span className="min-w-0 flex-1 truncate font-medium text-ink-700">
                    {row.label}
                  </span>
                  <span className="shrink-0 font-bold tabular text-ink-900">{percent(share)}%</span>
                  <span className="w-24 shrink-0 text-right tabular text-ink-500">
                    {money(row.value)}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

export function SplitBar({ segments = [], className = "" }) {
  const total = segments.reduce((sum, segment) => sum + Number(segment.value || 0), 0);
  if (total <= 0) return null;

  return (
    <div className={cn("space-y-3", className)}>
      <div className="flex h-3 w-full overflow-hidden rounded-full bg-ink-100">
        {segments.map((segment, index) => (
          <span
            key={segment.label}
            title={`${segment.label}: ${money(segment.value)}`}
            className="h-full"
            style={{
              width: `${(Number(segment.value) / total) * 100}%`,
              backgroundColor: segment.color || PALETTE[index % PALETTE.length],
            }}
          />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-5 gap-y-2">
        {segments.map((segment, index) => (
          <span key={segment.label} className="flex items-center gap-1.5 text-xs text-ink-500">
            <span
              className="h-2 w-2 rounded-sm"
              style={{ backgroundColor: segment.color || PALETTE[index % PALETTE.length] }}
            />
            {segment.label}
            <strong className="tabular text-ink-800">{money(segment.value)}</strong>
            <span className="tabular text-ink-400">
              {percent((Number(segment.value) / total) * 100)}%
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}
