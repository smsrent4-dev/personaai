import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, MessageCircle, RefreshCw, Settings2, X } from "lucide-react";
import { toast } from "sonner";
import { formatDistanceToNow } from "date-fns";
import { api, apiErrorMessage } from "@/lib/api";
import type { Agent, Integration, IntegrationSettings, WhatsAppProfile } from "@/types";

function QualityBadge({ rating }: { rating: string | null }) {
  if (!rating) return null;
  const color =
    rating === "GREEN" ? "bg-accent-green/15 text-accent-green" : rating === "RED" ? "bg-accent-pink/15 text-accent-pink" : "bg-accent-amber/15 text-accent-amber";
  return <span className={`rounded-full px-2 py-0.5 text-[10px] ${color}`}>{rating}</span>;
}

function ManualSetupModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    business_account_id: "",
    phone_number_id: "",
    access_token: "",
    verify_token: "",
    webhook_secret: "",
  });
  const [tested, setTested] = useState<{ ok: boolean; label: string } | null>(null);

  const test = useMutation({
    mutationFn: async () =>
      (
        await api.post("/integrations/whatsapp/test", {
          phone_number_id: form.phone_number_id,
          access_token: form.access_token,
        })
      ).data,
    onSuccess: (data) => {
      setTested({ ok: true, label: data.verified_name ?? data.display_phone_number ?? "Verified" });
      toast.success("Connection looks good");
    },
    onError: (err) => {
      setTested({ ok: false, label: "" });
      toast.error(apiErrorMessage(err, "Couldn't verify those credentials"));
    },
  });

  const save = useMutation({
    mutationFn: async () =>
      api.post("/integrations/whatsapp/manual", {
        business_account_id: form.business_account_id,
        phone_number_id: form.phone_number_id,
        access_token: form.access_token,
        verify_token: form.verify_token,
        webhook_secret: form.webhook_secret || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["integrations"] });
      queryClient.invalidateQueries({ queryKey: ["whatsapp-profile"] });
      toast.success("WhatsApp connected");
      onClose();
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Couldn't save that connection")),
  });

  const field = (key: keyof typeof form, label: string, placeholder: string, opts: { mono?: boolean } = {}) => (
    <label className="block space-y-1">
      <span className="text-xs text-ink-muted">{label}</span>
      <input
        value={form[key]}
        onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
        placeholder={placeholder}
        className={`w-full rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-xs text-ink focus:outline-none ${
          opts.mono ? "font-mono" : ""
        }`}
      />
    </label>
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="panel panel-glow w-full max-w-md p-5" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-display text-base font-semibold">Manual WhatsApp Cloud API Setup</h2>
          <button onClick={onClose} className="text-ink-faint hover:text-ink">
            <X className="h-4 w-4" />
          </button>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
          className="space-y-3"
        >
          {field("business_account_id", "Business Account ID", "102938475610283")}
          {field("phone_number_id", "Phone Number ID", "109283746510928", { mono: true })}
          {field("access_token", "Permanent Access Token", "EAAxxxxxxxxxxxxxxxxxxxx", { mono: true })}
          {field("verify_token", "Verify Token", "a value only you and Meta know")}
          {field("webhook_secret", "Webhook Secret (optional)", "extra shared secret, defense in depth")}

          {tested && (
            <p className={`text-xs ${tested.ok ? "text-accent-green" : "text-accent-pink"}`}>
              {tested.ok ? `✓ Verified: ${tested.label}` : "✕ Verification failed"}
            </p>
          )}

          <div className="flex items-center gap-2 pt-1">
            <button
              type="button"
              onClick={() => test.mutate()}
              disabled={test.isPending || !form.phone_number_id || !form.access_token}
              className="flex items-center gap-1.5 rounded-lg border border-base-border px-3 py-2 text-xs text-ink-muted hover:text-ink disabled:opacity-40"
            >
              {test.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Test Connection
            </button>
            <button
              type="submit"
              disabled={
                save.isPending || !form.business_account_id || !form.phone_number_id || !form.access_token || !form.verify_token
              }
              className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-accent-violet to-accent-blue px-4 py-2 text-xs font-medium text-white hover:opacity-90 disabled:opacity-40"
            >
              {save.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Save
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function SettingsModal({ integration, onClose }: { integration: Integration; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [settings, setSettings] = useState<IntegrationSettings>(integration.settings ?? {});

  const { data: agents = [] } = useQuery({
    queryKey: ["agents"],
    queryFn: async () => (await api.get<Agent[]>("/agents")).data,
  });

  const save = useMutation({
    mutationFn: async () => api.patch(`/integrations/${integration.platform}/settings`, settings),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["integrations"] });
      toast.success("Settings saved");
      onClose();
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  const toggle = (key: keyof IntegrationSettings, label: string, description: string) => (
    <label className="flex items-center justify-between gap-4 rounded-lg border border-base-border px-3 py-2.5">
      <div>
        <p className="text-xs font-medium text-ink">{label}</p>
        <p className="text-[11px] text-ink-faint">{description}</p>
      </div>
      <input
        type="checkbox"
        checked={Boolean(settings[key] ?? true)}
        onChange={(e) => setSettings((s) => ({ ...s, [key]: e.target.checked }))}
        className="h-4 w-4 accent-accent-violet"
      />
    </label>
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="panel panel-glow w-full max-w-md space-y-4 p-5" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h2 className="font-display text-base font-semibold capitalize">{integration.platform} Settings</h2>
          <button onClick={onClose} className="text-ink-faint hover:text-ink">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-2">
          {toggle("auto_reply", "Auto Reply", "Let agents reply automatically to incoming messages")}
          {toggle("typing_indicator", "Typing Indicator", "Show a typing indicator while composing a reply")}
          {toggle("read_receipts", "Read Receipts", "Mark incoming messages as read")}
          {toggle("human_takeover", "Human Takeover by default", "New conversations start assigned to a human")}
        </div>

        <label className="block space-y-1">
          <span className="text-xs text-ink-muted">Default Agent</span>
          <select
            value={settings.default_agent_id ?? ""}
            onChange={(e) => setSettings((s) => ({ ...s, default_agent_id: e.target.value || null }))}
            className="w-full rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-xs text-ink focus:outline-none"
          >
            <option value="">Auto (Router picks)</option>
            {agents.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.name}
              </option>
            ))}
          </select>
        </label>

        <div className="space-y-2 rounded-lg border border-base-border p-3">
          <label className="flex items-center justify-between">
            <span className="text-xs font-medium text-ink">Business Hours</span>
            <input
              type="checkbox"
              checked={Boolean(settings.business_hours?.enabled)}
              onChange={(e) =>
                setSettings((s) => ({
                  ...s,
                  business_hours: { ...s.business_hours, enabled: e.target.checked },
                }))
              }
              className="h-4 w-4 accent-accent-violet"
            />
          </label>
          {settings.business_hours?.enabled && (
            <input
              value={settings.business_hours?.message ?? ""}
              onChange={(e) =>
                setSettings((s) => ({
                  ...s,
                  business_hours: { ...s.business_hours, message: e.target.value },
                }))
              }
              placeholder="After-hours auto-reply message"
              className="w-full rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-xs text-ink focus:outline-none"
            />
          )}
        </div>

        <button
          onClick={() => save.mutate()}
          disabled={save.isPending}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-accent-violet to-accent-blue px-4 py-2 text-xs font-medium text-white hover:opacity-90 disabled:opacity-40"
        >
          {save.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          Save Settings
        </button>
      </div>
    </div>
  );
}

export default function WhatsAppIntegrationCard({ whatsapp }: { whatsapp: Integration | undefined }) {
  const queryClient = useQueryClient();
  const [showManualSetup, setShowManualSetup] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  const { data: profile } = useQuery({
    queryKey: ["whatsapp-profile"],
    queryFn: async () => (await api.get<WhatsAppProfile>("/integrations/whatsapp/profile")).data,
    enabled: !!whatsapp,
    retry: false,
  });

  const connectWithMeta = useMutation({
    mutationFn: async () => (await api.get("/integrations/whatsapp/oauth/config")).data as { app_id: string; config_id: string },
    onSuccess: (config) => {
      if (!config.app_id) {
        toast.error("Meta isn't configured yet on this server — use Manual Setup instead.");
        return;
      }
      // Simplified redirect-based OAuth in place of Meta's JS SDK popup
      // (which needs to be embedded on the page and isn't wired up in
      // this build) — the backend callback handles the returned `code`
      // identically either way, so swapping in the real FB.login()
      // Embedded Signup popup later doesn't require backend changes.
      const redirectUri = `${window.location.origin}/integrations/whatsapp/callback`;
      const url = new URL("https://www.facebook.com/v25.0/dialog/oauth");
      url.searchParams.set("client_id", config.app_id);
      if (config.config_id) url.searchParams.set("config_id", config.config_id);
      url.searchParams.set("redirect_uri", redirectUri);
      url.searchParams.set("response_type", "code");
      window.location.href = url.toString();
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  const sync = useMutation({
    mutationFn: async () => api.post("/integrations/whatsapp/sync"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["whatsapp-profile"] });
      toast.success("WhatsApp profile synced");
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Sync failed")),
  });

  const disconnect = useMutation({
    mutationFn: async () => api.delete("/integrations/whatsapp"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["integrations"] });
      queryClient.invalidateQueries({ queryKey: ["whatsapp-profile"] });
      toast.success("WhatsApp disconnected");
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  return (
    <div className="panel space-y-4 p-5">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-emerald-500/15">
          <MessageCircle className="h-5 w-5 text-emerald-500" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-ink">WhatsApp</p>
          <p className="truncate text-xs text-ink-faint">
            {profile ? profile.business_name ?? profile.display_phone_number : "Connect your WhatsApp Business account"}
          </p>
        </div>
        {whatsapp && (
          <span
            className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] ${
              whatsapp.status === "active" ? "bg-accent-green/15 text-accent-green" : "bg-accent-pink/15 text-accent-pink"
            }`}
          >
            {whatsapp.status}
          </span>
        )}
      </div>

      {whatsapp && profile ? (
        <>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="rounded-lg border border-base-border p-2.5">
              <p className="text-ink-faint">Phone Number</p>
              <p className="mt-0.5 font-mono text-ink">{profile.display_phone_number ?? "—"}</p>
            </div>
            <div className="rounded-lg border border-base-border p-2.5">
              <p className="text-ink-faint">Quality Rating</p>
              <div className="mt-0.5">
                <QualityBadge rating={profile.quality_rating} />
              </div>
            </div>
            <div className="rounded-lg border border-base-border p-2.5">
              <p className="text-ink-faint">Messaging Tier</p>
              <p className="mt-0.5 text-ink">{profile.messaging_tier ?? "—"}</p>
            </div>
            <div className="rounded-lg border border-base-border p-2.5">
              <p className="text-ink-faint">Last Sync</p>
              <p className="mt-0.5 text-ink">
                {profile.last_synced_at ? formatDistanceToNow(new Date(profile.last_synced_at), { addSuffix: true }) : "never"}
              </p>
            </div>
          </div>

          {whatsapp.error_message && <p className="text-xs text-accent-pink">{whatsapp.error_message}</p>}

          <div className="flex flex-wrap items-center gap-2 text-xs">
            <button
              onClick={() => sync.mutate()}
              disabled={sync.isPending}
              className="flex items-center gap-1.5 rounded-lg border border-base-border px-3 py-1.5 text-ink-muted hover:text-ink"
            >
              {sync.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
              Sync
            </button>
            <button
              onClick={() => setShowSettings(true)}
              className="flex items-center gap-1.5 rounded-lg border border-base-border px-3 py-1.5 text-ink-muted hover:text-ink"
            >
              <Settings2 className="h-3.5 w-3.5" />
              View Settings
            </button>
            <button
              onClick={() => setShowManualSetup(true)}
              className="rounded-lg border border-base-border px-3 py-1.5 text-ink-muted hover:text-ink"
            >
              Reconnect
            </button>
            <button
              onClick={() => disconnect.mutate()}
              disabled={disconnect.isPending}
              className="ml-auto flex items-center gap-1.5 text-ink-muted hover:text-accent-pink"
            >
              {disconnect.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <X className="h-3.5 w-3.5" />}
              Disconnect
            </button>
          </div>
        </>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => connectWithMeta.mutate()}
            disabled={connectWithMeta.isPending}
            className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-accent-violet to-accent-blue px-4 py-2 text-xs font-medium text-white hover:opacity-90 disabled:opacity-40"
          >
            {connectWithMeta.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            Connect with Meta
          </button>
          <button
            onClick={() => setShowManualSetup(true)}
            className="rounded-lg border border-base-border px-4 py-2 text-xs text-ink-muted hover:text-ink"
          >
            Manual Setup
          </button>
        </div>
      )}

      {showManualSetup && <ManualSetupModal onClose={() => setShowManualSetup(false)} />}
      {showSettings && whatsapp && <SettingsModal integration={whatsapp} onClose={() => setShowSettings(false)} />}
    </div>
  );
}
