import { useMemo, useState, type ElementType } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  MessageSquare,
  ShoppingBag,
  DollarSign,
  UserPlus,
  ArrowUpRight,
  ArrowDownRight,
  Bot,
  BookOpen,
  Package,
  Workflow,
  BarChart3,
  MessageSquare as FeedConversation,
  ShoppingBag as FeedOrder,
  Receipt as FeedReceipt,
  CheckCircle2 as FeedPaid,
  AlertTriangle as FeedAlert,
  Bell,
  ArrowRight,
  Activity,
  Sparkles,
  Zap,
  CircleCheck,
  CircleAlert,
  Wifi,
  ChevronRight,
  Send,
  Users,
  BrainCircuit,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from "recharts";

import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";

import type {
  Agent,
  Conversation,
  Order,
  Customer,
  AnalyticsSummary,
  Notification,
  NotificationType,
} from "@/types";

/* -------------------------------------------------------------------------- */
/* Configuration                                                              */
/* -------------------------------------------------------------------------- */

const RANGE_OPTIONS = [
  { label: "Last 7 days", days: 7 },
  { label: "Last 14 days", days: 14 },
  { label: "Last 30 days", days: 30 },
  { label: "Last 90 days", days: 90 },
];

const CHANNEL_COLORS: Record<string, string> = {
  whatsapp: "#22C55E",
  telegram: "#3B82F6",
  instagram: "#EC4899",
  messenger: "#FB923C",
  discord: "#8B5CF6",
  slack: "#A855F7",
  web_widget: "#22D3EE",
  voice: "#F59E0B",
};

const ORDER_STATUS_STYLES: Record<string, string> = {
  pending: "bg-accent-amber/10 text-accent-amber border-accent-amber/20",
  confirmed: "bg-accent-blue/10 text-accent-blue border-accent-blue/20",
  preparing:
    "bg-accent-violet/10 text-accent-violet border-accent-violet/20",
  ready: "bg-accent-cyan/10 text-accent-cyan border-accent-cyan/20",
  delivered:
    "bg-accent-green/10 text-accent-green border-accent-green/20",
  cancelled: "bg-ink-faint/10 text-ink-faint border-base-border",
  refunded: "bg-accent-pink/10 text-accent-pink border-accent-pink/20",
};

const FEED_ICONS: Record<NotificationType, ElementType> = {
  new_conversation: FeedConversation,
  knowledge_ingestion_failed: FeedAlert,
  integration_error: FeedAlert,
  new_order: FeedOrder,
  receipt_uploaded: FeedReceipt,
  payment_confirmed: FeedPaid,
};

const STAT_COLOR_STYLES: Record<string, string> = {
  "accent-violet": "bg-accent-violet/10 text-accent-violet",
  "accent-green": "bg-accent-green/10 text-accent-green",
  "accent-blue": "bg-accent-blue/10 text-accent-blue",
  "accent-orange": "bg-accent-orange/10 text-accent-orange",
};

/* -------------------------------------------------------------------------- */
/* Main Dashboard                                                             */
/* -------------------------------------------------------------------------- */

export default function DashboardPage() {
  const user = useAuthStore((s) => s.user);
  const [rangeDays, setRangeDays] = useState(30);

  /* ------------------------------------------------------------------------ */
  /* Queries                                                                  */
  /* ------------------------------------------------------------------------ */

  const analyticsQuery = useQuery({
    queryKey: ["analytics-summary", rangeDays],
    queryFn: async () =>
      (
        await api.get<AnalyticsSummary>("/analytics/summary", {
          params: { days: rangeDays },
        })
      ).data,
  });

  const agentsQuery = useQuery({
    queryKey: ["agents"],
    queryFn: async () => (await api.get<Agent[]>("/agents")).data,
  });

  const conversationsQuery = useQuery({
    queryKey: ["conversations"],
    queryFn: async () =>
      (await api.get<Conversation[]>("/conversations")).data,
  });

  const ordersQuery = useQuery({
    queryKey: ["orders"],
    queryFn: async () => (await api.get<Order[]>("/orders")).data,
  });

  const customersQuery = useQuery({
    queryKey: ["customers"],
    queryFn: async () => (await api.get<Customer[]>("/customers")).data,
  });

  const notificationsQuery = useQuery({
    queryKey: ["notifications"],
    queryFn: async () =>
      (await api.get<Notification[]>("/notifications")).data,
  });

  /* ------------------------------------------------------------------------ */
  /* Data                                                                     */
  /* ------------------------------------------------------------------------ */

  const analytics = analyticsQuery.data;
  const agents = agentsQuery.data ?? [];
  const conversations = conversationsQuery.data ?? [];
  const orders = ordersQuery.data ?? [];
  const customers = customersQuery.data ?? [];
  const notifications = notificationsQuery.data ?? [];

  const firstName =
    user?.full_name?.trim()?.split(/\s+/)[0] || "there";

  /* ------------------------------------------------------------------------ */
  /* Date windows                                                             */
  /* ------------------------------------------------------------------------ */

  const cutoffs = useMemo(() => {
    const now = Date.now();
    const windowMs = rangeDays * 24 * 60 * 60 * 1000;

    return {
      current: now - windowMs,
      previous: now - 2 * windowMs,
    };
  }, [rangeDays]);

  function windowDelta(items: { created_at: string }[]) {
    let current = 0;
    let previous = 0;

    for (const item of items) {
      const time = new Date(item.created_at).getTime();

      if (time >= cutoffs.current) {
        current += 1;
      } else if (time >= cutoffs.previous) {
        previous += 1;
      }
    }

    const pct =
      previous === 0
        ? current > 0
          ? 100
          : 0
        : Math.round(((current - previous) / previous) * 100);

    return {
      current,
      previous,
      pct,
    };
  }

  const conversationsWindow = windowDelta(conversations);
  const ordersWindow = windowDelta(orders);
  const customersWindow = windowDelta(customers);

  /* ------------------------------------------------------------------------ */
  /* Revenue                                                                  */
  /* ------------------------------------------------------------------------ */

  const paidRevenue = orders
    .filter(
      (order) =>
        order.payment_status === "paid" &&
        new Date(order.created_at).getTime() >= cutoffs.current
    )
    .reduce((sum, order) => sum + Number(order.total_amount), 0);

  const previousPaidRevenue = orders
    .filter(
      (order) =>
        order.payment_status === "paid" &&
        new Date(order.created_at).getTime() >= cutoffs.previous &&
        new Date(order.created_at).getTime() < cutoffs.current
    )
    .reduce((sum, order) => sum + Number(order.total_amount), 0);

  const revenuePct =
    previousPaidRevenue === 0
      ? paidRevenue > 0
        ? 100
        : 0
      : Math.round(
          ((paidRevenue - previousPaidRevenue) /
            previousPaidRevenue) *
            100
        );

  /*
   * NGN is the safer default for PersonaAI.
   * If the backend returns another currency, that currency is respected.
   */
  const currency = orders[0]?.currency ?? "NGN";

  const currencyFmt = new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  });

  /* ------------------------------------------------------------------------ */
  /* Channel breakdown                                                        */
  /* ------------------------------------------------------------------------ */

  const channelBreakdown = useMemo(() => {
    const counts = conversations.reduce<Record<string, number>>(
      (acc, conversation) => {
        const platform = conversation.platform || "unknown";

        acc[platform] = (acc[platform] ?? 0) + 1;

        return acc;
      },
      {}
    );

    const total = conversations.length || 1;

    return Object.entries(counts)
      .map(([platform, count]) => ({
        platform,
        count,
        pct: Math.round((count / total) * 100),
      }))
      .sort((a, b) => b.count - a.count);
  }, [conversations]);

  /* ------------------------------------------------------------------------ */
  /* Agent performance                                                        */
  /* ------------------------------------------------------------------------ */

  const agentPerformance = useMemo(() => {
    const convByAgent = conversations.reduce<Record<string, number>>(
      (acc, conversation) => {
        if (conversation.agent_id) {
          acc[conversation.agent_id] =
            (acc[conversation.agent_id] ?? 0) + 1;
        }

        return acc;
      },
      {}
    );

    const byMessages = analytics?.messages_by_agent ?? [];

    return byMessages
      .map((row) => ({
        ...row,
        conversationCount:
          convByAgent[row.agent_id] ?? 0,
        status:
          agents.find((agent) => agent.id === row.agent_id)?.status ??
          "active",
      }))
      .sort((a, b) => b.message_count - a.message_count)
      .slice(0, 4);
  }, [analytics, conversations, agents]);

  /* ------------------------------------------------------------------------ */
  /* Recent data                                                              */
  /* ------------------------------------------------------------------------ */

  const recentOrders = [...orders]
    .sort(
      (a, b) =>
        new Date(b.created_at).getTime() -
        new Date(a.created_at).getTime()
    )
    .slice(0, 5);

  const recentFeed = [...notifications]
    .sort(
      (a, b) =>
        new Date(b.created_at).getTime() -
        new Date(a.created_at).getTime()
    )
    .slice(0, 6);

  /* ------------------------------------------------------------------------ */
  /* Operational metrics                                                      */
  /* ------------------------------------------------------------------------ */

  const paidOrders = orders.filter(
    (order) => order.payment_status === "paid"
  ).length;

  const pendingOrders = orders.filter(
    (order) =>
      order.payment_status !== "paid" &&
      order.status !== "cancelled" &&
      order.status !== "refunded"
  ).length;

  const activeAgents = agents.filter(
    (agent) => agent.status === "active"
  ).length;

  const integrationErrors = notifications.filter(
    (notification) =>
      notification.type === "integration_error"
  ).length;

  /*
   * This is intentionally derived from the data already available to the
   * dashboard. If the backend later exposes a real AI-resolution metric,
   * replace this calculation with the API value.
   */
  const aiResolutionRate =
    conversations.length > 0
      ? Math.min(
          99,
          Math.max(
            0,
            Math.round(
              ((conversations.length -
                integrationErrors) /
                conversations.length) *
                100
            )
          )
        )
      : 0;

  /* ------------------------------------------------------------------------ */
  /* Render                                                                   */
  /* ------------------------------------------------------------------------ */

  return (
    <>
      <style>{`
        @keyframes personaFloat {
          0%, 100% {
            transform: translate3d(0, 0, 0) rotateX(0deg) rotateY(0deg);
          }
          50% {
            transform: translate3d(0, -10px, 0) rotateX(4deg) rotateY(7deg);
          }
        }

        @keyframes personaFloatSlow {
          0%, 100% {
            transform: translate3d(0, 0, 0) rotateZ(0deg);
          }
          50% {
            transform: translate3d(5px, -7px, 0) rotateZ(3deg);
          }
        }

        @keyframes personaPulse {
          0%, 100% {
            opacity: .35;
            transform: scale(.92);
          }
          50% {
            opacity: .7;
            transform: scale(1.08);
          }
        }

        @keyframes personaSpin {
          from {
            transform: rotateX(62deg) rotateZ(0deg);
          }
          to {
            transform: rotateX(62deg) rotateZ(360deg);
          }
        }

        @keyframes personaShimmer {
          0% {
            transform: translateX(-120%);
          }
          100% {
            transform: translateX(120%);
          }
        }

        .persona-3d-float {
          animation: personaFloat 7s ease-in-out infinite;
          transform-style: preserve-3d;
        }

        .persona-3d-float-slow {
          animation: personaFloatSlow 9s ease-in-out infinite;
          transform-style: preserve-3d;
        }

        .persona-pulse {
          animation: personaPulse 4s ease-in-out infinite;
        }

        .persona-ring {
          animation: personaSpin 18s linear infinite;
          transform-style: preserve-3d;
        }

        .persona-shimmer {
          animation: personaShimmer 3.5s ease-in-out infinite;
        }

        .persona-card {
          transform-style: preserve-3d;
          transition:
            transform .35s ease,
            border-color .35s ease,
            box-shadow .35s ease;
        }

        .persona-card:hover {
          transform: translateY(-3px);
        }

        @media (prefers-reduced-motion: reduce) {
          .persona-3d-float,
          .persona-3d-float-slow,
          .persona-pulse,
          .persona-ring,
          .persona-shimmer {
            animation: none !important;
          }

          .persona-card {
            transition: none;
          }
        }
      `}</style>

      <div className="w-full min-w-0 space-y-5 pb-6 sm:space-y-6 lg:space-y-7">
        {/* ------------------------------------------------------------------ */}
        {/* Header / Hero                                                      */}
        {/* ------------------------------------------------------------------ */}

        <section className="relative isolate overflow-hidden rounded-2xl border border-base-border bg-base-panel px-4 py-5 shadow-sm sm:px-6 sm:py-6 lg:px-7 lg:py-7">
          <div className="pointer-events-none absolute inset-0 overflow-hidden">
            <div className="absolute -right-24 -top-32 h-72 w-72 rounded-full bg-accent-violet/10 blur-3xl" />

            <div className="absolute -bottom-40 left-1/3 h-72 w-72 rounded-full bg-accent-blue/5 blur-3xl" />

            <div className="persona-shimmer absolute inset-y-0 left-0 w-1/3 bg-gradient-to-r from-transparent via-white/[0.025] to-transparent" />
          </div>

          <div className="relative flex min-w-0 flex-col gap-7 lg:flex-row lg:items-center lg:justify-between">
            <div className="min-w-0 max-w-2xl">
              <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-accent-violet/20 bg-accent-violet/5 px-3 py-1.5 text-[11px] font-medium text-accent-violet">
                <Sparkles className="h-3.5 w-3.5" />
                PersonaAI Command Center
              </div>

              <h1 className="font-display text-2xl font-semibold tracking-tight text-ink sm:text-3xl lg:text-4xl">
                Good to see you,{" "}
                <span className="text-accent-violet">
                  {firstName}
                </span>
              </h1>

              <p className="mt-2 max-w-xl text-xs leading-6 text-ink-muted sm:text-sm">
                Monitor conversations, AI agents, customers and
                revenue from one intelligent workspace.
              </p>

              <div className="mt-5 flex flex-col gap-2.5 xs:flex-row sm:flex-row">
                <Link
                  to="/conversations"
                  className="inline-flex min-h-10 items-center justify-center gap-2 rounded-xl bg-accent-violet px-4 py-2.5 text-xs font-semibold text-white shadow-lg shadow-accent-violet/10 transition hover:-translate-y-0.5 hover:shadow-accent-violet/20"
                >
                  <MessageSquare className="h-4 w-4" />
                  Open Inbox
                  <ArrowRight className="h-3.5 w-3.5" />
                </Link>

                <Link
                  to="/analytics"
                  className="inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border border-base-border bg-base-panel-2 px-4 py-2.5 text-xs font-semibold text-ink transition hover:border-accent-violet/30 hover:bg-accent-violet/5"
                >
                  <BarChart3 className="h-4 w-4" />
                  View Analytics
                </Link>
              </div>
            </div>

            {/* 3D AI CORE */}
            <div className="relative mx-auto h-52 w-full max-w-xs shrink-0 sm:h-56 lg:mx-0 lg:h-64 lg:w-72">
              <div className="absolute inset-0 [perspective:900px]">
                <div className="persona-3d-float relative mx-auto h-full w-full">
                  {/* Outer glow */}
                  <div className="persona-pulse absolute left-1/2 top-1/2 h-40 w-40 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent-violet/20 blur-3xl" />

                  {/* Orbit rings */}
                  <div className="persona-ring absolute left-1/2 top-1/2 h-40 w-40 -translate-x-1/2 -translate-y-1/2 rounded-full border border-accent-violet/20" />

                  <div
                    className="persona-ring absolute left-1/2 top-1/2 h-32 w-32 -translate-x-1/2 -translate-y-1/2 rounded-full border border-accent-blue/20"
                    style={{
                      animationDirection: "reverse",
                      animationDuration: "13s",
                    }}
                  />

                  {/* Core */}
                  <div className="absolute left-1/2 top-1/2 h-28 w-28 -translate-x-1/2 -translate-y-1/2 [transform-style:preserve-3d] sm:h-32 sm:w-32">
                    <div className="absolute inset-0 rotate-45 rounded-[28%] border border-accent-violet/30 bg-gradient-to-br from-accent-violet/20 via-base-panel-2 to-accent-blue/10 shadow-2xl shadow-accent-violet/10 [transform:translateZ(12px)]" />

                    <div className="absolute inset-4 rounded-full border border-accent-violet/20 bg-base-panel/80 backdrop-blur-xl [transform:translateZ(28px)]" />

                    <div className="absolute left-1/2 top-1/2 flex h-14 w-14 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-2xl border border-accent-violet/30 bg-accent-violet/10 text-accent-violet shadow-lg shadow-accent-violet/10 [transform:translateZ(45px)]">
                      <BrainCircuit className="h-7 w-7" />
                    </div>
                  </div>

                  {/* Floating data cards */}
                  <div className="persona-3d-float-slow absolute left-0 top-7 hidden rounded-xl border border-base-border bg-base-panel/90 px-3 py-2 shadow-xl backdrop-blur-md sm:block">
                    <div className="flex items-center gap-2">
                      <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent-green/10 text-accent-green">
                        <Activity className="h-3.5 w-3.5" />
                      </span>

                      <div>
                        <p className="text-[9px] text-ink-faint">
                          AI Activity
                        </p>

                        <p className="text-xs font-semibold text-ink">
                          Live
                        </p>
                      </div>
                    </div>
                  </div>

                  <div
                    className="persona-3d-float absolute bottom-6 right-0 hidden rounded-xl border border-base-border bg-base-panel/90 px-3 py-2 shadow-xl backdrop-blur-md sm:block"
                    style={{ animationDelay: "-2s" }}
                  >
                    <div className="flex items-center gap-2">
                      <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent-violet/10 text-accent-violet">
                        <Zap className="h-3.5 w-3.5" />
                      </span>

                      <div>
                        <p className="text-[9px] text-ink-faint">
                          Agents
                        </p>

                        <p className="text-xs font-semibold text-ink">
                          {activeAgents} active
                        </p>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ------------------------------------------------------------------ */}
        {/* Controls                                                            */}
        {/* ------------------------------------------------------------------ */}

        <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-center gap-2">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-violet/10 text-accent-violet">
              <BarChart3 className="h-4 w-4" />
            </div>

            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-ink">
                Business Overview
              </p>

              <p className="truncate text-[11px] text-ink-faint">
                Performance across your workspace
              </p>
            </div>
          </div>

          <select
            value={rangeDays}
            onChange={(event) =>
              setRangeDays(Number(event.target.value))
            }
            className="min-h-10 w-full rounded-xl border border-base-border bg-base-panel px-3 py-2 text-xs font-medium text-ink outline-none transition focus:border-accent-violet/40 focus:ring-2 focus:ring-accent-violet/10 sm:w-auto"
          >
            {RANGE_OPTIONS.map((option) => (
              <option key={option.days} value={option.days}>
                {option.label}
              </option>
            ))}
          </select>
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* KPI CARDS                                                           */}
        {/* ------------------------------------------------------------------ */}

        <div className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            icon={MessageSquare}
            color="accent-violet"
            label="Conversations"
            value={conversations.length.toLocaleString()}
            deltaPct={conversationsWindow.pct}
            sublabel={`${conversationsWindow.current} this period`}
          />

          <StatCard
            icon={Users}
            color="accent-green"
            label="Customers"
            value={customers.length.toLocaleString()}
            deltaPct={customersWindow.pct}
            sublabel={`${customersWindow.current} new this period`}
          />

          <StatCard
            icon={DollarSign}
            color="accent-blue"
            label="Revenue"
            value={currencyFmt.format(paidRevenue)}
            deltaPct={revenuePct}
            sublabel="paid revenue this period"
          />

          <StatCard
            icon={BrainCircuit}
            color="accent-orange"
            label="AI Resolution"
            value={`${aiResolutionRate}%`}
            deltaPct={0}
            sublabel={`${activeAgents} active AI agents`}
            neutralDelta
          />
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* MAIN ANALYTICS                                                      */}
        {/* ------------------------------------------------------------------ */}

        <div className="grid min-w-0 grid-cols-1 gap-4 xl:grid-cols-3">
          {/* Messages chart */}
          <div className="persona-card panel min-w-0 overflow-hidden p-4 sm:p-5 xl:col-span-2">
            <div className="mb-5 flex min-w-0 items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-violet/10 text-accent-violet">
                    <MessageSquare className="h-4 w-4" />
                  </span>

                  <p className="truncate text-sm font-semibold text-ink">
                    Messages Overview
                  </p>
                </div>

                <p className="mt-2 text-[11px] leading-5 text-ink-faint">
                  Daily message volume across all connected channels.
                </p>
              </div>

              <Link
                to="/analytics"
                className="hidden shrink-0 items-center gap-1 text-[11px] font-medium text-accent-violet hover:underline sm:flex"
              >
                Details
                <ChevronRight className="h-3.5 w-3.5" />
              </Link>
            </div>

            <div className="h-60 min-w-0 sm:h-72">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart
                  data={analytics?.messages_per_day ?? []}
                  margin={{
                    top: 8,
                    right: 4,
                    left: -22,
                    bottom: 0,
                  }}
                >
                  <defs>
                    <linearGradient
                      id="personaMessagesFill"
                      x1="0"
                      y1="0"
                      x2="0"
                      y2="1"
                    >
                      <stop
                        offset="0%"
                        stopColor="#8B5CF6"
                        stopOpacity={0.3}
                      />

                      <stop
                        offset="100%"
                        stopColor="#8B5CF6"
                        stopOpacity={0}
                      />
                    </linearGradient>
                  </defs>

                  <CartesianGrid
                    stroke="#232544"
                    vertical={false}
                    strokeDasharray="3 5"
                  />

                  <XAxis
                    dataKey="date"
                    tick={{
                      fontSize: 10,
                      fill: "#6B6E89",
                    }}
                    axisLine={false}
                    tickLine={false}
                    tickFormatter={(date: string) =>
                      date.slice(5)
                    }
                    minTickGap={20}
                  />

                  <YAxis
                    tick={{
                      fontSize: 10,
                      fill: "#6B6E89",
                    }}
                    axisLine={false}
                    tickLine={false}
                    allowDecimals={false}
                    width={36}
                  />

                  <Tooltip
                    cursor={{
                      stroke: "#8B5CF6",
                      strokeOpacity: 0.18,
                    }}
                    contentStyle={{
                      borderRadius: 14,
                      border: "1px solid #232544",
                      fontSize: 11,
                      background: "#12132B",
                      color: "#F4F4F8",
                      boxShadow:
                        "0 16px 40px rgba(0,0,0,.25)",
                    }}
                    labelStyle={{
                      color: "#F4F4F8",
                      fontWeight: 600,
                    }}
                  />

                  <Area
                    type="monotone"
                    dataKey="count"
                    name="Messages"
                    stroke="#8B5CF6"
                    strokeWidth={2.5}
                    fill="url(#personaMessagesFill)"
                    activeDot={{
                      r: 4,
                      strokeWidth: 2,
                    }}
                  />
                </AreaChart>
              </ResponsiveContainer>

              {(analytics?.messages_per_day?.length ?? 0) ===
                0 &&
                !analyticsQuery.isLoading && (
                  <div className="pointer-events-none -mt-32 text-center text-xs text-ink-faint sm:-mt-40">
                    No messages yet in this period.
                  </div>
                )}
            </div>
          </div>

          {/* Needs attention */}
          <NeedsAttention
            pendingOrders={pendingOrders}
            integrationErrors={integrationErrors}
            conversationsWaiting={0}
          />
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* CHANNELS + AGENTS                                                   */}
        {/* ------------------------------------------------------------------ */}

        <div className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-2">
          {/* Channel health */}
          <div className="persona-card panel min-w-0 overflow-hidden p-4 sm:p-5">
            <div className="mb-5 flex items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-blue/10 text-accent-blue">
                    <Wifi className="h-4 w-4" />
                  </span>

                  <p className="text-sm font-semibold text-ink">
                    Channel Health
                  </p>
                </div>

                <p className="mt-2 text-[11px] text-ink-faint">
                  Monitor where your customers are contacting you.
                </p>
              </div>

              <Link
                to="/integrations"
                className="text-[11px] font-medium text-accent-violet hover:underline"
              >
                Manage
              </Link>
            </div>

            {channelBreakdown.length === 0 ? (
              <div className="rounded-xl border border-dashed border-base-border bg-base-panel-2/50 px-4 py-7 text-center">
                <Wifi className="mx-auto h-6 w-6 text-ink-faint" />

                <p className="mt-2 text-xs font-medium text-ink">
                  No channels active yet
                </p>

                <p className="mt-1 text-[11px] text-ink-faint">
                  Connect WhatsApp or Telegram to start receiving
                  conversations.
                </p>

                <Link
                  to="/integrations"
                  className="mt-4 inline-flex items-center gap-1.5 text-[11px] font-semibold text-accent-violet"
                >
                  Connect a channel
                  <ArrowRight className="h-3.5 w-3.5" />
                </Link>
              </div>
            ) : (
              <div className="space-y-2.5">
                {channelBreakdown.slice(0, 5).map((channel) => (
                  <ChannelRow
                    key={channel.platform}
                    platform={channel.platform}
                    count={channel.count}
                    pct={channel.pct}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Agent performance */}
          <div className="persona-card panel min-w-0 overflow-hidden p-4 sm:p-5">
            <div className="mb-5 flex items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-violet/10 text-accent-violet">
                    <Bot className="h-4 w-4" />
                  </span>

                  <p className="text-sm font-semibold text-ink">
                    AI Agents
                  </p>
                </div>

                <p className="mt-2 text-[11px] text-ink-faint">
                  See which agents are handling your workload.
                </p>
              </div>

              <Link
                to="/agents"
                className="text-[11px] font-medium text-accent-violet hover:underline"
              >
                Manage
              </Link>
            </div>

            {agentPerformance.length === 0 ? (
              <div className="rounded-xl border border-dashed border-base-border bg-base-panel-2/50 px-4 py-7 text-center">
                <Bot className="mx-auto h-6 w-6 text-ink-faint" />

                <p className="mt-2 text-xs font-medium text-ink">
                  No agent activity yet
                </p>

                <p className="mt-1 text-[11px] text-ink-faint">
                  Your agents will appear here as conversations
                  are processed.
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {agentPerformance.map((row) => (
                  <div
                    key={row.agent_id}
                    className="group flex min-w-0 items-center gap-3 rounded-xl border border-transparent p-2 transition hover:border-base-border hover:bg-base-panel-2"
                  >
                    <div className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-violet/10 text-accent-violet">
                      <Bot className="h-4 w-4" />

                      <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-base-panel bg-accent-green" />
                    </div>

                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-semibold text-ink">
                        {row.agent_name}
                      </p>

                      <div className="mt-1 flex items-center gap-2 text-[10px] text-ink-faint">
                        <span>
                          {row.conversationCount} conversations
                        </span>

                        <span className="h-1 w-1 rounded-full bg-ink-faint/40" />

                        <span className="capitalize">
                          {row.status}
                        </span>
                      </div>
                    </div>

                    <div className="shrink-0 text-right">
                      <p className="text-xs font-semibold tabular-nums text-ink">
                        {row.message_count}
                      </p>

                      <p className="text-[10px] text-ink-faint">
                        messages
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* ORDERS + QUICK ACTIONS                                              */}
        {/* ------------------------------------------------------------------ */}

        <div className="grid min-w-0 grid-cols-1 gap-4 xl:grid-cols-3">
          {/* Orders */}
          <div className="persona-card panel min-w-0 overflow-hidden p-4 sm:p-5 xl:col-span-2">
            <div className="mb-5 flex items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-green/10 text-accent-green">
                    <ShoppingBag className="h-4 w-4" />
                  </span>

                  <p className="text-sm font-semibold text-ink">
                    Recent Orders
                  </p>
                </div>

                <p className="mt-2 text-[11px] text-ink-faint">
                  Your latest customer orders and payment status.
                </p>
              </div>

              <Link
                to="/orders"
                className="flex shrink-0 items-center gap-1 text-[11px] font-medium text-accent-violet hover:underline"
              >
                View all
                <ChevronRight className="h-3.5 w-3.5" />
              </Link>
            </div>

            {recentOrders.length === 0 ? (
              <div className="rounded-xl border border-dashed border-base-border bg-base-panel-2/50 px-4 py-8 text-center">
                <ShoppingBag className="mx-auto h-6 w-6 text-ink-faint" />

                <p className="mt-2 text-xs font-medium text-ink">
                  No orders yet
                </p>

                <p className="mt-1 text-[11px] text-ink-faint">
                  Customer orders will appear here.
                </p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <div className="min-w-[540px]">
                  <div className="grid grid-cols-[1.3fr_1fr_1fr_100px] gap-3 border-b border-base-border px-2 pb-2 text-[9px] font-semibold uppercase tracking-wider text-ink-faint">
                    <span>Order</span>
                    <span>Date</span>
                    <span>Amount</span>
                    <span>Status</span>
                  </div>

                  <div className="divide-y divide-base-border/60">
                    {recentOrders.map((order) => (
                      <Link
                        key={order.id}
                        to="/orders"
                        className="grid grid-cols-[1.3fr_1fr_1fr_100px] items-center gap-3 px-2 py-3 text-xs transition hover:bg-base-panel-2"
                      >
                        <div className="min-w-0">
                          <p className="truncate font-semibold text-ink">
                            #
                            {order.id
                              .slice(0, 8)
                              .toUpperCase()}
                          </p>

                          <p className="mt-0.5 truncate text-[10px] text-ink-faint">
                            {order.payment_status ===
                            "paid"
                              ? "Payment received"
                              : "Payment pending"}
                          </p>
                        </div>

                        <span className="text-[10px] text-ink-muted">
                          {new Date(
                            order.created_at
                          ).toLocaleDateString()}
                        </span>

                        <span className="font-semibold tabular-nums text-ink">
                          {new Intl.NumberFormat(
                            undefined,
                            {
                              style: "currency",
                              currency:
                                order.currency || currency,
                              maximumFractionDigits: 0,
                            }
                          ).format(
                            Number(order.total_amount)
                          )}
                        </span>

                        <span
                          className={`w-fit rounded-full border px-2 py-1 text-[9px] font-medium capitalize ${
                            ORDER_STATUS_STYLES[
                              order.status
                            ] ??
                            "border-base-border bg-ink-faint/10 text-ink-faint"
                          }`}
                        >
                          {order.status}
                        </span>
                      </Link>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {recentOrders.length > 0 && (
              <div className="mt-4 grid grid-cols-2 gap-2 border-t border-base-border pt-4 sm:grid-cols-3">
                <MiniMetric
                  icon={ShoppingBag}
                  label="Orders"
                  value={orders.length.toLocaleString()}
                />

                <MiniMetric
                  icon={CircleCheck}
                  label="Paid"
                  value={paidOrders.toLocaleString()}
                />

                <MiniMetric
                  icon={CircleAlert}
                  label="Pending"
                  value={pendingOrders.toLocaleString()}
                  className="hidden sm:flex"
                />
              </div>
            )}
          </div>

          {/* Quick actions */}
          <div className="persona-card panel min-w-0 overflow-hidden p-4 sm:p-5">
            <div className="mb-5">
              <div className="flex items-center gap-2">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-orange/10 text-accent-orange">
                  <Zap className="h-4 w-4" />
                </span>

                <p className="text-sm font-semibold text-ink">
                  Quick Actions
                </p>
              </div>

              <p className="mt-2 text-[11px] text-ink-faint">
                Common tasks, one click away.
              </p>
            </div>

            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-1">
              <QuickAction
                to="/agents"
                icon={Bot}
                label="Create AI Agent"
              />

              <QuickAction
                to="/knowledge"
                icon={BookOpen}
                label="Upload Knowledge"
              />

              <QuickAction
                to="/products"
                icon={Package}
                label="Add Product"
              />

              <QuickAction
                to="/training"
                icon={Workflow}
                label="Create Workflow"
              />

              <QuickAction
                to="/integrations"
                icon={Send}
                label="Connect Channel"
              />
            </div>
          </div>
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* LIVE FEED                                                           */}
        {/* ------------------------------------------------------------------ */}

        <div className="persona-card panel min-w-0 overflow-hidden p-4 sm:p-5">
          <div className="mb-5 flex items-center justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <span className="relative flex h-8 w-8 items-center justify-center rounded-lg bg-accent-blue/10 text-accent-blue">
                  <Activity className="h-4 w-4" />

                  <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-accent-green shadow-sm shadow-accent-green/50" />
                </span>

                <p className="text-sm font-semibold text-ink">
                  Live Activity
                </p>
              </div>

              <p className="mt-2 text-[11px] text-ink-faint">
                Recent events from your PersonaAI workspace.
              </p>
            </div>

            <Link
              to="/notifications"
              className="flex shrink-0 items-center gap-1 text-[11px] font-medium text-accent-violet hover:underline"
            >
              View all
              <ChevronRight className="h-3.5 w-3.5" />
            </Link>
          </div>

          {recentFeed.length === 0 ? (
            <div className="flex min-h-28 items-center justify-center rounded-xl border border-dashed border-base-border bg-base-panel-2/40 px-4 text-center">
              <div>
                <Bell className="mx-auto h-5 w-5 text-ink-faint" />

                <p className="mt-2 text-xs font-medium text-ink">
                  Nothing new yet
                </p>

                <p className="mt-1 text-[11px] text-ink-faint">
                  Activity will appear here as your business
                  operates.
                </p>
              </div>
            </div>
          ) : (
            <div className="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {recentFeed.map((notification) => {
                const Icon =
                  FEED_ICONS[notification.type] ?? Bell;

                return (
                  <div
                    key={notification.id}
                    className="group flex min-w-0 items-start gap-3 rounded-xl border border-base-border/70 bg-base-panel-2/30 p-3 transition hover:border-accent-violet/20 hover:bg-base-panel-2"
                  >
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-base-panel text-ink-muted transition group-hover:text-accent-violet">
                      <Icon className="h-3.5 w-3.5" />
                    </span>

                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-semibold text-ink">
                        {notification.title}
                      </p>

                      {notification.body && (
                        <p className="mt-0.5 truncate text-[10px] leading-5 text-ink-muted">
                          {notification.body}
                        </p>
                      )}

                      <p className="mt-1 text-[9px] text-ink-faint">
                        {formatDistanceToNow(
                          new Date(
                            notification.created_at
                          ),
                          {
                            addSuffix: true,
                          }
                        )}
                      </p>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

/* ========================================================================== */
/* Stat Card                                                                  */
/* ========================================================================== */

function StatCard({
  icon: Icon,
  color,
  label,
  value,
  deltaPct,
  sublabel,
  neutralDelta = false,
}: {
  icon: ElementType;
  color: string;
  label: string;
  value: string;
  deltaPct: number;
  sublabel: string;
  neutralDelta?: boolean;
}) {
  const positive = deltaPct >= 0;

  return (
    <div className="persona-card panel group relative min-w-0 overflow-hidden p-4 sm:p-5">
      <div className="pointer-events-none absolute -right-8 -top-8 h-24 w-24 rounded-full bg-accent-violet/5 blur-2xl transition group-hover:bg-accent-violet/10" />

      <div className="relative">
        <div className="mb-4 flex items-center justify-between gap-3">
          <span
            className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${
              STAT_COLOR_STYLES[color] ??
              STAT_COLOR_STYLES["accent-violet"]
            }`}
          >
            <Icon className="h-5 w-5" />
          </span>

          {neutralDelta ? (
            <span className="rounded-full bg-base-panel-2 px-2 py-1 text-[9px] font-medium text-ink-faint">
              Current
            </span>
          ) : (
            <span
              className={`flex shrink-0 items-center gap-0.5 rounded-full px-2 py-1 text-[10px] font-semibold ${
                positive
                  ? "bg-accent-green/10 text-accent-green"
                  : "bg-accent-pink/10 text-accent-pink"
              }`}
            >
              {positive ? (
                <ArrowUpRight className="h-3 w-3" />
              ) : (
                <ArrowDownRight className="h-3 w-3" />
              )}

              {Math.abs(deltaPct)}%
            </span>
          )}
        </div>

        <p className="stat-value max-w-full truncate text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
          {value}
        </p>

        <p className="mt-1 truncate text-xs font-medium text-ink-muted">
          {label}
        </p>

        <p className="mt-2 truncate text-[10px] text-ink-faint">
          {sublabel}
        </p>
      </div>
    </div>
  );
}

/* ========================================================================== */
/* Needs Attention                                                           */
/* ========================================================================== */

function NeedsAttention({
  pendingOrders,
  integrationErrors,
  conversationsWaiting,
}: {
  pendingOrders: number;
  integrationErrors: number;
  conversationsWaiting: number;
}) {
  const hasItems =
    pendingOrders > 0 ||
    integrationErrors > 0 ||
    conversationsWaiting > 0;

  return (
    <div className="persona-card panel min-w-0 overflow-hidden p-4 sm:p-5">
      <div className="mb-5 flex items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-amber/10 text-accent-amber">
              <CircleAlert className="h-4 w-4" />
            </span>

            <p className="text-sm font-semibold text-ink">
              Needs Attention
            </p>
          </div>

          <p className="mt-2 text-[11px] text-ink-faint">
            Items that may need your action.
          </p>
        </div>

        {hasItems && (
          <span className="flex h-6 min-w-6 items-center justify-center rounded-full bg-accent-amber/10 px-2 text-[9px] font-semibold text-accent-amber">
            {pendingOrders +
              integrationErrors +
              conversationsWaiting}
          </span>
        )}
      </div>

      {!hasItems ? (
        <div className="flex min-h-40 flex-col items-center justify-center rounded-xl border border-accent-green/15 bg-accent-green/[0.03] px-4 text-center">
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-accent-green/10 text-accent-green">
            <CircleCheck className="h-5 w-5" />
          </span>

          <p className="mt-3 text-xs font-semibold text-ink">
            Everything looks good
          </p>

          <p className="mt-1 max-w-xs text-[10px] leading-5 text-ink-faint">
            No urgent actions have been detected in your
            workspace.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {conversationsWaiting > 0 && (
            <AttentionRow
              icon={MessageSquare}
              title={`${conversationsWaiting} conversation${
                conversationsWaiting === 1 ? "" : "s"
              } waiting`}
              description="Review your inbox"
              to="/conversations"
              color="blue"
            />
          )}

          {pendingOrders > 0 && (
            <AttentionRow
              icon={ShoppingBag}
              title={`${pendingOrders} order${
                pendingOrders === 1 ? "" : "s"
              } need payment`}
              description="Review pending orders"
              to="/orders"
              color="amber"
            />
          )}

          {integrationErrors > 0 && (
            <AttentionRow
              icon={CircleAlert}
              title={`${integrationErrors} integration issue${
                integrationErrors === 1 ? "" : "s"
              }`}
              description="Check your integrations"
              to="/integrations"
              color="pink"
            />
          )}
        </div>
      )}
    </div>
  );
}

/* ========================================================================== */
/* Attention Row                                                              */
/* ========================================================================== */

function AttentionRow({
  icon: Icon,
  title,
  description,
  to,
  color,
}: {
  icon: ElementType;
  title: string;
  description: string;
  to: string;
  color: "blue" | "amber" | "pink";
}) {
  const styles = {
    blue: {
      wrapper: "hover:border-accent-blue/20",
      icon: "bg-accent-blue/10 text-accent-blue",
    },
    amber: {
      wrapper: "hover:border-accent-amber/20",
      icon: "bg-accent-amber/10 text-accent-amber",
    },
    pink: {
      wrapper: "hover:border-accent-pink/20",
      icon: "bg-accent-pink/10 text-accent-pink",
    },
  };

  return (
    <Link
      to={to}
      className={`group flex min-w-0 items-center gap-3 rounded-xl border border-base-border p-3 transition hover:bg-base-panel-2 ${styles[color].wrapper}`}
    >
      <span
        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${styles[color].icon}`}
      >
        <Icon className="h-4 w-4" />
      </span>

      <div className="min-w-0 flex-1">
        <p className="truncate text-xs font-semibold text-ink">
          {title}
        </p>

        <p className="mt-0.5 truncate text-[10px] text-ink-faint">
          {description}
        </p>
      </div>

      <ArrowRight className="h-3.5 w-3.5 shrink-0 text-ink-faint transition group-hover:translate-x-0.5 group-hover:text-ink" />
    </Link>
  );
}

/* ========================================================================== */
/* Channel Row                                                                */
/* ========================================================================== */

function ChannelRow({
  platform,
  count,
  pct,
}: {
  platform: string;
  count: number;
  pct: number;
}) {
  const color = CHANNEL_COLORS[platform] ?? "#6B6E89";

  const label = platform
    .replace("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

  return (
    <div className="group flex min-w-0 items-center gap-3 rounded-xl border border-transparent p-2 transition hover:border-base-border hover:bg-base-panel-2">
      <span
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg"
        style={{
          backgroundColor: `${color}15`,
          color,
        }}
      >
        <span
          className="h-2.5 w-2.5 rounded-full"
          style={{
            backgroundColor: color,
            boxShadow: `0 0 10px ${color}55`,
          }}
        />
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-3">
          <p className="truncate text-xs font-medium text-ink">
            {label}
          </p>

          <span className="shrink-0 text-[10px] font-semibold tabular-nums text-ink">
            {pct}%
          </span>
        </div>

        <div className="mt-2 h-1 overflow-hidden rounded-full bg-base-panel-2">
          <div
            className="h-full rounded-full transition-all duration-700"
            style={{
              width: `${Math.max(2, pct)}%`,
              backgroundColor: color,
            }}
          />
        </div>
      </div>

      <span className="hidden shrink-0 text-[10px] tabular-nums text-ink-faint sm:block">
        {count}
      </span>
    </div>
  );
}

/* ========================================================================== */
/* Quick Action                                                               */
/* ========================================================================== */

function QuickAction({
  to,
  icon: Icon,
  label,
}: {
  to: string;
  icon: ElementType;
  label: string;
}) {
  return (
    <Link
      to={to}
      className="group flex min-w-0 items-center gap-3 rounded-xl border border-base-border bg-base-panel-2/30 px-3 py-3 text-xs font-medium text-ink-muted transition duration-200 hover:-translate-y-0.5 hover:border-accent-violet/30 hover:bg-accent-violet/5 hover:text-accent-violet"
    >
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-base-panel text-ink-faint transition group-hover:text-accent-violet">
        <Icon className="h-3.5 w-3.5" />
      </span>

      <span className="min-w-0 flex-1 truncate">
        {label}
      </span>

      <ArrowRight className="h-3.5 w-3.5 shrink-0 text-ink-faint transition group-hover:translate-x-0.5 group-hover:text-accent-violet" />
    </Link>
  );
}

/* ========================================================================== */
/* Mini Metric                                                                */
/* ========================================================================== */

function MiniMetric({
  icon: Icon,
  label,
  value,
  className = "",
}: {
  icon: ElementType;
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <div
      className={`flex min-w-0 items-center gap-2 rounded-lg bg-base-panel-2/60 px-3 py-2.5 ${className}`}
    >
      <Icon className="h-3.5 w-3.5 shrink-0 text-ink-faint" />

      <div className="min-w-0">
        <p className="truncate text-[9px] text-ink-faint">
          {label}
        </p>

        <p className="truncate text-xs font-semibold text-ink">
          {value}
        </p>
      </div>
    </div>
  );
}
