import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Sparkles, Loader2 } from "lucide-react";
import { useAuthStore } from "@/lib/auth-store";
import { api, apiErrorMessage } from "@/lib/api";
import { toast } from "sonner";
import Scene3DBackground from "@/components/Scene3DBackground";

export default function LoginPage() {
  const navigate = useNavigate();

  const setTokens = useAuthStore((s) => s.setTokens);
  const setUser = useAuthStore((s) => s.setUser);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();

    if (loading) {
      return;
    }

    setLoading(true);

    try {
      const normalizedEmail = email.trim().toLowerCase();

      // Login through the configured API client.
      // In production this goes to:
      // VITE_API_URL/api/v1/auth/login
      const { data: tokens } = await api.post("/auth/login", {
        email: normalizedEmail,
        password,
      });

      if (!tokens?.access_token || !tokens?.refresh_token) {
        throw new Error("Authentication tokens were not returned.");
      }

      setTokens(tokens.access_token, tokens.refresh_token);

      // Fetch the authenticated user using the same API client.
      // The Authorization header is added automatically by api.ts.
      const { data: user } = await api.get("/auth/me");

      setUser(user);

      toast.success("Welcome back!");

      navigate("/");
    } catch (err) {
      console.error("Login failed:", err);

      toast.error(
        apiErrorMessage(err, "Couldn't sign you in. Please check your email and password.")
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
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
            Welcome back
          </h1>

          <p className="mb-6 text-sm text-ink-muted">
            Sign in to your command center.
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs text-ink-muted">
                Email
              </label>

              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
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
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-lg border border-base-border bg-base-panel-2/60 px-3 py-2 text-sm text-ink focus:border-accent-violet/50 focus:outline-none"
                placeholder="••••••••"
                autoComplete="current-password"
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

              {loading ? "Signing in..." : "Sign in"}
            </button>
          </form>
        </div>

        <p className="mt-4 text-center text-sm text-ink-muted">
          New here?{" "}
          <Link
            to="/register"
            className="text-accent-violet hover:underline"
          >
            Create an account
          </Link>
        </p>
      </div>
    </div>
  );
}