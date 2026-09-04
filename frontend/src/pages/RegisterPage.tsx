import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Sparkles, Loader2 } from "lucide-react";
import { useAuthStore } from "@/lib/auth-store";
import { api, apiErrorMessage } from "@/lib/api";
import { toast } from "sonner";
import Scene3DBackground from "@/components/Scene3DBackground";
export default function RegisterPage() {
  const navigate = useNavigate();
  const setTokens = useAuthStore((s) => s.setTokens);
  const setUser = useAuthStore((s) => s.setUser);
  const [form, setForm] = useState({
    full_name: "",
    business_name: "",
    email: "",
    password: "",
  });
  const [loading, setLoading] = useState(false);
  function update<K extends keyof typeof form>(key: K, value: string) {
    setForm((current) => ({
      ...current,
      [key]: value,
    }));
  }
  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (loading) {
      return;
    }
    setLoading(true);
    try {
      // Register the account through the configured API client.
      // In production this uses:
      // VITE_API_URL + /api/v1
      await api.post("/auth/register", {
        full_name: form.full_name.trim(),
        business_name: form.business_name.trim() || null,
        email: form.email.trim().toLowerCase(),
        password: form.password,
      });
      // Automatically log the user in after successful registration.
      const { data: tokens } = await api.post("/auth/login", {
        email: form.email.trim().toLowerCase(),
        password: form.password,
      });
      if (!tokens?.access_token || !tokens?.refresh_token) {
        throw new Error("Authentication tokens were not returned.");
      }
      setTokens(tokens.access_token, tokens.refresh_token);
      // Fetch the authenticated user's profile.
      // The api interceptor automatically adds the Bearer token.
      const { data: user } = await api.get("/auth/me");
      setUser(user);
      toast.success("Account created — your default agents are ready.");
      navigate("/");
    } catch (err) {
      console.error("Registration failed:", err);
      toast.error(
        apiErrorMessage(err, "Couldn't create your account. Please try again.")
      );
    } finally {
      setLoading(false);
    }
  }
  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-10">
      <Scene3DBackground />
      <div className="w-full max-w-sm">
        <div className="mb-8 flex items-center justify-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-accent-violet to-accent-blue">
            <Sparkles className="h-4 w-4 text-white" />
          </div>
          <span className="font-display text-xl font-semibold">
            PersonaAI
          </span>
        </div>
        <div className="panel panel-glow p-6">
          <h1 className="mb-1 font-display text-lg font-semibold">
            Create your AI team
          </h1>
          <p className="mb-6 text-sm text-ink-muted">
            You'll get four agents ready to go: Personal, Sales, Support, and
            Opportunity.
          </p>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs text-ink-muted">
                Your name
              </label>
              <input
                required
                value={form.full_name}
                onChange={(e) => update("full_name", e.target.value)}
                className="w-full rounded-lg border border-base-border bg-base-panel-2/60 px-3 py-2 text-sm text-ink focus:border-accent-violet/50 focus:outline-none"
                placeholder="Ada Founder"
                autoComplete="name"
                disabled={loading}
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs text-ink-muted">
                Business name (optional)
              </label>
              <input
                value={form.business_name}
                onChange={(e) => update("business_name", e.target.value)}
                className="w-full rounded-lg border border-base-border bg-base-panel-2/60 px-3 py-2 text-sm text-ink focus:border-accent-violet/50 focus:outline-none"
                placeholder="Ada's Studio"
                autoComplete="organization"
                disabled={loading}
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs text-ink-muted">
                Email
              </label>
              <input
                type="email"
                required
                value={form.email}
                onChange={(e) => update("email", e.target.value)}
                className="w-full rounded-lg border border-base-border bg-base-panel-2/60 px-3 py-2 text-sm text-ink focus:border-accent-violet/50 focus:outline-none"
                placeholder="you@business.com"
                autoComplete="email"
                disabled={loading}
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs text-ink-muted">
                Password
              </label>
              <input
                type="password"
                required
                minLength={8}
                value={form.password}
                onChange={(e) => update("password", e.target.value)}
                className="w-full rounded-lg border border-base-border bg-base-panel-2/60 px-3 py-2 text-sm text-ink focus:border-accent-violet/50 focus:outline-none"
                placeholder="At least 8 characters, 1 uppercase, 1 number"
                autoComplete="new-password"
                disabled={loading}
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-accent-violet to-accent-blue px-4 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}
              {loading ? "Creating account..." : "Create account"}
            </button>
          </form>
        </div>
        <p className="mt-4 text-center text-sm text-ink-muted">
          Already have an account?{" "}
          <Link
            to="/login"
            className="text-accent-violet hover:underline"
          >
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}