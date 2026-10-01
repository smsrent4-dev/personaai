
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Banknote,
  Check,
  CreditCard,
  ExternalLink,
  Loader2,
} from "lucide-react";
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
type PaymentMethod = "card" | "bank_transfer";
export default function BillingPage() {
  const queryClient = useQueryClient();
  const [checkingOut, setCheckingOut] = useState<string | null>(null);
  const [paymentMethod, setPaymentMethod] =
    useState<PaymentMethod>("card");
  const plansQuery = useQuery({
    queryKey: ["billing-plans"],
    queryFn: async () =>
      (await api.get<BillingPlan[]>("/billing/plans")).data,
  });
  const subscriptionQuery = useQuery({
    queryKey: ["billing-subscription"],
    queryFn: async () =>
      (await api.get<Subscription | null>("/billing/subscription")).data,
  });
  const plans = plansQuery.data ?? [];
  const subscription = subscriptionQuery.data;
  const currentPlanId = subscription?.plan_id ?? null;
  async function handleSubscribe(planId: string) {
    const checkoutKey = `${planId}:${paymentMethod}`;
    setCheckingOut(checkoutKey);
    try {
      const { data } = await api.post("/billing/checkout", {
        plan_id: planId,
        payment_method: paymentMethod,
      });
      if (data.activated_directly) {
        toast.success("You're on this plan now.");
        await queryClient.invalidateQueries({
          queryKey: ["billing-subscription"],
        });
        setCheckingOut(null);
        return;
      }
      if (!data.authorization_url) {
        throw new Error("Paystack did not return a checkout URL.");
      }
      window.location.href = data.authorization_url;
    } catch (err) {
      toast.error(
        apiErrorMessage(err, "Couldn't start checkout"),
      );
      setCheckingOut(null);
    }
  }
  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="font-display text-xl font-semibold">
          Billing
        </h1>
        <p className="text-sm text-ink-muted">
          Manage your plan and payment.
        </p>
      </div>
      {/* Current subscription */}
      <div className="panel p-5">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-accent-violet/15">
            <CreditCard className="h-5 w-5 text-accent-violet" />
          </div>
          <div className="flex-1">
            {subscriptionQuery.isLoading ? (
              <p className="text-sm text-ink-muted">
                Loading your subscription…
              </p>
            ) : subscription ? (
              (() => {
                const currentSubPlan = plans.find(
                  (p) => p.id === subscription.plan_id,
                );
                const isFreePlan = currentSubPlan
                  ? Number(currentSubPlan.price_amount) === 0
                  : false;
                return (
                  <>
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium text-ink">
                        {currentSubPlan?.name ?? "Subscription"}
                      </p>
                      <span
                        className={cn(
                          "rounded-full px-2 py-0.5 text-[10px]",
                          STATUS_STYLES[subscription.status],
                        )}
                      >
                        {subscription.status.replace("_", " ")}
                      </span>
                    </div>
                    {subscription.current_period_end &&
                      subscription.status === "active" && (
                        <p className="text-xs text-ink-faint">
                          Renews{" "}
                          {new Date(
                            subscription.current_period_end,
                          ).toLocaleDateString()}
                        </p>
                      )}
                    {subscription.status === "incomplete" &&
                      !isFreePlan && (
                        <p className="text-xs text-ink-faint">
                          Waiting for payment confirmation.
                        </p>
                      )}
                    {subscription.status === "past_due" && (
                      <p className="text-xs text-accent-pink">
                        Your last payment failed — update your payment
                        method to avoid interruption.
                      </p>
                    )}
                  </>
                );
              })()
            ) : (
              <p className="text-sm text-ink-muted">
                You don't have a subscription yet — pick a plan below.
              </p>
            )}
          </div>
        </div>
      </div>
      {/* Payment method */}
      <div className="panel p-5">
        <div className="mb-4">
          <p className="text-sm font-medium text-ink">
            Payment method
          </p>
          <p className="mt-1 text-xs text-ink-muted">
            Choose how you want to pay.
          </p>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <button
            type="button"
            onClick={() => setPaymentMethod("card")}
            className={cn(
              "flex items-center gap-3 rounded-xl border p-4 text-left transition-all",
              paymentMethod === "card"
                ? "border-accent-violet/50 bg-accent-violet/10"
                : "border-ink-faint/15 bg-ink/5 hover:border-ink-faint/30",
            )}
          >
            <div
              className={cn(
                "flex h-10 w-10 shrink-0 items-center justify-center rounded-lg",
                paymentMethod === "card"
                  ? "bg-accent-violet/15 text-accent-violet"
                  : "bg-ink-faint/10 text-ink-muted",
              )}
            >
              <CreditCard className="h-5 w-5" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-ink">
                Card
              </p>
              <p className="mt-0.5 text-xs text-ink-muted">
                Pay with debit or credit card.
              </p>
            </div>
            <div
              className={cn(
                "flex h-5 w-5 items-center justify-center rounded-full border",
                paymentMethod === "card"
                  ? "border-accent-violet bg-accent-violet"
                  : "border-ink-faint/30",
              )}
            >
              {paymentMethod === "card" && (
                <Check className="h-3 w-3 text-white" />
              )}
            </div>
          </button>
          <button
            type="button"
            onClick={() => setPaymentMethod("bank_transfer")}
            className={cn(
              "flex items-center gap-3 rounded-xl border p-4 text-left transition-all",
              paymentMethod === "bank_transfer"
                ? "border-accent-blue/50 bg-accent-blue/10"
                : "border-ink-faint/15 bg-ink/5 hover:border-ink-faint/30",
            )}
          >
            <div
              className={cn(
                "flex h-10 w-10 shrink-0 items-center justify-center rounded-lg",
                paymentMethod === "bank_transfer"
                  ? "bg-accent-blue/15 text-accent-blue"
                  : "bg-ink-faint/10 text-ink-muted",
              )}
            >
              <Banknote className="h-5 w-5" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-ink">
                Bank Transfer
              </p>
              <p className="mt-0.5 text-xs text-ink-muted">
                Pay directly through bank transfer.
              </p>
            </div>
            <div
              className={cn(
                "flex h-5 w-5 items-center justify-center rounded-full border",
                paymentMethod === "bank_transfer"
                  ? "border-accent-blue bg-accent-blue"
                  : "border-ink-faint/30",
              )}
            >
              {paymentMethod === "bank_transfer" && (
                <Check className="h-3 w-3 text-white" />
              )}
            </div>
          </button>
        </div>
      </div>
      {/* Plans */}
      {plansQuery.isLoading ? (
        <div className="flex items-center gap-2">
          <Loader2 className="h-6 w-6 animate-spin text-ink-faint" />
          <span className="text-sm text-ink-muted">
            Loading plans…
          </span>
        </div>
      ) : plansQuery.isError ? (
        <div className="panel p-5">
          <p className="text-sm font-medium text-accent-pink">
            Couldn't load billing plans.
          </p>
          <p className="mt-1 text-xs text-ink-muted">
            Please refresh the page and try again.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {plans.map((plan) => {
            const isCurrent = plan.id === currentPlanId;
            const checkoutKey = `${plan.id}:${paymentMethod}`;
            const isCheckingOut =
              checkingOut === checkoutKey;
            const isFreePlan =
              Number(plan.price_amount) === 0;
            return (
              <div
                key={plan.id}
                className={cn(
                  "panel flex flex-col p-5",
                  isCurrent &&
                    "panel-glow border-accent-violet/40",
                )}
              >
                {isCurrent && (
                  <div className="mb-3 flex items-center gap-1.5 text-xs font-medium text-accent-violet">
                    <Check className="h-3.5 w-3.5" />
                    Current plan
                  </div>
                )}
                <p className="font-display text-base font-semibold text-ink">
                  {plan.name}
                </p>
                <p className="mt-1 font-mono text-2xl text-ink">
                  {formatPrice(
                    plan.price_amount,
                    plan.currency,
                    plan.interval,
                  )}
                </p>
                {plan.description && (
                  <p className="mt-2 text-xs text-ink-muted">
                    {plan.description}
                  </p>
                )}
                <ul className="mt-4 flex-1 space-y-2 text-xs text-ink-muted">
                  <li className="flex items-center gap-2">
                    <Check className="h-3.5 w-3.5 shrink-0 text-accent-green" />
                    {formatLimit(
                      plan.max_agents,
                      "agents",
                    )}
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="h-3.5 w-3.5 shrink-0 text-accent-green" />
                    {formatLimit(
                      plan.max_messages_per_month,
                      "messages/mo",
                    )}
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="h-3.5 w-3.5 shrink-0 text-accent-green" />
                    {formatLimit(
                      plan.max_knowledge_documents,
                      "knowledge docs",
                    )}
                  </li>
                  <li className="flex items-center gap-2">
                    <Check className="h-3.5 w-3.5 shrink-0 text-accent-green" />
                    {formatLimit(
                      plan.max_integrations,
                      "integrations",
                    )}
                  </li>
                </ul>
                <button
                  type="button"
                  onClick={() => handleSubscribe(plan.id)}
                  disabled={isCurrent || isCheckingOut}
                  className={cn(
                    "mt-5 flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-opacity",
                    "disabled:cursor-not-allowed disabled:opacity-60",
                    isCurrent
                      ? "border border-accent-violet/40 text-accent-violet"
                      : "bg-gradient-to-r from-accent-violet to-accent-blue text-white hover:opacity-90",
                  )}
                >
                  {isCheckingOut && (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  )}
                  {isCurrent
                    ? "Current plan"
                    : isFreePlan
                      ? "Activate plan"
                      : paymentMethod === "bank_transfer"
                        ? "Pay with Bank Transfer"
                        : "Pay with Card"}
                  {!isCurrent &&
                    !isCheckingOut &&
                    !isFreePlan && (
                      <ExternalLink className="h-3.5 w-3.5" />
                    )}
                </button>
                {!isCurrent && !isFreePlan && (
                  <p className="mt-2 text-center text-[10px] text-ink-faint">
                    Secure checkout via Paystack
                  </p>
                )}
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
