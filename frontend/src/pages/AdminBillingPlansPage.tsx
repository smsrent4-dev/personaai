import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ArrowLeft, Plus, Loader2, X, Ban, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { api, apiErrorMessage } from "@/lib/api";
import { formatLimit, formatPrice } from "@/lib/billing-format";
import { cn } from "@/lib/utils";
import type { BillingInterval, BillingPlan } from "@/types";

export default function AdminBillingPlansPage() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [editingPlan, setEditingPlan] = useState<BillingPlan | null>(null);

  const { data: plans = [], isLoading } = useQuery({
    queryKey: ["admin-billing-plans"],
    queryFn: async () => (await api.get<BillingPlan[]>("/admin/billing-plans")).data,
  });

  const deactivate = useMutation({
    mutationFn: async (id: string) => api.post(`/admin/billing-plans/${id}/deactivate`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-billing-plans"] });
      toast.success("Plan deactivated");
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <Link to="/admin" className="mb-1 flex items-center gap-1.5 text-xs text-ink-muted hover:text-ink">
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to Admin
          </Link>
          <h1 className="font-display text-xl font-semibold">Billing Plans</h1>
          <p className="text-sm text-ink-muted">Edit pricing and limits — synced to Paystack automatically.</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-accent-violet to-accent-blue px-4 py-2 text-sm font-medium text-white hover:opacity-90"
        >
          <Plus className="h-4 w-4" />
          New Plan
        </button>
      </div>

      {isLoading ? (
        <Loader2 className="h-6 w-6 animate-spin text-ink-faint" />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {plans.map((plan) => (
            <div key={plan.id} className={cn("panel flex flex-col p-5", !plan.is_active && "opacity-50")}>
              <div className="flex items-start justify-between">
                <div>
                  <p className="font-display text-base font-semibold text-ink">{plan.name}</p>
                  <p className="font-mono text-lg text-ink-muted">
                    {formatPrice(plan.price_amount, plan.currency, plan.interval)}
                  </p>
                </div>
                <span
                  className={cn(
                    "rounded-full px-2 py-0.5 text-[10px]",
                    plan.is_active ? "bg-accent-green/15 text-accent-green" : "bg-ink-faint/15 text-ink-faint"
                  )}
                >
                  {plan.is_active ? "active" : "deactivated"}
                </span>
              </div>

              <ul className="mt-3 space-y-1 text-xs text-ink-muted">
                <li>{formatLimit(plan.max_agents, "agents")}</li>
                <li>{formatLimit(plan.max_messages_per_month, "messages/mo")}</li>
                <li>{formatLimit(plan.max_knowledge_documents, "knowledge docs")}</li>
                <li>{formatLimit(plan.max_integrations, "integrations")}</li>
              </ul>

              <div className="mt-4 flex items-center gap-2">
                <button
                  onClick={() => setEditingPlan(plan)}
                  className="rounded-lg border border-base-border px-3 py-1.5 text-xs text-ink-muted hover:text-ink"
                >
                  Edit
                </button>
                {plan.is_active && (
                  <button
                    onClick={() => deactivate.mutate(plan.id)}
                    disabled={deactivate.isPending}
                    className="flex items-center gap-1 rounded-lg border border-base-border px-3 py-1.5 text-xs text-ink-muted hover:border-accent-pink/40 hover:text-accent-pink"
                  >
                    <Ban className="h-3.5 w-3.5" />
                    Deactivate
                  </button>
                )}
              </div>
            </div>
          ))}
          {plans.length === 0 && <p className="col-span-full text-sm text-ink-faint">No plans yet.</p>}
        </div>
      )}

      {showCreate && <PlanFormModal mode="create" onClose={() => setShowCreate(false)} />}
      {editingPlan && <PlanFormModal mode="edit" plan={editingPlan} onClose={() => setEditingPlan(null)} />}
    </div>
  );
}

function PlanFormModal({
  mode,
  plan,
  onClose,
}: {
  mode: "create" | "edit";
  plan?: BillingPlan;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(plan?.name ?? "");
  const [price, setPrice] = useState(plan ? String(plan.price_amount) : "");
  const [currency, setCurrency] = useState(plan?.currency ?? "NGN");
  const [interval, setInterval] = useState<BillingInterval>(plan?.interval ?? "monthly");
  const [maxAgents, setMaxAgents] = useState(plan?.max_agents?.toString() ?? "");
  const [maxMessages, setMaxMessages] = useState(plan?.max_messages_per_month?.toString() ?? "");
  const [maxDocs, setMaxDocs] = useState(plan?.max_knowledge_documents?.toString() ?? "");
  const [maxIntegrations, setMaxIntegrations] = useState(plan?.max_integrations?.toString() ?? "");

  const toIntOrNull = (v: string) => (v.trim() === "" ? null : parseInt(v, 10));

  const save = useMutation({
    mutationFn: async () => {
      const payload = {
        name,
        price_amount: price,
        max_agents: toIntOrNull(maxAgents),
        max_messages_per_month: toIntOrNull(maxMessages),
        max_knowledge_documents: toIntOrNull(maxDocs),
        max_integrations: toIntOrNull(maxIntegrations),
      };
      if (mode === "create") {
        return api.post("/admin/billing-plans", { ...payload, currency, interval });
      }
      return api.patch(`/admin/billing-plans/${plan!.id}`, payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-billing-plans"] });
      toast.success(mode === "create" ? "Plan created" : "Plan updated");
      onClose();
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="panel panel-glow w-full max-w-md p-5" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-display text-base font-semibold">{mode === "create" ? "New Plan" : "Edit Plan"}</h2>
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
          <div>
            <label className="mb-1 block text-xs text-ink-muted">Name</label>
            <input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-sm focus:outline-none"
              placeholder="Growth"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs text-ink-muted">Price</label>
              <input
                required
                inputMode="decimal"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                className="w-full rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-sm focus:outline-none"
                placeholder="99.00"
              />
            </div>
            {mode === "create" ? (
              <div>
                <label className="mb-1 block text-xs text-ink-muted">Currency</label>
                <input
                  value={currency}
                  onChange={(e) => setCurrency(e.target.value.toUpperCase())}
                  maxLength={3}
                  className="w-full rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-sm uppercase focus:outline-none"
                />
              </div>
            ) : (
              <div>
                <label className="mb-1 block text-xs text-ink-muted">Currency</label>
                <input
                  disabled
                  value={plan?.currency}
                  className="w-full rounded-lg border border-base-border bg-base-panel-2/40 px-3 py-2 text-sm text-ink-faint"
                />
              </div>
            )}
          </div>
          {mode === "create" && (
            <div>
              <label className="mb-1 block text-xs text-ink-muted">Billing interval</label>
              <select
                value={interval}
                onChange={(e) => setInterval(e.target.value as BillingInterval)}
                className="w-full rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-sm focus:outline-none"
              >
                <option value="monthly">Monthly</option>
                <option value="yearly">Yearly</option>
              </select>
            </div>
          )}

          <p className="pt-1 text-xs text-ink-muted">Limits — leave blank for unlimited</p>
          <div className="grid grid-cols-2 gap-3">
            <LimitInput label="Max agents" value={maxAgents} onChange={setMaxAgents} />
            <LimitInput label="Max messages/mo" value={maxMessages} onChange={setMaxMessages} />
            <LimitInput label="Max knowledge docs" value={maxDocs} onChange={setMaxDocs} />
            <LimitInput label="Max integrations" value={maxIntegrations} onChange={setMaxIntegrations} />
          </div>

          <button
            type="submit"
            disabled={save.isPending}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-accent-violet to-accent-blue px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
          >
            {save.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            {mode === "create" ? "Create plan" : "Save changes"}
          </button>
          {mode === "edit" && (
            <p className="flex items-center gap-1.5 text-center text-[11px] text-ink-faint">
              <RotateCcw className="h-3 w-3 shrink-0" />
              Changing the price re-syncs the plan on Paystack automatically.
            </p>
          )}
        </form>
      </div>
    </div>
  );
}

function LimitInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <label className="mb-1 block text-xs text-ink-muted">{label}</label>
      <input
        inputMode="numeric"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="∞"
        className="w-full rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-sm focus:outline-none"
      />
    </div>
  );
}
