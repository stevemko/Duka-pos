/* oxlint-disable react/only-export-components */
import { useEffect } from "react";
import Icon from "./Icon";

export function cn(...values) {
  return values.filter(Boolean).join(" ");
}

const buttonVariants = {
  primary:
    "bg-ink-950 text-white shadow-sm hover:bg-ink-800 active:bg-ink-900 disabled:bg-ink-300",
  brand:
    "bg-brand-600 text-white shadow-sm hover:bg-brand-700 active:bg-brand-800 disabled:bg-brand-300",
  secondary:
    "border border-ink-200 bg-white text-ink-700 shadow-sm hover:border-ink-300 hover:bg-ink-50 disabled:text-ink-400",
  ghost: "text-ink-600 hover:bg-ink-100 hover:text-ink-900 disabled:text-ink-300",
  danger:
    "bg-red-600 text-white shadow-sm hover:bg-red-700 active:bg-red-800 disabled:bg-red-300",
  dangerGhost: "text-red-600 hover:bg-red-50 disabled:text-red-300",
};

const buttonSizes = {
  sm: "h-8 gap-1.5 px-3 text-xs",
  md: "h-10 gap-2 px-4 text-sm",
  lg: "h-11 gap-2 px-5 text-sm",
};

export function Button({
  variant = "primary",
  size = "md",
  icon,
  iconRight,
  loading = false,
  className = "",
  children,
  type = "button",
  disabled = false,
  ...props
}) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex select-none items-center justify-center rounded-xl font-semibold transition-colors disabled:cursor-not-allowed",
        buttonVariants[variant],
        buttonSizes[size],
        className,
      )}
      {...props}
      disabled={loading || disabled}
    >
      {loading ? (
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
      ) : (
        icon && <Icon name={icon} size={size === "sm" ? 15 : 17} />
      )}
      {children}
      {iconRight && <Icon name={iconRight} size={size === "sm" ? 15 : 17} />}
    </button>
  );
}

export function IconButton({ icon, label, variant = "ghost", className = "", ...props }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={cn(
        "inline-flex h-9 w-9 items-center justify-center rounded-xl transition-colors disabled:cursor-not-allowed",
        buttonVariants[variant],
        className,
      )}
      {...props}
    >
      <Icon name={icon} size={18} />
    </button>
  );
}

export function Card({ className = "", surface = "bg-white", children, ...props }) {
  return (
    <section
      // Tailwind sorts bg-white after the custom colours, so a tinted card has to
      // replace the default surface instead of losing to it in the class list.
      className={cn("rounded-2xl border border-ink-200/70 shadow-card", surface, className)}
      {...props}
    >
      {children}
    </section>
  );
}

export function CardHeader({ title, subtitle, action, icon, className = "" }) {
  return (
    <div className={cn("flex flex-wrap items-start justify-between gap-3 px-5 pt-5", className)}>
      <div className="flex min-w-0 items-start gap-3">
        {icon && (
          <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-ink-100 text-ink-600">
            <Icon name={icon} size={18} />
          </span>
        )}
        <div className="min-w-0">
          <h2 className="font-display text-base font-semibold tracking-tight text-ink-950">
            {title}
          </h2>
          {subtitle && <p className="mt-0.5 text-sm text-ink-500">{subtitle}</p>}
        </div>
      </div>
      {action}
    </div>
  );
}

export function PageHeader({ eyebrow, title, subtitle, actions, children }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && (
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-brand-700">
            {eyebrow}
          </p>
        )}
        <h1 className="mt-1 font-display text-2xl font-semibold tracking-tight text-ink-950 sm:text-[1.7rem]">
          {title}
        </h1>
        {subtitle && <p className="mt-1 max-w-2xl text-sm text-ink-500">{subtitle}</p>}
        {children}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

const badgeTones = {
  neutral: "bg-ink-100 text-ink-700",
  brand: "bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-200",
  success: "bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200",
  warning: "bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-200",
  danger: "bg-red-50 text-red-700 ring-1 ring-inset ring-red-200",
  info: "bg-sky-50 text-sky-700 ring-1 ring-inset ring-sky-200",
};

export function Badge({ tone = "neutral", children, className = "", dot = false }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-semibold capitalize",
        badgeTones[tone],
        className,
      )}
    >
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

export function statusTone(status) {
  switch (status) {
    case "paid":
    case "succeeded":
      return "success";
    case "partially_paid":
      return "warning";
    case "on_credit":
      return "danger";
    case "payment_pending":
    case "pending":
      return "info";
    default:
      return "neutral";
  }
}

export function statusLabel(status = "") {
  return status.replaceAll("_", " ");
}

export const inputClass =
  "h-10 w-full rounded-xl border border-ink-200 bg-white px-3 text-sm text-ink-900 shadow-sm transition placeholder:text-ink-400 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-100 disabled:bg-ink-50 disabled:text-ink-400";

export function Field({ label, hint, error, required, children, className = "" }) {
  return (
    <label className={cn("block", className)}>
      {label && (
        <span className="mb-1.5 flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-ink-500">
          {label}
          {required && <span className="text-red-500">*</span>}
        </span>
      )}
      {children}
      {error ? (
        <span className="mt-1 block text-xs font-medium text-red-600">{error}</span>
      ) : (
        hint && <span className="mt-1 block text-xs text-ink-400">{hint}</span>
      )}
    </label>
  );
}

export function Input({ className = "", ...props }) {
  return <input className={cn(inputClass, className)} {...props} />;
}

export function Select({ className = "", children, ...props }) {
  return (
    <select className={cn(inputClass, "appearance-none pr-8", className)} {...props}>
      {children}
    </select>
  );
}

export function Textarea({ className = "", ...props }) {
  return (
    <textarea
      className={cn(inputClass, "h-auto min-h-20 py-2.5 leading-relaxed", className)}
      {...props}
    />
  );
}

export function SearchInput({
  value,
  onChange,
  placeholder = "Search...",
  className = "",
  inputClassName = "",
  ...props
}) {
  return (
    <div className={cn("relative", className)}>
      <Icon
        name="search"
        size={16}
        className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-400"
      />
      <input
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className={cn(inputClass, "pl-9", inputClassName)}
        {...props}
      />
    </div>
  );
}

const alertTones = {
  error: {
    wrapper: "border-red-200 bg-red-50 text-red-800",
    icon: "alert",
    iconClass: "text-red-600",
  },
  success: {
    wrapper: "border-emerald-200 bg-emerald-50 text-emerald-800",
    icon: "checkCircle",
    iconClass: "text-emerald-600",
  },
  warning: {
    wrapper: "border-amber-200 bg-amber-50 text-amber-800",
    icon: "alert",
    iconClass: "text-amber-600",
  },
  info: {
    wrapper: "border-sky-200 bg-sky-50 text-sky-800",
    icon: "spark",
    iconClass: "text-sky-600",
  },
};

export function Alert({ tone = "error", title, children, className = "", onClose }) {
  const style = alertTones[tone] || alertTones.error;
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={cn(
        "flex items-start gap-3 rounded-xl border px-4 py-3 text-sm",
        style.wrapper,
        className,
      )}
    >
      <Icon name={style.icon} size={18} className={cn("mt-0.5 shrink-0", style.iconClass)} />
      <div className="min-w-0 flex-1">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className={cn(title && "mt-0.5")}>{children}</div>}
      </div>
      {onClose && (
        <button
          type="button"
          onClick={onClose}
          className="rounded-md p-0.5 opacity-60 transition hover:opacity-100"
          aria-label="Dismiss"
        >
          <Icon name="close" size={16} />
        </button>
      )}
    </div>
  );
}

export function Modal({ open, onClose, title, subtitle, children, footer, size = "md" }) {
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event) => {
      if (event.key === "Escape") onClose?.();
    };
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [open, onClose]);

  if (!open) return null;

  const widths = {
    sm: "max-w-md",
    md: "max-w-xl",
    lg: "max-w-3xl",
    xl: "max-w-5xl",
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-6">
      <div
        className="absolute inset-0 bg-ink-950/50 backdrop-blur-[2px]"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cn(
          "animate-rise relative flex max-h-[92vh] w-full flex-col overflow-hidden rounded-t-2xl bg-white shadow-float sm:rounded-2xl",
          widths[size],
        )}
      >
        <div className="flex items-start justify-between gap-3 border-b border-ink-100 px-5 py-4">
          <div className="min-w-0">
            <h2 className="font-display text-lg font-semibold text-ink-950">{title}</h2>
            {subtitle && <p className="mt-0.5 text-sm text-ink-500">{subtitle}</p>}
          </div>
          <IconButton icon="close" label="Close" onClick={onClose} />
        </div>
        <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && (
          <div className="flex flex-wrap justify-end gap-2 border-t border-ink-100 bg-ink-50/60 px-5 py-3">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}

export function EmptyState({ icon = "package", title, message, action, className = "" }) {
  return (
    <div className={cn("flex flex-col items-center justify-center px-6 py-12 text-center", className)}>
      <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-ink-100 text-ink-400">
        <Icon name={icon} size={22} />
      </span>
      <p className="mt-3 text-sm font-semibold text-ink-800">{title}</p>
      {message && <p className="mt-1 max-w-sm text-sm text-ink-500">{message}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Spinner({ label = "Loading", className = "" }) {
  return (
    <div className={cn("flex items-center justify-center gap-3 py-12 text-sm text-ink-500", className)}>
      <span className="h-5 w-5 animate-spin rounded-full border-2 border-ink-300 border-t-brand-600" />
      {label}
    </div>
  );
}

export function StatCard({ label, value, hint, icon, tone = "neutral", emphasis = false }) {
  const tones = {
    neutral: "bg-ink-100 text-ink-600",
    brand: "bg-brand-100 text-brand-700",
    success: "bg-emerald-100 text-emerald-700",
    warning: "bg-amber-100 text-amber-700",
    danger: "bg-red-100 text-red-600",
    info: "bg-sky-100 text-sky-700",
  };
  return (
    <div
      className={cn(
        "rounded-2xl border p-4 shadow-card",
        // One background per card: cn() only joins, so a base bg-white and an
        // emphasised bg-ink-950 in the same list let whichever Tailwind sorts
        // later win - the emphasised number came out white on white.
        emphasis ? "border-ink-950 bg-ink-950 text-white" : "border-ink-200/70 bg-white",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <p
          className={cn(
            "text-xs font-semibold uppercase tracking-wide",
            emphasis ? "text-white/60" : "text-ink-500",
          )}
        >
          {label}
        </p>
        {icon && (
          <span
            className={cn(
              "flex h-8 w-8 items-center justify-center rounded-xl",
              emphasis ? "bg-white/10 text-brand-300" : tones[tone],
            )}
          >
            <Icon name={icon} size={16} />
          </span>
        )}
      </div>
      <p
        className={cn(
          "tabular mt-3 font-display text-xl font-semibold tracking-tight sm:text-2xl",
          emphasis ? "text-white" : "text-ink-950",
        )}
      >
        {value}
      </p>
      {hint && (
        <p className={cn("mt-1 text-xs", emphasis ? "text-white/60" : "text-ink-400")}>{hint}</p>
      )}
    </div>
  );
}

export function TableShell({ children, minWidth = "720px", className = "" }) {
  return (
    <div className={cn("scrollbar-thin overflow-x-auto", className)}>
      <table className="w-full text-left text-sm" style={{ minWidth }}>
        {children}
      </table>
    </div>
  );
}

export function Th({ children, align = "left", className = "" }) {
  return (
    <th
      className={cn(
        "whitespace-nowrap border-b border-ink-100 px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-ink-400",
        align === "right" ? "text-right" : "text-left",
        className,
      )}
    >
      {children}
    </th>
  );
}

export function Td({ children, align = "left", className = "", colSpan }) {
  return (
    <td
      colSpan={colSpan}
      className={cn(
        "border-b border-ink-100/80 px-4 py-3 text-ink-700",
        align === "right" && "text-right",
        className,
      )}
    >
      {children}
    </td>
  );
}

export function Tabs({ items, value, onChange, className = "" }) {
  return (
    <div
      className={cn(
        "no-scrollbar flex gap-1 overflow-x-auto rounded-xl bg-ink-100/80 p-1",
        className,
      )}
    >
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          onClick={() => onChange(item.id)}
          className={cn(
            "inline-flex shrink-0 items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-semibold transition",
            value === item.id
              ? "bg-white text-ink-950 shadow-sm"
              : "text-ink-500 hover:text-ink-800",
          )}
        >
          {item.label}
          {item.count !== undefined && (
            <span
              className={cn(
                "rounded-full px-1.5 py-0.5 text-[10px] font-bold tabular",
                value === item.id ? "bg-ink-100 text-ink-600" : "bg-ink-200/70 text-ink-500",
              )}
            >
              {item.count}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

export function Avatar({ name = "", className = "" }) {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
  return (
    <span
      className={cn(
        "flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-ink-900 text-xs font-bold text-white",
        className,
      )}
    >
      {initials || "?"}
    </span>
  );
}

export function Divider({ className = "" }) {
  return <div className={cn("h-px w-full bg-ink-100", className)} />;
}
