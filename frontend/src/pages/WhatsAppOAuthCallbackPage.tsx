import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { toast } from "sonner";
import { api, apiErrorMessage } from "@/lib/api";

export default function WhatsAppOAuthCallbackPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState<"working" | "success" | "error">("working");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const code = searchParams.get("code");

    if (!code) {
      setStatus("error");
      setError(
        "Meta didn't return an authorization code — the signup flow may have been cancelled."
      );
      return;
    }

    const redirectUri = `${window.location.origin}/integrations/whatsapp/callback`;

    api
      .post("/integrations/whatsapp/oauth/callback", {
        code,
        redirect_uri: redirectUri,
      })
      .then(() => {
        setStatus("success");
        toast.success("WhatsApp connected");

        setTimeout(() => {
          navigate("/integrations", { replace: true });
        }, 1200);
      })
      .catch((err) => {
        setStatus("error");
        setError(
          apiErrorMessage(
            err,
            "Couldn't complete the WhatsApp connection"
          )
        );
      });
  }, [searchParams, navigate]);

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="panel panel-glow w-full max-w-sm p-8 text-center">
        {status === "working" && (
          <>
            <Loader2 className="mx-auto h-8 w-8 animate-spin text-accent-violet" />

            <h1 className="mt-4 font-display text-lg font-semibold">
              Connecting WhatsApp…
            </h1>

            <p className="mt-1 text-sm text-ink-muted">
              Finishing up with Meta.
            </p>
          </>
        )}

        {status === "success" && (
          <>
            <CheckCircle2 className="mx-auto h-8 w-8 text-accent-green" />

            <h1 className="mt-4 font-display text-lg font-semibold">
              WhatsApp connected!
            </h1>

            <p className="mt-1 text-sm text-ink-muted">
              Taking you back to Integrations…
            </p>
          </>
        )}

        {status === "error" && (
          <>
            <XCircle className="mx-auto h-8 w-8 text-accent-pink" />

            <h1 className="mt-4 font-display text-lg font-semibold">
              Connection failed
            </h1>

            <p className="mt-1 text-sm text-ink-muted">
              {error}
            </p>

            <Link
              to="/integrations"
              className="mt-5 inline-block rounded-lg border border-base-border px-4 py-2 text-sm text-ink-muted hover:text-ink"
            >
              Back to Integrations
            </Link>
          </>
        )}
      </div>
    </div>
  );
}