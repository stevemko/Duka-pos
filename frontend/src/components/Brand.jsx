import { cn } from "./ui";

export function BrandMark({ size = 40, className = "" }) {
  return (
    <span
      className={cn(
        "relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-2xl bg-gradient-to-br from-brand-400 via-brand-500 to-brand-800 text-ink-950 shadow-[0_10px_30px_-12px_rgba(16,185,129,0.8)]",
        className,
      )}
      style={{ height: size, width: size }}
      aria-hidden="true"
    >
      <svg viewBox="0 0 48 48" width={size * 0.7} height={size * 0.7} fill="none">
        <path
          d="M20 35h8M21 40h6M24 9a9 9 0 0 0-5 16.5V31h10v-5.5A9 9 0 0 0 24 9Z"
          stroke="currentColor"
          strokeWidth="2.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d="M24 14v6M21 17h6"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
        />
        <path
          d="M10 13.5c1.5-3 3.9-5.3 7-6.7M38 13.5c-1.5-3-3.9-5.3-7-6.7"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          opacity="0.45"
        />
      </svg>
    </span>
  );
}

export function BrandLockup({ compact = false, className = "" }) {
  return (
    <span className={cn("flex items-center gap-3", className)}>
      <BrandMark size={compact ? 36 : 40} />
      <span className="min-w-0">
        <span className="block truncate font-display text-base font-semibold tracking-tight">
          Greenlight LED
        </span>
        <span className="block text-[10px] font-semibold uppercase tracking-[0.18em] opacity-60">
          Accessories
        </span>
      </span>
    </span>
  );
}
