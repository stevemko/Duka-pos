import { useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { authApi } from "../api/client";
import Icon from "./Icon";
import { BrandLockup } from "./Brand";
import {
  Avatar,
  Button,
  Field,
  Input,
  Modal,
  cn,
} from "./ui";

const navGroups = [
  {
    label: "Operations",
    items: [
      { to: "/", label: "Sell", icon: "cart", end: true },
      { to: "/transactions", label: "Transactions", icon: "receipt" },
      { to: "/credit", label: "Credit book", icon: "users" },
      { to: "/inventory", label: "Inventory", icon: "package" },
    ],
  },
  {
    label: "Insights",
    items: [{ to: "/dashboard", label: "Dashboard", icon: "dashboard" }],
  },
  {
    label: "Management",
    managerOnly: true,
    items: [
      { to: "/expenses", label: "Expenses", icon: "wallet" },
      {
        to: "/team",
        label: "Branches",
        superLabel: "Team & branches",
        icon: "users",
        superIcon: "shield",
      },
    ],
  },
];

function NavItems({ onNavigate }) {
  const { canManage, canManageUsers } = useAuth();
  return (
    <nav className="flex flex-1 flex-col gap-5 overflow-y-auto px-3 py-4">
      {navGroups
        .filter((group) => !group.managerOnly || canManage)
        .map((group) => (
          <div key={group.label}>
            <p className="px-3 pb-2 text-[10px] font-bold uppercase tracking-[0.18em] text-white/35">
              {group.label}
            </p>
            <div className="space-y-1">
              {group.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  onClick={onNavigate}
                  className={({ isActive }) =>
                    cn(
                      "group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold transition",
                      isActive
                        ? "bg-white/10 text-white shadow-[inset_2px_0_0_var(--color-brand-400)]"
                        : "text-white/55 hover:bg-white/5 hover:text-white",
                    )
                  }
                >
                  {({ isActive }) => (
                    <>
                      <Icon
                        name={
                          canManageUsers && item.superIcon ? item.superIcon : item.icon
                        }
                        size={18}
                        className={isActive ? "text-brand-300" : "text-white/40 group-hover:text-white/80"}
                      />
                      {canManageUsers && item.superLabel ? item.superLabel : item.label}
                    </>
                  )}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
    </nav>
  );
}

function BranchSwitcher({ compact = false }) {
  const {
    branches,
    activeBranch,
    activeBranchId,
    setActiveBranchId,
    canViewAllBranches,
    user,
  } = useAuth();

  if (!branches.length) return null;

  if (!canViewAllBranches) {
    return (
      <div
        className={cn(
          "flex items-center gap-2 rounded-xl border border-ink-200 bg-white px-3 text-sm text-ink-600",
          compact ? "h-9" : "h-10",
        )}
      >
        <Icon name="store" size={16} className="text-ink-400" />
        <span className="max-w-32 truncate font-semibold text-ink-800">
          {activeBranch?.name || user?.branch?.name || "Main shop"}
        </span>
      </div>
    );
  }

  return (
    <label className="relative flex items-center">
      <Icon
        name="store"
        size={16}
        className="pointer-events-none absolute left-3 z-10 text-ink-400"
      />
      <select
        value={activeBranchId}
        onChange={(event) => setActiveBranchId(event.target.value)}
        aria-label="Active branch"
        className={cn(
          "appearance-none rounded-xl border border-ink-200 bg-white pl-9 pr-9 text-sm font-semibold text-ink-800 shadow-sm transition hover:border-ink-300 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-100",
          compact ? "h-9" : "h-10",
        )}
      >
        {canViewAllBranches && <option value="all">All branches</option>}
        {branches.map((branch) => (
          <option key={branch.id} value={branch.id}>
            {branch.name}
            {branch.is_active ? "" : " (closed)"}
          </option>
        ))}
      </select>
      <Icon
        name="chevronDown"
        size={14}
        className="pointer-events-none absolute right-3 text-ink-400"
      />
    </label>
  );
}

function Sidebar({ onNavigate }) {
  const { canManage, idleMinutes, user } = useAuth();
  const roleLabel = user?.is_superuser
    ? "super admin"
    : user?.role || (canManage ? "manager" : "cashier");
  return (
    <div className="flex h-full flex-col bg-ink-950 bg-[radial-gradient(circle_at_top_left,rgba(16,185,129,0.16),transparent_55%)]">
      <Link
        to="/"
        onClick={onNavigate}
        className="flex items-center px-4 pb-4 pt-5 text-white"
        aria-label="Greenlight LED Accessories home"
      >
        <BrandLockup />
      </Link>

      <NavItems onNavigate={onNavigate} />

      <div className="border-t border-white/10 p-3">
        <div className="flex items-center gap-2 rounded-xl bg-white/5 p-2">
          <Avatar name={user?.full_name || user?.username || "User"} className="bg-white/10" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-white">
              {user?.full_name || user?.username || "User"}
            </p>
            <p className="text-[11px] capitalize text-white/40">{roleLabel}</p>
          </div>
        </div>
        <p className="mt-2 px-1 text-[10px] text-white/30">
          Auto-locks after {idleMinutes} min idle
        </p>
      </div>
    </div>
  );
}

export default function Layout() {
  const { user, logout } = useAuth();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const location = useLocation();

  return (
    <div className="min-h-screen bg-ink-50">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 lg:block">
        <Sidebar />
      </aside>

      {drawerOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div
            className="absolute inset-0 bg-ink-950/60"
            onClick={() => setDrawerOpen(false)}
            aria-hidden="true"
          />
          <div className="animate-rise absolute inset-y-0 left-0 w-72 shadow-float">
            <Sidebar onNavigate={() => setDrawerOpen(false)} />
          </div>
        </div>
      )}

      <div className="lg:pl-64">
        <header className="sticky top-0 z-20 border-b border-ink-200/70 bg-ink-50/85 backdrop-blur-md">
          <div className="mx-auto flex h-16 max-w-[1440px] items-center gap-3 px-4 sm:px-6">
            <button
              type="button"
              onClick={() => setDrawerOpen(true)}
              className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-ink-200 bg-white text-ink-700 lg:hidden"
              aria-label="Open menu"
            >
              <Icon name="menu" size={18} />
            </button>

            <div className="lg:hidden">
              <p className="font-display text-sm font-semibold text-ink-950">Greenlight LED</p>
              <p className="text-[10px] uppercase tracking-wider text-ink-400">
                {location.pathname === "/"
                  ? "Sell"
                  : location.pathname.replace("/", "").replace("-", " ")}
              </p>
            </div>

            <div className="ml-auto flex items-center gap-2">
              <div className="hidden sm:block">
                <BranchSwitcher compact />
              </div>
              <button
                type="button"
                onClick={() => setPasswordOpen(true)}
                className="hidden h-9 items-center gap-2 rounded-xl border border-ink-200 bg-white px-3 text-xs font-semibold text-ink-600 shadow-sm transition hover:border-ink-300 hover:text-ink-900 sm:inline-flex"
                title="Change your password"
              >
                <Icon name="lock" size={14} />
                Password
              </button>
              <div className="flex items-center gap-2 rounded-xl border border-ink-200 bg-white py-1 pl-1 pr-2 shadow-sm">
                <Avatar name={user?.full_name || user?.username} className="h-7 w-7 text-[10px]" />
                <div className="hidden leading-tight sm:block">
                  <p className="max-w-28 truncate text-xs font-bold text-ink-900">
                    {user?.full_name || user?.username}
                  </p>
                  <p className="text-[10px] capitalize text-ink-400">
                    {user?.is_superuser ? "super admin" : user?.role || "cashier"}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={logout}
                className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-ink-200 bg-white text-ink-500 shadow-sm transition hover:border-red-200 hover:bg-red-50 hover:text-red-600"
                aria-label="Sign out"
                title="Sign out"
              >
                <Icon name="logout" size={16} />
              </button>
            </div>
          </div>
          <div className="border-t border-ink-200/60 px-4 pb-2 sm:hidden">
            <BranchSwitcher compact />
          </div>
        </header>

        <main className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6 lg:py-8">
          <Outlet />
        </main>
      </div>

      <PasswordDialog open={passwordOpen} onClose={() => setPasswordOpen(false)} />
    </div>
  );
}

function PasswordDialog({ open, onClose }) {
  const { user } = useAuth();
  const [form, setForm] = useState({ current: "", next: "", confirm: "" });
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setError("");
    setSuccess("");
    if (!form.current || !form.next) {
      setError("Fill in all password fields.");
      return;
    }
    if (form.next !== form.confirm) {
      setError("The new passwords do not match.");
      return;
    }
    if (form.next.length < 8) {
      setError("The new password must be at least 8 characters.");
      return;
    }
    setSaving(true);
    try {
      const response = await authApi.changePassword({
        current_password: form.current,
        new_password: form.next,
      });
      localStorage.setItem("duka_pos_token", response.token);
      setForm({ current: "", next: "", confirm: "" });
      setSuccess("Password updated. Use the new password next time you sign in.");
    } catch (requestError) {
      setError(
        requestError.response?.data?.current_password?.[0] ||
          requestError.response?.data?.new_password?.[0] ||
          "Could not change the password.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Change password"
      subtitle={`Signed in as ${user?.username || "user"}`}
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={saving} onClick={submit} type="submit" form="change-password-form">
            Update password
          </Button>
        </>
      }
    >
      <form id="change-password-form" onSubmit={submit} className="space-y-3">
        <Field label="Current password" required>
          <Input
            type="password"
            autoComplete="current-password"
            value={form.current}
            onChange={(event) => setForm({ ...form, current: event.target.value })}
          />
        </Field>
        <Field label="New password" required hint="At least 8 characters.">
          <Input
            type="password"
            autoComplete="new-password"
            value={form.next}
            onChange={(event) => setForm({ ...form, next: event.target.value })}
          />
        </Field>
        <Field label="Confirm new password" required>
          <Input
            type="password"
            autoComplete="new-password"
            value={form.confirm}
            onChange={(event) => setForm({ ...form, confirm: event.target.value })}
          />
        </Field>
        {error && <p className="text-sm font-medium text-red-600">{error}</p>}
        {success && (
          <div className="flex items-center gap-2 rounded-xl bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
            <Icon name="checkCircle" size={16} />
            {success}
          </div>
        )}
      </form>
    </Modal>
  );
}
