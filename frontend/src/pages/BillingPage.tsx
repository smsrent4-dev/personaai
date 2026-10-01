import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Banknote,
  Check,
  CreditCard,
  ExternalLink,
  Loader2,
  ShieldCheck,
  Sparkles,
  ArrowRight,
} from "lucide-react";
import { toast } from "sonner";
import { api, apiErrorMessage } from "@/lib/api";
import { formatLimit, formatPrice } from "@/lib/billing-format";
import { cn } from "@/lib/utils";
import type { BillingPlan, Subscription } from "@/types";

const STATUS_STYLES: Record<Subscription["status"], string> = {
  active: "bg-accent-green/10 text-accent-green border-accent-green/20",
  incomplete: "bg-accent-amber/10 text-accent-amber border-accent-amber/20",
  past_due: "bg-accent-pink/10 text-accent-pink border-accent-pink/20",
  canceled: "bg-ink-faint/10 text-ink-faint border-ink-faint/20",
};

type PaymentMethod = "card" | "bank_transfer";

export default function BillingPage() {
  const queryClient = useQueryClient();

  const [checkingOut, setCheckingOut] = useState<string | null>(null);
  const [selectedPaymentMethod, setSelectedPaymentMethod] =
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

  async function handleSubscribe(
    plan: BillingPlan,
    paymentMethod: PaymentMethod,
  ) {
    const isFreePlan = Number(plan.price_amount) === 0;
    const checkoutKey = `${plan.id}:${paymentMethod}`;

    setCheckingOut(checkoutKey);

    try {
      const { data } = await api.post("/billing/checkout", {
        plan_id: plan.id,
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
        apiErrorMessage(
          err,
          isFreePlan
            ? "Couldn't activate this plan"
            : "Couldn't start checkout",
        ),
      );

      setCheckingOut(null);
    }
  }

  const selectedMethodLabel =
    selectedPaymentMethod === "card"
      ? "Card"
      : "Bank Transfer";

  return (
    <div className="relative mx-auto w-full max-w-7xl overflow-hidden pb-10">
      {/* Ambient background glow */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -left-32 top-0 h-72 w-72 rounded-full bg-accent-violet/10 blur-3xl"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-32 top-64 h-72 w-72 rounded-full bg-accent-blue/10 blur-3xl"
      />

      <div className="relative space-y-6 sm:space-y-8">
        {/* ====================================================== */}
        {/* HEADER */}
        {/* ====================================================== */}

        <section className="animate-in fade-in slide-in-from-bottom-3 duration-500">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-accent-violet/20 bg-accent-violet/5 px-3 py-1 text-[11px] font-medium text-accent-violet">
                <Sparkles className="h-3 w-3" />
                Simple & secure billing
              </div>

              <h1 className="font-display text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
                Choose your plan
              </h1>

              <p className="mt-1.5 max-w-xl text-sm leading-6 text-ink-muted">
                Upgrade your PersonaAI workspace with the plan
                that fits your business.
              </p>
            </div>

            <div className="flex items-center gap-2 text-xs text-ink-faint">
              <ShieldCheck className="h-4 w-4 text-accent-green" />
              Secure payments via Paystack
            </div>
          </div>
        </section>

        {/* ====================================================== */}
        {/* CURRENT SUBSCRIPTION */}
        {/* ====================================================== */}

        <section className="animate-in fade-in slide-in-from-bottom-3 duration-500 delay-75">
          <div className="relative overflow-hidden rounded-2xl border border-ink-faint/10 bg-ink/5 p-4 shadow-sm backdrop-blur-sm sm:p-5">
            {/* Decorative glow */}
            <div
              aria-hidden="true"
              className="absolute -right-16 -top-16 h-32 w-32 rounded-full bg-accent-violet/10 blur-3xl"
            />

            <div className="relative flex flex-col gap-4 sm:flex-row sm:items-center">
              <div className="flex items-center gap-3">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-accent-violet/20 bg-accent-violet/10">
                  <CreditCard className="h-5 w-5 text-accent-violet" />
                </div>

                <div className="min-w-0">
                  <p className="text-[11px] font-medium uppercase tracking-wider text-ink-faint">
                    Current subscription
                  </p>

                  {subscriptionQuery.isLoading ? (
                    <div className="mt-1 h-4 w-32 animate-pulse rounded bg-ink-faint/10" />
                  ) : subscription ? (
                    (() => {
                      const currentSubPlan = plans.find(
                        (p) => p.id === subscription.plan_id,
                      );

                      return (
                        <p className="mt-0.5 truncate text-sm font-semibold text-ink">
                          {currentSubPlan?.name ?? "Subscription"}
                        </p>
                      );
                    })()
                  ) : (
                    <p className="mt-0.5 text-sm font-medium text-ink">
                      No active plan
                    </p>
                  )}
                </div>
              </div>

              <div className="hidden h-8 w-px bg-ink-faint/10 sm:block" />

              <div className="flex-1">
                {subscriptionQuery.isLoading ? (
                  <p className="text-xs text-ink-muted">
                    Loading subscription details…
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
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                        <span
                          className={cn(
                            "inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-medium capitalize",
                            STATUS_STYLES[subscription.status],
                          )}
                        >
                          <span className="mr-1.5 h-1.5 w-1.5 rounded-full bg-current" />
                          {subscription.status.replace("_", " ")}
                        </span>

                        {subscription.current_period_end &&
                          subscription.status === "active" && (
                            <span className="text-xs text-ink-faint">
                              Renews{" "}
                              {new Date(
                                subscription.current_period_end,
                              ).toLocaleDateString()}
                            </span>
                          )}

                        {subscription.status === "incomplete" &&
                          !isFreePlan && (
                            <span className="text-xs text-ink-faint">
                              Waiting for payment confirmation.
                            </span>
                          )}

                        {subscription.status === "past_due" && (
                          <span className="text-xs text-accent-pink">
                            Payment failed — update your payment method.
                          </span>
                        )}
                      </div>
                    );
                  })()
                ) : (
                  <p className="text-xs leading-5 text-ink-muted">
                    Choose a plan below to get started.
                  </p>
                )}
              </div>
            </div>
          </div>
        </section>

        {/* ====================================================== */}
        {/* PAYMENT METHOD */}
        {/* ====================================================== */}

        <section className="animate-in fade-in slide-in-from-bottom-3 duration-500 delay-100">
          <div className="mb-3">
            <h2 className="text-sm font-semibold text-ink">
              Payment method
            </h2>

            <p className="mt-1 text-xs text-ink-muted">
              Select how you'd like to pay for your plan.
            </p>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {/* CARD */}
            <button
              type="button"
              onClick={() => setSelectedPaymentMethod("card")}
              className={cn(
                "group relative overflow-hidden rounded-2xl border p-4 text-left outline-none transition-all duration-300 sm:p-5",
                "focus-visible:ring-2 focus-visible:ring-accent-violet/50",
                selectedPaymentMethod === "card"
                  ? "border-accent-violet/50 bg-accent-violet/[0.07] shadow-lg shadow-accent-violet/5"
                  : "border-ink-faint/10 bg-ink/5 hover:-translate-y-0.5 hover:border-ink-faint/25 hover:bg-ink/10",
              )}
            >
              {selectedPaymentMethod === "card" && (
                <div
                  aria-hidden="true"
                  className="absolute -right-10 -top-10 h-24 w-24 rounded-full bg-accent-violet/15 blur-2xl"
                />
              )}

              <div className="relative flex items-center gap-3.5">
                <div
                  className={cn(
                    "flex h-11 w-11 shrink-0 items-center justify-center rounded-xl transition-all duration-300",
                    selectedPaymentMethod === "card"
                      ? "bg-accent-violet/15 text-accent-violet"
                      : "bg-ink-faint/10 text-ink-muted group-hover:text-ink",
                  )}
                >
                  <CreditCard className="h-5 w-5" />
                </div>

                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-semibold text-ink">
                      Card
                    </p>

                    {selectedPaymentMethod === "card" && (
                      <span className="rounded-full bg-accent-violet/10 px-2 py-0.5 text-[9px] font-medium text-accent-violet">
                        Selected
                      </span>
                    )}
                  </div>

                  <p className="mt-0.5 text-xs leading-5 text-ink-muted">
                    Pay with your debit or credit card.
                  </p>
                </div>

                <div
                  className={cn(
                    "flex h-5 w-5 shrink-0 items-center justify-center rounded-full border transition-all duration-300",
                    selectedPaymentMethod === "card"
                      ? "scale-110 border-accent-violet bg-accent-violet"
                      : "border-ink-faint/30",
                  )}
                >
                  {selectedPaymentMethod === "card" && (
                    <Check className="h-3 w-3 text-white" />
                  )}
                </div>
              </div>
            </button>

            {/* BANK TRANSFER */}
            <button
              type="button"
              onClick={() =>
                setSelectedPaymentMethod("bank_transfer")
              }
              className={cn(
                "group relative overflow-hidden rounded-2xl border p-4 text-left outline-none transition-all duration-300 sm:p-5",
                "focus-visible:ring-2 focus-visible:ring-accent-blue/50",
                selectedPaymentMethod === "bank_transfer"
                  ? "border-accent-blue/50 bg-accent-blue/[0.07] shadow-lg shadow-accent-blue/5"
                  : "border-ink-faint/10 bg-ink/5 hover:-translate-y-0.5 hover:border-ink-faint/25 hover:bg-ink/10",
              )}
            >
              {selectedPaymentMethod === "bank_transfer" && (
                <div
                  aria-hidden="true"
                  className="absolute -right-10 -top-10 h-24 w-24 rounded-full bg-accent-blue/15 blur-2xl"
                />
              )}

              <div className="relative flex items-center gap-3.5">
                <div
                  className={cn(
                    "flex h-11 w-11 shrink-0 items-center justify-center rounded-xl transition-all duration-300",
                    selectedPaymentMethod === "bank_transfer"
                      ? "bg-accent-blue/15 text-accent-blue"
                      : "bg-ink-faint/10 text-ink-muted group-hover:text-ink",
                  )}
                >
                  <Banknote className="h-5 w-5" />
                </div>

                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-semibold text-ink">
                      Bank Transfer
                    </p>

                    {selectedPaymentMethod === "bank_transfer" && (
                      <span className="rounded-full bg-accent-blue/10 px-2 py-0.5 text-[9px] font-medium text-accent-blue">
                        Selected
                      </span>
                    )}
                  </div>

                  <p className="mt-0.5 text-xs leading-5 text-ink-muted">
                    Pay directly from your bank account.
                  </p>
                </div>

                <div
                  className={cn(
                    "flex h-5 w-5 shrink-0 items-center justify-center rounded-full border transition-all duration-300",
                    selectedPaymentMethod === "bank_transfer"
                      ? "scale-110 border-accent-blue bg-accent-blue"
                      : "border-ink-faint/30",
                  )}
                >
                  {selectedPaymentMethod === "bank_transfer" && (
                    <Check className="h-3 w-3 text-white" />
                  )}
                </div>
              </div>
            </button>
          </div>

          {/* Selected payment indicator */}
          <div className="mt-3 flex items-center justify-between rounded-xl border border-ink-faint/10 bg-ink/5 px-3.5 py-2.5">
            <span className="text-[11px] text-ink-faint">
              Selected payment method
            </span>

            <span className="text-xs font-medium text-ink">
              {selectedMethodLabel}
            </span>
          </div>
        </section>

        {/* ====================================================== */}
        {/* PLANS */}
        {/* ====================================================== */}

        <section className="animate-in fade-in slide-in-from-bottom-3 duration-500 delay-150">
          <div className="mb-4 flex items-end justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-ink">
                Available plans
              </h2>

              <p className="mt-1 text-xs text-ink-muted">
                Choose the plan that matches your workflow.
              </p>
            </div>

            <div className="hidden items-center gap-1.5 text-[10px] text-ink-faint sm:flex">
              <ShieldCheck className="h-3.5 w-3.5 text-accent-green" />
              Secure checkout
            </div>
          </div>

          {plansQuery.isLoading ? (
            <div className="flex min-h-40 items-center justify-center rounded-2xl border border-ink-faint/10 bg-ink/5">
              <div className="flex flex-col items-center gap-3">
                <Loader2 className="h-6 w-6 animate-spin text-accent-violet" />

                <p className="text-xs text-ink-muted">
                  Loading plans…
                </p>
              </div>
            </div>
          ) : plans.length > 0 ? (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {plans.map((plan, index) => {
                const isCurrent = plan.id === currentPlanId;
                const isFreePlan =
                  Number(plan.price_amount) === 0;

                const checkoutKey = `${plan.id}:${selectedPaymentMethod}`;

                const isCheckingOut =
                  checkingOut === checkoutKey;

                return (
                  <div
                    key={plan.id}
                    className={cn(
                      "group relative flex flex-col overflow-hidden rounded-2xl border p-5 opacity-0",
                      "animate-in fade-in slide-in-from-bottom-4 fill-mode-forwards",
                      "transition-all duration-300",
                      "hover:-translate-y-1 hover:shadow-xl",
                      isCurrent
                        ? "border-accent-violet/40 bg-accent-violet/[0.035] shadow-lg shadow-accent-violet/5"
                        : "border-ink-faint/10 bg-ink/5 hover:border-ink-faint/20",
                    )}
                    style={{
                      animationDelay: `${150 + index * 80}ms`,
                    }}
                  >
                    {/* Top accent */}
                    <div
                      aria-hidden="true"
                      className={cn(
                        "absolute inset-x-0 top-0 h-px opacity-0 transition-opacity duration-300 group-hover:opacity-100",
                        isCurrent
                          ? "bg-accent-violet opacity-100"
                          : "bg-gradient-to-r from-accent-violet/0 via-accent-violet/60 to-accent-blue/0",
                      )}
                    />

                    {/* Current plan badge */}
                    {isCurrent && (
                      <div className="mb-4 flex items-center gap-1.5 text-[10px] font-medium text-accent-violet">
                        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-accent-violet/10">
                          <Check className="h-3 w-3" />
                        </span>
                        Current plan
                      </div>
                    )}

                    {!isCurrent && (
                      <div className="mb-4 h-5" />
                    )}

                    {/* Plan heading */}
                    <div>
                      <h3 className="font-display text-base font-semibold text-ink">
                        {plan.name}
                      </h3>

                      {plan.description && (
                        <p className="mt-1.5 min-h-10 text-xs leading-5 text-ink-muted">
                          {plan.description}
                        </p>
                      )}
                    </div>

                    {/* Price */}
                    <div className="mt-5 flex items-baseline gap-2">
                      <span className="font-mono text-2xl font-medium tracking-tight text-ink sm:text-3xl">
                        {formatPrice(
                          plan.price_amount,
                          plan.currency,
                          plan.interval,
                        )}
                      </span>
                    </div>

                    <div className="mt-1 text-[10px] text-ink-faint">
                      {plan.interval === "monthly"
                        ? "Billed monthly"
                        : plan.interval === "yearly"
                          ? "Billed yearly"
                          : ""}
                    </div>

                    {/* Divider */}
                    <div className="my-5 h-px bg-ink-faint/10" />

                    {/* Features */}
                    <ul className="flex-1 space-y-3">
                      <li className="flex items-start gap-2.5 text-xs text-ink-muted">
                        <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-accent-green/10">
                          <Check className="h-2.5 w-2.5 text-accent-green" />
                        </span>

                        <span>
                          {formatLimit(
                            plan.max_agents,
                            "agents",
                          )}
                        </span>
                      </li>

                      <li className="flex items-start gap-2.5 text-xs text-ink-muted">
                        <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-accent-green/10">
                          <Check className="h-2.5 w-2.5 text-accent-green" />
                        </span>

                        <span>
                          {formatLimit(
                            plan.max_messages_per_month,
                            "messages/mo",
                          )}
                        </span>
                      </li>

                      <li className="flex items-start gap-2.5 text-xs text-ink-muted">
                        <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-accent-green/10">
                          <Check className="h-2.5 w-2.5 text-accent-green" />
                        </span>

                        <span>
                          {formatLimit(
                            plan.max_knowledge_documents,
                            "knowledge docs",
                          )}
                        </span>
                      </li>

                      <li className="flex items-start gap-2.5 text-xs text-ink-muted">
                        <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-accent-green/10">
                          <Check className="h-2.5 w-2.5 text-accent-green" />
                        </span>

                        <span>
                          {formatLimit(
                            plan.max_integrations,
                            "integrations",
                          )}
                        </span>
                      </li>
                    </ul>

                    {/* CTA */}
                    <button
                      type="button"
                      onClick={() =>
                        handleSubscribe(
                          plan,
                          selectedPaymentMethod,
                        )
                      }
                      disabled={isCurrent || isCheckingOut}
                      className={cn(
                        "mt-6 flex min-h-11 w-full items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-xs font-semibold outline-none transition-all duration-300",
                        "focus-visible:ring-2 focus-visible:ring-accent-violet/50",
                        "disabled:cursor-not-allowed disabled:opacity-50",
                        isCurrent
                          ? "border border-accent-violet/25 bg-accent-violet/5 text-accent-violet"
                          : "bg-gradient-to-r from-accent-violet to-accent-blue text-white shadow-lg shadow-accent-violet/10 hover:-translate-y-0.5 hover:shadow-xl hover:shadow-accent-violet/20",
                      )}
                    >
                      {isCheckingOut ? (
                        <>
                          <Loader2 className="h-4 w-4 animate-spin" />
                          <span>Opening checkout…</span>
                        </>
                      ) : isCurrent ? (
                        <>
                          <Check className="h-4 w-4" />
                          <span>Current plan</span>
                        </>
                      ) : isFreePlan ? (
                        <>
                          <Sparkles className="h-4 w-4" />
                          <span>Activate plan</span>
                        </>
                      ) : (
                        <>
                          <span>
                            {selectedPaymentMethod ===
                            "bank_transfer"
                              ? "Pay with Bank Transfer"
                              : "Pay with Card"}
                          </span>

                          <ArrowRight className="h-3.5 w-3.5 transition-transform duration-300 group-hover:translate-x-0.5" />
                        </>
                      )}
                    </button>

                    {!isCurrent && !isFreePlan && (
                      <p className="mt-2.5 text-center text-[9px] text-ink-faint">
                        Secure checkout •{" "}
                        {selectedMethodLabel}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="flex min-h-40 items-center justify-center rounded-2xl border border-dashed border-ink-faint/15 bg-ink/5 p-6 text-center">
              <div>
                <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-ink-faint/10">
                  <CreditCard className="h-5 w-5 text-ink-faint" />
                </div>

                <p className="mt-3 text-sm font-medium text-ink">
                  No plans available
                </p>

                <p className="mt-1 text-xs text-ink-faint">
                  Check back soon for available billing plans.
                </p>
              </div>
            </div>
          )}
        </section>

        {/* ====================================================== */}
        {/* FOOTER TRUST */}
        {/* ====================================================== */}

        <div className="flex flex-col items-center justify-center gap-2 border-t border-ink-faint/10 pt-6 text-center sm:flex-row sm:gap-3">
          <div className="flex items-center gap-1.5 text-[10px] text-ink-faint">
            <ShieldCheck className="h-3.5 w-3.5 text-accent-green" />
            Secure payment processing
          </div>

          <span className="hidden text-ink-faint/30 sm:block">
            •
          </span>

          <p className="text-[10px] text-ink-faint">
            Your payment details are handled securely by Paystack.
          </p>
        </div>
      </div>
    </div>
  );
}
