import { useState } from "react";
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

export default function NotificationsBell() {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();

  const { data: notifications = [] } = useQuery({
    queryKey: ["notifications"],
    queryFn: async () => (await api.get<Notification[]>("/notifications")).data,
    refetchInterval: 30_000,
  });
  const { data: unread } = useQuery({
    queryKey: ["notifications-unread-count"],
    queryFn: async () => (await api.get<{ count: number }>("/notifications/unread-count")).data,
    refetchInterval: 30_000,
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

  const count = unread?.count ?? 0;

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="relative flex h-9 w-9 items-center justify-center rounded-xl border border-base-border bg-base-panel text-ink-muted transition-colors hover:text-ink"
      >
        <Bell className="h-4 w-4" />
        {count > 0 && (
          <span className="absolute -right-1 -top-1 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-accent-pink px-1 text-[10px] font-medium text-white">
            {count > 9 ? "9+" : count}
          </span>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-20 mt-2 w-80 rounded-2xl border border-base-border bg-base-panel shadow-card">
            <div className="flex items-center justify-between border-b border-base-border px-4 py-3">
              <p className="text-sm font-semibold text-ink">Notifications</p>
              {count > 0 && (
                <button
                  onClick={() => markAllRead.mutate()}
                  className="text-xs text-accent-violet hover:underline"
                >
                  Mark all read
                </button>
              )}
            </div>
            <div className="max-h-96 overflow-y-auto">
              {notifications.length === 0 && (
                <p className="px-4 py-6 text-center text-xs text-ink-faint">You're all caught up.</p>
              )}
              {notifications.slice(0, 20).map((n) => {
                const Icon = ICONS[n.type] ?? Bell;
                return (
                  <button
                    key={n.id}
                    onClick={() => !n.is_read && markRead.mutate(n.id)}
                    className={cn(
                      "flex w-full items-start gap-3 border-b border-base-border px-4 py-3 text-left transition-colors last:border-0 hover:bg-base-panel-2",
                      !n.is_read && "bg-accent-violet/[0.04]"
                    )}
                  >
                    <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-base-panel-2 text-ink-muted">
                      <Icon className="h-3.5 w-3.5" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-xs font-medium text-ink">{n.title}</span>
                      {n.body && <span className="mt-0.5 block truncate text-[11px] text-ink-muted">{n.body}</span>}
                      <span className="mt-0.5 block text-[10px] text-ink-faint">
                        {formatDistanceToNow(new Date(n.created_at), { addSuffix: true })}
                      </span>
                    </span>
                    {!n.is_read && <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-accent-violet" />}
                  </button>
                );
              })}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
