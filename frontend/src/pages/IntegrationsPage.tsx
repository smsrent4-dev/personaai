import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Send, Loader2, X } from "lucide-react";
import { toast } from "sonner";
import { api, apiErrorMessage } from "@/lib/api";
import type { Integration } from "@/types";
import WhatsAppIntegrationCard from "@/components/WhatsAppIntegrationCard";

export default function IntegrationsPage() {
  const queryClient = useQueryClient();
  const [botToken, setBotToken] = useState("");

  const { data: integrations = [], isLoading } = useQuery({
    queryKey: ["integrations"],
    queryFn: async () => (await api.get<Integration[]>("/integrations")).data,
  });

  const telegram = integrations.find((i) => i.platform === "telegram");
  const whatsapp = integrations.find((i) => i.platform === "whatsapp");

  const connect = useMutation({
    mutationFn: async () => api.post("/integrations/telegram", { bot_token: botToken }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["integrations"] });
      setBotToken("");
      toast.success("Telegram connected");
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Couldn't connect that bot")),
  });

  const disconnect = useMutation({
    mutationFn: async () => api.delete("/integrations/telegram"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["integrations"] });
      toast.success("Telegram disconnected");
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-xl font-semibold">Integrations</h1>
        <p className="text-sm text-ink-muted">Connect the platforms your agents answer on.</p>
      </div>

      <div className="panel space-y-4 p-5">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-accent-blue/15">
            <Send className="h-5 w-5 text-accent-blue" />
          </div>
          <div>
            <p className="text-sm font-medium text-ink">Telegram</p>
            <p className="text-xs text-ink-faint">
              {telegram
                ? `Connected as @${telegram.external_bot_username}`
                : "Message @BotFather on Telegram to create a bot and get its token."}
            </p>
          </div>
        </div>

        {isLoading ? (
          <Loader2 className="h-4 w-4 animate-spin text-ink-faint" />
        ) : telegram ? (
          <div className="flex items-center justify-between rounded-lg border border-base-border p-3">
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] ${
                telegram.status === "active"
                  ? "bg-accent-green/15 text-accent-green"
                  : "bg-accent-pink/15 text-accent-pink"
              }`}
            >
              {telegram.status}
            </span>
            {telegram.error_message && <span className="text-xs text-accent-pink">{telegram.error_message}</span>}
            <button
              onClick={() => disconnect.mutate()}
              disabled={disconnect.isPending}
              className="flex items-center gap-1.5 text-xs text-ink-muted hover:text-accent-pink"
            >
              {disconnect.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <X className="h-3.5 w-3.5" />
              )}
              Disconnect
            </button>
          </div>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (botToken.trim()) connect.mutate();
            }}
            className="flex items-center gap-2"
          >
            <input
              value={botToken}
              onChange={(e) => setBotToken(e.target.value)}
              placeholder="123456789:AAExampleBotTokenFromBotFather"
              className="w-full rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 font-mono text-xs text-ink focus:outline-none"
            />
            <button
              type="submit"
              disabled={connect.isPending || !botToken.trim()}
              className="flex shrink-0 items-center gap-2 rounded-lg bg-gradient-to-r from-accent-violet to-accent-blue px-4 py-2 text-xs font-medium text-white hover:opacity-90 disabled:opacity-40"
            >
              {connect.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Connect
            </button>
          </form>
        )}
      </div>

      <WhatsAppIntegrationCard whatsapp={whatsapp} />

      <div className="panel space-y-2 p-5 opacity-60">
        <p className="text-sm font-medium text-ink">More platforms</p>
        <p className="text-xs text-ink-faint">
          Discord, Instagram, Messenger, Slack, and a website chat widget are built on the same adapter
          architecture as Telegram and WhatsApp - not connected yet.
        </p>
      </div>
    </div>
  );
}
