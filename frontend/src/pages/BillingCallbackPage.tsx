import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, Loader2, Clock } from "lucide-react";
import { api } from "@/lib/api";
import type { Subscription } from "@/types";

const POLL_INTERVAL_MS = 2500;
const MAX_POLLS = 12;

export default function BillingCallbackPage() {
  const [status, setStatus] = useState<"waiting" | "active" | "timeout">("waiting");

  useEffect(() => {
    let cancelled = false;
    let attempts = 0;

    async function poll() {
      try {
        const { data } = await api.get<Subscription | null>("/billing/subscription");
        if (cancelled) return;
        if (data?.status === "active") {
          setStatus("active");
          return;
        }
      } catch {
        // keep polling — a transient error here shouldn't end the flow early
      }

      attempts += 1;
      if (attempts >= MAX_POLLS) {
        if (!cancelled) setStatus("timeout");
        return;
      }
      setTimeout(poll, POLL_INTERVAL_MS);
    }

    poll();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="panel panel-glow w-full max-w-sm p-8 text-center">
        {status === "waiting" && (
          <>
            <Loader2 className="mx-auto h-8 w-8 animate-spin text-accent-violet" />
            <h1 className="mt-4 font-display text-lg font-semibold">Confirming your payment…</h1>
            <p className="mt-1 text-sm text-ink-muted">This usually takes a few seconds.</p>
          </>
        )}
        {status === "active" && (
          <>
            <CheckCircle2 className="mx-auto h-8 w-8 text-accent-green" />
            <h1 className="mt-4 font-display text-lg font-semibold">You're subscribed!</h1>
            <p className="mt-1 text-sm text-ink-muted">Your plan is now active.</p>
            <Link
              to="/billing"
              className="mt-5 inline-block rounded-lg bg-gradient-to-r from-accent-violet to-accent-blue px-4 py-2 text-sm font-medium text-white hover:opacity-90"
            >
              Back to Billing
            </Link>
          </>
        )}
        {status === "timeout" && (
          <>
            <Clock className="mx-auto h-8 w-8 text-accent-amber" />
            <h1 className="mt-4 font-display text-lg font-semibold">Still processing</h1>
            <p className="mt-1 text-sm text-ink-muted">
              Your payment may have gone through, but confirmation is taking longer than usual. Check the Billing
              page in a moment.
            </p>
            <Link
              to="/billing"
              className="mt-5 inline-block rounded-lg border border-base-border px-4 py-2 text-sm text-ink-muted hover:text-ink"
            >
              Go to Billing
            </Link>
          </>
        )}
      </div>
    </div>
  );
}
