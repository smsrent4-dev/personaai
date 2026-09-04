import { useQuery } from "@tanstack/react-query";
import { Users, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import type { Customer } from "@/types";
import PlatformBadge from "@/components/PlatformBadge";

export default function CustomersPage() {
  const { data: customers = [], isLoading } = useQuery({
    queryKey: ["customers"],
    queryFn: async () => (await api.get<Customer[]>("/customers")).data,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-xl font-semibold">Customers</h1>
        <p className="text-sm text-ink-muted">
          Built automatically from conversations and orders — nothing here is manually entered.
        </p>
      </div>

      <div className="panel divide-y divide-base-border">
        {isLoading && (
          <div className="p-6">
            <Loader2 className="h-5 w-5 animate-spin text-ink-faint" />
          </div>
        )}
        {!isLoading && customers.length === 0 && (
          <div className="flex flex-col items-center gap-2 p-10 text-center">
            <Users className="h-6 w-6 text-ink-faint" />
            <p className="text-sm text-ink-muted">No customers yet — they'll appear as people message your agents.</p>
          </div>
        )}
        {customers.map((customer) => (
          <div key={customer.id} className="flex items-center justify-between px-4 py-3">
            <div className="min-w-0">
              <p className="truncate text-sm text-ink">
                {customer.display_name ?? customer.external_user_id}
              </p>
              <div className="mt-0.5 flex items-center gap-2 text-xs text-ink-faint">
                <PlatformBadge platform={customer.platform} />
                <span>· {customer.external_user_id}</span>
                {customer.last_interaction_at && (
                  <span>· last seen {new Date(customer.last_interaction_at).toLocaleDateString()}</span>
                )}
              </div>
              {customer.interests.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {customer.interests.slice(0, 4).map((interest) => (
                    <span
                      key={interest}
                      className="rounded-full bg-accent-violet/10 px-2 py-0.5 text-[10px] text-accent-violet"
                    >
                      {interest}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <div className="shrink-0 text-right">
              <p className="font-mono text-sm text-ink">${customer.lifetime_spend.toLocaleString()}</p>
              <p className="text-xs text-ink-faint">
                {customer.order_count} order{customer.order_count === 1 ? "" : "s"}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
