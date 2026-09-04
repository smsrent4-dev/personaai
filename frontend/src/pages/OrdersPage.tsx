import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ShoppingBag, Loader2, CheckCircle2, X, Truck } from "lucide-react";
import { toast } from "sonner";
import { api, apiErrorMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { Order, OrderEvent, OrderStatus } from "@/types";

const ORDER_STATUSES: OrderStatus[] = [
  "pending",
  "confirmed",
  "preparing",
  "ready",
  "delivered",
  "cancelled",
  "refunded",
];

const STATUS_STYLES: Record<OrderStatus, string> = {
  pending: "bg-accent-amber/15 text-accent-amber",
  confirmed: "bg-accent-blue/15 text-accent-blue",
  preparing: "bg-accent-violet/15 text-accent-violet",
  ready: "bg-accent-cyan/15 text-accent-cyan",
  delivered: "bg-accent-green/15 text-accent-green",
  cancelled: "bg-ink-faint/15 text-ink-faint",
  refunded: "bg-accent-pink/15 text-accent-pink",
};

const PAYMENT_STYLES: Record<string, string> = {
  paid: "bg-accent-green/15 text-accent-green",
  unpaid: "bg-ink-faint/15 text-ink-faint",
  awaiting_confirmation: "bg-accent-amber/15 text-accent-amber",
  awaiting_delivery_payment: "bg-accent-blue/15 text-accent-blue",
  awaiting_cash_payment: "bg-accent-blue/15 text-accent-blue",
  refunded: "bg-accent-pink/15 text-accent-pink",
};

export default function OrdersPage() {
  const [selectedOrder, setSelectedOrder] = useState<Order | null>(null);

  const { data: orders = [], isLoading } = useQuery({
    queryKey: ["orders"],
    queryFn: async () => (await api.get<Order[]>("/orders")).data,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-xl font-semibold">Orders</h1>
        <p className="text-sm text-ink-muted">
          Orders your agents create automatically, plus any you add manually.
        </p>
      </div>

      <div className="panel divide-y divide-base-border">
        {isLoading && <p className="p-4 text-sm text-ink-faint">Loading…</p>}
        {!isLoading && orders.length === 0 && (
          <div className="flex flex-col items-center gap-2 p-10 text-center">
            <ShoppingBag className="h-6 w-6 text-ink-faint" />
            <p className="text-sm text-ink-muted">No orders yet.</p>
          </div>
        )}
        {orders.map((order) => (
          <button
            key={order.id}
            onClick={() => setSelectedOrder(order)}
            className="flex w-full items-center justify-between px-4 py-3 text-left transition-colors hover:bg-white/5"
          >
            <div className="min-w-0">
              <p className="truncate text-sm text-ink">
                {order.items.map((i) => `${i.quantity}x ${i.name}`).join(", ")}
              </p>
              <p className="flex items-center gap-1 text-xs text-ink-faint">
                {new Date(order.created_at).toLocaleString()}
                {order.shipping_address && (
                  <span className="flex items-center gap-0.5 text-accent-blue" title={order.shipping_address}>
                    <Truck className="h-3 w-3" /> ships
                  </span>
                )}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <span className="font-mono text-sm text-ink">
                {order.total_amount} {order.currency}
              </span>
              <span className={cn("rounded-full px-2 py-0.5 text-[10px]", STATUS_STYLES[order.status])}>
                {order.status}
              </span>
              <span className={cn("rounded-full px-2 py-0.5 text-[10px]", PAYMENT_STYLES[order.payment_status])}>
                {order.payment_status.replace(/_/g, " ")}
              </span>
            </div>
          </button>
        ))}
      </div>

      {selectedOrder && <OrderDetailModal order={selectedOrder} onClose={() => setSelectedOrder(null)} />}
    </div>
  );
}

function OrderDetailModal({ order, onClose }: { order: Order; onClose: () => void }) {
  const queryClient = useQueryClient();

  const timelineQuery = useQuery({
    queryKey: ["order-timeline", order.id],
    queryFn: async () => (await api.get<OrderEvent[]>(`/orders/${order.id}/timeline`)).data,
  });

  const updateStatus = useMutation({
    mutationFn: async (status: OrderStatus) => api.patch(`/orders/${order.id}/status`, { status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["orders"] });
      queryClient.invalidateQueries({ queryKey: ["order-timeline", order.id] });
      toast.success("Order updated");
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  const confirmPayment = useMutation({
    mutationFn: async () => api.post(`/orders/${order.id}/confirm-payment`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["orders"] });
      queryClient.invalidateQueries({ queryKey: ["order-timeline", order.id] });
      toast.success("Payment confirmed");
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="panel panel-glow w-full max-w-lg space-y-4 p-5" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h2 className="font-display text-base font-semibold">Order Details</h2>
          <button onClick={onClose} className="text-ink-faint hover:text-ink">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-1">
          {order.items.map((item, i) => (
            <div key={i} className="flex justify-between text-sm">
              <span className="text-ink-muted">
                {item.quantity}x {item.name}
              </span>
              <span className="font-mono text-ink">{item.subtotal}</span>
            </div>
          ))}
          <div className="flex justify-between border-t border-base-border pt-2 text-sm font-medium">
            <span className="text-ink">Total</span>
            <span className="font-mono text-ink">
              {order.total_amount} {order.currency}
            </span>
          </div>
        </div>

        {(order.recipient_name || order.shipping_address) && (
          <div className="rounded-lg border border-base-border bg-base-panel-2 p-3">
            <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-ink-muted">
              <Truck className="h-3.5 w-3.5" /> Delivery
            </p>
            {order.recipient_name && <p className="text-sm text-ink">{order.recipient_name}</p>}
            {order.recipient_phone && <p className="text-xs text-ink-muted">{order.recipient_phone}</p>}
            {order.shipping_address && <p className="text-xs text-ink-muted">{order.shipping_address}</p>}
          </div>
        )}

        <div className="flex items-center gap-2">
          <select
            value={order.status}
            onChange={(e) => updateStatus.mutate(e.target.value as OrderStatus)}
            disabled={updateStatus.isPending}
            className="rounded-lg border border-base-border bg-base-panel-2 px-2 py-1.5 text-xs text-ink focus:outline-none"
          >
            {ORDER_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>

          {order.payment_status === "awaiting_confirmation" && (
            <button
              onClick={() => confirmPayment.mutate()}
              disabled={confirmPayment.isPending}
              className="flex items-center gap-1.5 rounded-lg bg-gradient-to-r from-accent-green to-accent-cyan px-3 py-1.5 text-xs font-medium text-white hover:opacity-90"
            >
              {confirmPayment.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <CheckCircle2 className="h-3.5 w-3.5" />
              )}
              Confirm Payment
            </button>
          )}
        </div>

        <div>
          <p className="mb-2 text-xs font-medium text-ink-muted">Timeline</p>
          <div className="space-y-2">
            {(timelineQuery.data ?? []).map((event) => (
              <div key={event.id} className="flex items-start gap-2 text-xs">
                <span className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-accent-violet" />
                <div>
                  <p className="text-ink">{event.event_type.replace(/_/g, " ")}</p>
                  {event.note && <p className="text-ink-faint">{event.note}</p>}
                  <p className="text-[10px] text-ink-faint">{new Date(event.created_at).toLocaleString()}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
