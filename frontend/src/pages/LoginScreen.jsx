import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import Icon from "../components/Icon";
import { BrandLockup, BrandMark } from "../components/Brand";
import { Alert, Button, Field, Input } from "../components/ui";

const SHOP_WEBSITE = (import.meta.env.VITE_SHOP_WEBSITE || "greenlightledaccessories.com").trim();

const highlights = [
  {
    icon: "cart",
    title: "Fast counter checkout",
    text: "Barcode-style search, tap-to-add baskets and instant receipts for a 1000+ item catalog.",
  },
  {
    icon: "receipt",
    title: "Every shilling recorded",
    text: "Daily sales, M-Pesa confirmations, credits and expenses in one read-only ledger.",
  },
  {
    icon: "bank",
    title: "Paybill ready",
    text: "M-Pesa Paybill and STK payments reconcile to the receipt and the daily records.",
  },
];

export default function LoginScreen() {
  const { login, isAuthenticated, workspaceLoading } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (isAuthenticated && !workspaceLoading) {
      navigate("/", { replace: true });
    }
  }, [isAuthenticated, workspaceLoading, navigate]);

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError("");

    if (!username.trim() || !password) {
      setError("Enter your username and password.");
      return;
    }

    setSubmitting(true);
    try {
      await login(username.trim(), password);
      navigate(location.state?.from || "/", { replace: true });
    } catch (requestError) {
      setError(
        requestError.response?.data?.detail ||
          "Unable to sign in. Check your username and password.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="grid min-h-screen bg-ink-50 lg:grid-cols-[1.05fr_1fr]">
      <aside className="relative hidden overflow-hidden bg-ink-950 p-10 text-white lg:flex lg:flex-col lg:justify-between xl:p-14">
        <div
          className="pointer-events-none absolute inset-0 opacity-80"
          style={{
            background:
              "radial-gradient(900px circle at 10% 0%, rgba(16,185,129,0.22), transparent 55%), radial-gradient(700px circle at 100% 100%, rgba(5,150,105,0.18), transparent 50%)",
          }}
        />
        <div className="relative">
          <div className="flex items-center text-white">
            <BrandLockup />
          </div>

          <h1 className="mt-14 max-w-lg font-display text-4xl font-semibold leading-[1.15] tracking-tight xl:text-5xl">
            Run the counter,
            <span className="block text-brand-300">know the numbers.</span>
          </h1>
          <p className="mt-4 max-w-md text-sm leading-relaxed text-white/60">
            One secure system for Greenlight LED Accessories — sales, stock, credit,
            M-Pesa Paybill and expenses, recorded cleanly every single day.
          </p>

          <div className="mt-10 space-y-5">
            {highlights.map((item) => (
              <div key={item.title} className="flex gap-3">
                <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white/10 text-brand-300">
                  <Icon name={item.icon} size={18} />
                </span>
                <div>
                  <p className="text-sm font-semibold">{item.title}</p>
                  <p className="text-sm text-white/50">{item.text}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <p className="relative text-xs text-white/35">
          Secure sign-in · Super-admin accounts · Branch-aware records
          {SHOP_WEBSITE ? ` · ${SHOP_WEBSITE}` : ""}
        </p>
      </aside>

      <main className="flex min-h-screen items-center justify-center px-5 py-10 sm:px-8">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-3 text-ink-950 lg:hidden">
            <BrandMark size={44} />
            <div>
              <p className="font-display text-lg font-semibold text-ink-950">Greenlight LED</p>
              <p className="text-xs text-ink-400">Accessories · Point of sale</p>
            </div>
          </div>

          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-brand-700">
            Welcome back
          </p>
          <h2 className="mt-1 font-display text-2xl font-semibold tracking-tight text-ink-950">
            Sign in to Greenlight LED
          </h2>
          <p className="mt-1 text-sm text-ink-500">
            Use the username and password the super admin created for you.
          </p>

          <form onSubmit={handleSubmit} className="mt-7 space-y-4">
            <Field label="Username" required>
              <Input
                type="text"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                autoComplete="username"
                autoFocus
                disabled={submitting}
                placeholder="e.g. amina"
                className="h-11"
              />
            </Field>

            <Field label="Password" required>
              <div className="relative">
                <Input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete="current-password"
                  disabled={submitting}
                  placeholder="Enter your password"
                  className="h-11 pr-11"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((value) => !value)}
                  className="absolute right-1.5 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg text-ink-400 transition hover:bg-ink-100 hover:text-ink-700"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  <Icon name="eye" size={17} />
                </button>
              </div>
            </Field>

            {error && <Alert tone="error">{error}</Alert>}

            <Button
              type="submit"
              size="lg"
              variant="brand"
              loading={submitting}
              className="w-full"
            >
              {submitting ? "Signing in..." : "Sign in"}
            </Button>
          </form>

          <div className="mt-8 flex items-start gap-2 rounded-xl border border-ink-200 bg-white px-3 py-2.5 text-xs text-ink-500 shadow-sm">
            <Icon name="shield" size={15} className="mt-0.5 shrink-0 text-brand-600" />
            The super admin creates accounts and resets passwords. Managers oversee the shop.
            Ask the super admin if you cannot sign in.
          </div>
        </div>
      </main>
    </div>
  );
}
