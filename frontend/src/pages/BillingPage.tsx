import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CreditCard, Check, Loader2, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { api, apiErrorMessage } from "@/lib/api";
import { formatLimit, formatPrice } from "@/lib/billing-format";
import { cn } from "@/lib/utils";
import type { BillingPlan, Subscription } from "@/types";

const STATUS_STYLES: Record<Subscription["status"], string> = {
  active: "bg-accent-green/15 text-accent-green",
  incomplete: "bg-accent-amber/15 text-accent-amber",
  past_due: "bg-accent-pink/15 text-accent-pink",
  canceled: "bg-ink-faint/15 text-ink-faint",
};

export default function BillingPage() {
  const queryClient = useQueryClient();
  const [checkingOut, setCheckingOut] = useState<string | null>(null);

  const plansQuery = useQuery({
    queryKey: ["billing-plans"],
    queryFn: async () => (await api.get<BillingPlan[]>("/billing/plans")).data,
  });

  const subscriptionQuery = useQuery({
    queryKey: ["billing-subscription"],
    queryFn: async () => (await api.get<Subscription | null>("/billing/subscription")).data,
  });

  const plans = plansQuery.data ?? [];
  const subscription = subscriptionQuery.data;
  // Matches by plan_id alone, not "status === active" — you should never
  // see a clickable "Subscribe" button on the plan you're already tied
  // to, even in an edge-case status (this is also what stops a free
  // plan's own card from ever showing "Subscribe" after you're on it).
  const currentPlanId = subscription?.plan_id ?? null;

  async function handleSubscribe(planId: string) {
    setCheckingOut(planId);
    try {
      const { data } = await api.post("/billing/checkout", { plan_id: planId });
      if (data.activated_directly) {
        // Free plan — activated immediately server-side, nothing to redirect to.
        toast.success("You're on this plan now.");
        await queryClient.invalidateQueries({ queryKey: ["billing-subscription"] });
        setCheckingOut(null);
        return;
      }
      window.location.href = data.authorization_url;
    } catch (err) {
      toast.error(apiErrorMessage(err, "Couldn't start checkout"));
      setCheckingOut(null);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-xl font-semibold">Billing</h1>
        <p className="text-sm text-ink-muted">Manage your plan and payment.</p>
      </div>

      <div className="panel p-5">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-accent-violet/15">
            <CreditCard className="h-5 w-5 text-accent-violet" />
          </div>
          <div className="flex-1">
            {subscriptionQuery.isLoading ? (
              <p className="text-sm text-ink-muted">Loading your subscription…</p>
            ) : subscription ? (
              (() => {
                const currentSubPlan = plans.find((p) => p.id === subscription.plan_id);
                const isFreePlan = currentSubPlan ? Number(currentSubPlan.price_amount) === 0 : false;
                return (
                  <>
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium text-ink">{currentSubPlan?.name ?? "Subscription"}</p>
                      <span className={cn("rounded-full px-2 py-0.5 text-[10px]", STATUS_STYLES[subscription.status])}>
                        {subscription.status.replace("_", " ")}
                      </span>
                    </div>
                    {subscription.current_period_end && subscription.status === "active" && (
                      <p className="text-xs text-ink-faint">
                        Renews {new Date(subscription.current_period_end).toLocaleDateString()}
                      </p>
                    )}
                    {/* A free plan is always activated immediately server-side (see
                        SubscriptionService.start_checkout) — it should never actually be
                        "incomplete", but this stays plan-aware rather than trusting that
                        invariant blindly, so a stale/edge-case row can't show a confusing
                        "waiting for payment" message on a plan that never needed any. */}
                    {subscription.status === "incomplete" && !isFreePlan && (
                      <p className="text-xs text-ink-faint">Waiting for payment confirmation.</p>
                    )}
                    {subscription.status === "past_due" && (
                      <p className="text-xs text-accent-pink">
                        Your last payment failed — update your payment method to avoid interruption.
                      </p>
                    )}
                  </>
                );
              })()
            ) : (
              <p className="text-sm text-ink-muted">You don't have a subscription yet — pick a plan below.</p>
            )}
          </div>
        </div>
      </div>

      {plansQuery.isLoading ? (
        <Loader2 className="h-6 w-6 animate-spin text-ink-faint" />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {plans.map((plan) => {
            const isCurrent = plan.id === currentPlanId;
            return (
              <div
                key={plan.id}
                className={cn("panel flex flex-col p-5", isCurrent && "panel-glow border-accent-violet/40")}
              >
                <p className="font-display text-base font-semibold text-ink">{plan.name}</p>
                <p className="mt-1 font-mono text-2xl text-ink">
                  {formatPrice(plan.price_amount, plan.currency, plan.interval)}
                </p>
                {plan.description && <p className="mt-2 text-xs text-ink-muted">{plan.description}</p>}

                <ul className="mt-4 flex-1 space-y-2 text-xs text-ink-muted">
                  <li className="flex items-center gap-2">
                    <Check className="h-3.5 w-3.5 shrink-0 text-accent-green" />
                    {formatLimit(plan.max_agents, "agents")}
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="h-3.5 w-3.5 shrink-0 text-accent-green" />
                    {formatLimit(plan.max_messages_per_month, "messages/mo")}
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="h-3.5 w-3.5 shrink-0 text-accent-green" />
                    {formatLimit(plan.max_knowledge_documents, "knowledge docs")}
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="h-3.5 w-3.5 shrink-0 text-accent-green" />
                    {formatLimit(plan.max_integrations, "integrations")}
                  </li>
                </ul>

                <button
                  onClick={() => handleSubscribe(plan.id)}
                  disabled={isCurrent || checkingOut === plan.id}
                  className={cn(
                    "mt-5 flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-opacity disabled:opacity-60",
                    isCurrent
                      ? "border border-accent-violet/40 text-accent-violet"
                      : "bg-gradient-to-r from-accent-violet to-accent-blue text-white hover:opacity-90"
                  )}
                >
                  {checkingOut === plan.id && <Loader2 className="h-4 w-4 animate-spin" />}
                  {isCurrent ? "Current plan" : "Subscribe"}
                  {!isCurrent && checkingOut !== plan.id && <ExternalLink className="h-3.5 w-3.5" />}
                </button>
              </div>
            );
          })}

          {plans.length === 0 && (
            <p className="col-span-full text-sm text-ink-faint">
              No plans are available yet — check back soon.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
