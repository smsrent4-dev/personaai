import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { MessageSquare } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { api } from "@/lib/api";
import type { Conversation, Platform } from "@/types";
import PlatformBadge from "@/components/PlatformBadge";

type ChannelFilter = "all" | Platform;

export default function ConversationsPage() {
  const [filter, setFilter] = useState<ChannelFilter>("all");

  const { data: conversations = [], isLoading } = useQuery({
    queryKey: ["conversations"],
    queryFn: async () => (await api.get<Conversation[]>("/conversations")).data,
  });

  const availablePlatforms = useMemo(
    () => Array.from(new Set(conversations.map((c) => c.platform))) as Platform[],
    [conversations]
  );

  const filtered = filter === "all" ? conversations : conversations.filter((c) => c.platform === filter);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-xl font-semibold">Conversations</h1>
          <p className="text-sm text-ink-muted">Every thread across every connected platform.</p>
        </div>

        {availablePlatforms.length > 0 && (
          <div className="flex items-center gap-1 rounded-lg border border-base-border p-1">
            <button
              onClick={() => setFilter("all")}
              className={`rounded-md px-3 py-1 text-xs transition-colors ${
                filter === "all" ? "bg-base-panel-2 text-ink" : "text-ink-faint hover:text-ink"
              }`}
            >
              All
            </button>
            {availablePlatforms.map((platform) => (
              <button
                key={platform}
                onClick={() => setFilter(platform)}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1 text-xs capitalize transition-colors ${
                  filter === platform ? "bg-base-panel-2 text-ink" : "text-ink-faint hover:text-ink"
                }`}
              >
                {platform}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="panel divide-y divide-base-border">
        {isLoading && <p className="p-4 text-sm text-ink-faint">Loading…</p>}

        {!isLoading && filtered.length === 0 && (
          <div className="flex flex-col items-center gap-2 p-10 text-center">
            <MessageSquare className="h-6 w-6 text-ink-faint" />
            <p className="text-sm text-ink-muted">
              {conversations.length === 0 ? "No conversations yet." : "No conversations on this channel yet."}
            </p>
            {conversations.length === 0 && (
              <Link to="/integrations" className="text-xs text-accent-violet hover:underline">
                Connect a platform to start receiving messages →
              </Link>
            )}
          </div>
        )}

        {filtered.map((conv) => (
          <Link
            key={conv.id}
            to={`/conversations/${conv.id}`}
            className="flex items-center justify-between px-4 py-3 transition-colors hover:bg-white/5"
          >
            <div className="min-w-0">
              <p className="truncate text-sm text-ink">{conv.external_user_name ?? conv.external_conversation_id}</p>
              <div className="mt-0.5 flex items-center gap-2">
                <PlatformBadge platform={conv.platform} />
                <span className="text-xs text-ink-faint">
                  · {conv.external_conversation_id} · {conv.status}
                </span>
              </div>
            </div>
            {conv.last_message_at && (
              <span className="shrink-0 font-mono text-xs text-ink-faint">
                {formatDistanceToNow(new Date(conv.last_message_at), { addSuffix: true })}
              </span>
            )}
          </Link>
        ))}
      </div>
    </div>
  );
}
