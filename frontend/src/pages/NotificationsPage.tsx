import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { Bell, MessageSquare, AlertTriangle, ShoppingBag, Receipt, CheckCircle2 } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { Notification, NotificationType } from "@/types";

const ICONS: Record<NotificationType, React.ElementType> = {
  new_conversation: MessageSquare,
  knowledge_ingestion_failed: AlertTriangle,
  integration_error: AlertTriangle,
  new_order: ShoppingBag,
  receipt_uploaded: Receipt,
  payment_confirmed: CheckCircle2,
};

export default function NotificationsPage() {
  const queryClient = useQueryClient();

  const { data: notifications = [], isLoading } = useQuery({
    queryKey: ["notifications"],
    queryFn: async () => (await api.get<Notification[]>("/notifications")).data,
  });

  const markAllRead = useMutation({
    mutationFn: async () => api.post("/notifications/read-all"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
      queryClient.invalidateQueries({ queryKey: ["notifications-unread-count"] });
    },
  });

  const markRead = useMutation({
    mutationFn: async (id: string) => api.post(`/notifications/${id}/read`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
      queryClient.invalidateQueries({ queryKey: ["notifications-unread-count"] });
    },
  });

  const unreadCount = notifications.filter((n) => !n.is_read).length;
  const sorted = [...notifications].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-xl font-semibold text-ink">Notifications</h1>
          <p className="text-sm text-ink-muted">New leads, order activity, and integration issues, as they happen.</p>
        </div>
        {unreadCount > 0 && (
          <button
            onClick={() => markAllRead.mutate()}
            className="rounded-lg border border-base-border px-3 py-1.5 text-xs font-medium text-ink-muted transition-colors hover:text-ink"
          >
            Mark all read
          </button>
        )}
      </div>

      <div className="panel divide-y divide-base-border">
        {isLoading && <p className="p-4 text-sm text-ink-faint">Loading…</p>}
        {!isLoading && sorted.length === 0 && (
          <div className="flex flex-col items-center gap-2 p-10 text-center">
            <Bell className="h-6 w-6 text-ink-faint" />
            <p className="text-sm text-ink-muted">You're all caught up.</p>
          </div>
        )}
        {sorted.map((n) => {
          const Icon = ICONS[n.type] ?? Bell;
          return (
            <button
              key={n.id}
              onClick={() => !n.is_read && markRead.mutate(n.id)}
              className={cn(
                "flex w-full items-start gap-3 p-4 text-left transition-colors hover:bg-base-panel-2",
                !n.is_read && "bg-accent-violet/[0.03]"
              )}
            >
              <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-base-panel-2 text-ink-muted">
                <Icon className="h-4 w-4" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium text-ink">{n.title}</span>
                {n.body && <span className="mt-0.5 block text-xs text-ink-muted">{n.body}</span>}
                <span className="mt-1 block text-[11px] text-ink-faint">
                  {formatDistanceToNow(new Date(n.created_at), { addSuffix: true })}
                </span>
              </span>
              {!n.is_read && <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-accent-violet" />}
            </button>
          );
        })}
      </div>
    </div>
  );
}
