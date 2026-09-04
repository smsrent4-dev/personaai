import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Landmark, Banknote, Truck, Plus, Trash2, Loader2, X } from "lucide-react";
import { toast } from "sonner";
import { api, apiErrorMessage } from "@/lib/api";
import type { PaymentMethod, PaymentMethodType } from "@/types";
import { cn } from "@/lib/utils";

const METHOD_ICON: Record<PaymentMethodType, typeof Landmark> = {
  bank_transfer: Landmark,
  cash: Banknote,
  pay_on_delivery: Truck,
};

export default function PaymentMethodsPage() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);

  const { data: methods = [], isLoading } = useQuery({
    queryKey: ["payment-methods"],
    queryFn: async () => (await api.get<PaymentMethod[]>("/payment-methods")).data,
  });

  const toggleEnabled = useMutation({
    mutationFn: async ({ id, is_enabled }: { id: string; is_enabled: boolean }) =>
      api.patch(`/payment-methods/${id}`, { is_enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["payment-methods"] }),
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  const remove = useMutation({
    mutationFn: async (id: string) => api.delete(`/payment-methods/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["payment-methods"] });
      toast.success("Payment method removed");
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-xl font-semibold">Payment Methods</h1>
          <p className="text-sm text-ink-muted">
            How your agents tell customers to pay. Bank details are encrypted at rest.
          </p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-accent-violet to-accent-blue px-4 py-2 text-sm font-medium text-white hover:opacity-90"
        >
          <Plus className="h-4 w-4" />
          Add Method
        </button>
      </div>

      {isLoading ? (
        <Loader2 className="h-6 w-6 animate-spin text-ink-faint" />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {methods.map((method) => {
            const Icon = METHOD_ICON[method.method_type];
            return (
              <div key={method.id} className={cn("panel p-4", !method.is_enabled && "opacity-50")}>
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-full bg-accent-violet/15">
                      <Icon className="h-5 w-5 text-accent-violet" />
                    </div>
                    <div>
                      <p className="text-sm font-medium text-ink">{method.label}</p>
                      <p className="text-xs capitalize text-ink-faint">{method.method_type.replace(/_/g, " ")}</p>
                    </div>
                  </div>
                  <button
                    onClick={() => remove.mutate(method.id)}
                    className="text-ink-faint hover:text-accent-pink"
                    aria-label="Remove"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>

                {method.method_type === "bank_transfer" && (
                  <div className="mt-3 space-y-0.5 text-xs text-ink-muted">
                    {method.details.bank_name && <p>{method.details.bank_name}</p>}
                    {method.details.account_name && <p>{method.details.account_name}</p>}
                    {method.details.account_number && <p className="font-mono">{method.details.account_number}</p>}
                  </div>
                )}

                <label className="mt-3 flex items-center gap-2 text-xs text-ink-muted">
                  <input
                    type="checkbox"
                    checked={method.is_enabled}
                    onChange={(e) => toggleEnabled.mutate({ id: method.id, is_enabled: e.target.checked })}
                    className="accent-accent-violet"
                  />
                  Enabled
                </label>
              </div>
            );
          })}
          {methods.length === 0 && (
            <p className="col-span-full text-sm text-ink-faint">No payment methods configured yet.</p>
          )}
        </div>
      )}

      {showCreate && <CreateMethodModal onClose={() => setShowCreate(false)} />}
    </div>
  );
}

function CreateMethodModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [methodType, setMethodType] = useState<PaymentMethodType>("bank_transfer");
  const [label, setLabel] = useState("");
  const [bankName, setBankName] = useState("");
  const [accountName, setAccountName] = useState("");
  const [accountNumber, setAccountNumber] = useState("");

  const create = useMutation({
    mutationFn: async () =>
      api.post("/payment-methods", {
        method_type: methodType,
        label,
        ...(methodType === "bank_transfer"
          ? { bank_name: bankName, account_name: accountName, account_number: accountNumber }
          : {}),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["payment-methods"] });
      toast.success("Payment method added");
      onClose();
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="panel panel-glow w-full max-w-md p-5" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-display text-base font-semibold">Add Payment Method</h2>
          <button onClick={onClose} className="text-ink-faint hover:text-ink">
            <X className="h-4 w-4" />
          </button>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
          className="space-y-3"
        >
          <div>
            <label className="mb-1 block text-xs text-ink-muted">Type</label>
            <select
              value={methodType}
              onChange={(e) => setMethodType(e.target.value as PaymentMethodType)}
              className="w-full rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-sm focus:outline-none"
            >
              <option value="bank_transfer">Bank Transfer</option>
              <option value="cash">Cash</option>
              <option value="pay_on_delivery">Pay on Delivery</option>
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-ink-muted">Label</label>
            <input
              required
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="Main account"
              className="w-full rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-sm focus:outline-none"
            />
          </div>

          {methodType === "bank_transfer" && (
            <>
              <div>
                <label className="mb-1 block text-xs text-ink-muted">Bank name</label>
                <input
                  required
                  value={bankName}
                  onChange={(e) => setBankName(e.target.value)}
                  className="w-full rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-sm focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-ink-muted">Account name</label>
                <input
                  required
                  value={accountName}
                  onChange={(e) => setAccountName(e.target.value)}
                  className="w-full rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-sm focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-ink-muted">Account number</label>
                <input
                  required
                  value={accountNumber}
                  onChange={(e) => setAccountNumber(e.target.value)}
                  className="w-full rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-sm font-mono focus:outline-none"
                />
              </div>
            </>
          )}

          <button
            type="submit"
            disabled={create.isPending}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-accent-violet to-accent-blue px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
          >
            {create.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Add method
          </button>
        </form>
      </div>
    </div>
  );
}
