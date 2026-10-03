import { useMemo, useState, type ElementType } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  MessageSquare,
  ShoppingBag,
  DollarSign,
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
/* Config                                                                     */
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
  preparing: "bg-accent-violet/10 text-accent-violet border-accent-violet/20",
  ready: "bg-accent-cyan/10 text-accent-cyan border-accent-cyan/20",
  delivered: "bg-accent-green/10 text-accent-green border-accent-green/20",
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
/* Page                                                                       */
/* -------------------------------------------------------------------------- */

export default function DashboardPage() {
  const user = useAuthStore((s) => s.user);
  const [rangeDays, setRangeDays] = useState(30);

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

  const analytics = analyticsQuery.data;
  const agents = agentsQuery.data ?? [];
  const conversations = conversationsQuery.data ?? [];
  const orders = ordersQuery.data ?? [];
  const customers = customersQuery.data ?? [];
  const notifications = notificationsQuery.data ?? [];

  const firstName =
    user?.full_name?.trim()?.split(/\s+/)[0] || "there";

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
      if (time >= cutoffs.current) current += 1;
      else if (time >= cutoffs.previous) previous += 1;
    }
    const pct =
      previous === 0
        ? current > 0
          ? 100
          : 0
        : Math.round(((current - previous) / previous) * 100);
    return { current, previous, pct };
  }

  const conversationsWindow = windowDelta(conversations);
  const customersWindow = windowDelta(customers);

  const paidRevenue = orders
    .filter(
      (o) =>
        o.payment_status === "paid" &&
        new Date(o.created_at).getTime() >= cutoffs.current
    )
    .reduce((sum, o) => sum + Number(o.total_amount), 0);

  const previousPaidRevenue = orders
    .filter(
      (o) =>
        o.payment_status === "paid" &&
        new Date(o.created_at).getTime() >= cutoffs.previous &&
        new Date(o.created_at).getTime() < cutoffs.current
    )
    .reduce((sum, o) => sum + Number(o.total_amount), 0);

  const revenuePct =
    previousPaidRevenue === 0
      ? paidRevenue > 0
        ? 100
        : 0
      : Math.round(
          ((paidRevenue - previousPaidRevenue) / previousPaidRevenue) * 100
        );

  const currency = orders[0]?.currency ?? "NGN";
  const currencyFmt = new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  });

  const channelBreakdown = useMemo(() => {
    const counts = conversations.reduce<Record<string, number>>(
      (acc, c) => {
        const platform = c.platform || "unknown";
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

  const agentPerformance = useMemo(() => {
    const convByAgent = conversations.reduce<Record<string, number>>(
      (acc, c) => {
        if (c.agent_id) {
          acc[c.agent_id] = (acc[c.agent_id] ?? 0) + 1;
        }
        return acc;
      },
      {}
    );
    const byMessages = analytics?.messages_by_agent ?? [];
    return byMessages
      .map((row) => ({
        ...row,
        conversationCount: convByAgent[row.agent_id] ?? 0,
        status:
          agents.find((a) => a.id === row.agent_id)?.status ?? "active",
      }))
      .sort((a, b) => b.message_count - a.message_count)
      .slice(0, 4);
  }, [analytics, conversations, agents]);

  const recentOrders = [...orders]
    .sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    )
    .slice(0, 5);

  const recentFeed = [...notifications]
    .sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    )
    .slice(0, 6);

  const paidOrders = orders.filter((o) => o.payment_status === "paid").length;
  const pendingOrders = orders.filter(
    (o) =>
      o.payment_status !== "paid" &&
      o.status !== "cancelled" &&
      o.status !== "refunded"
  ).length;
  const activeAgents = agents.filter((a) => a.status === "active").length;
  const integrationErrors = notifications.filter(
    (n) => n.type === "integration_error"
  ).length;

  const aiResolutionRate =
    conversations.length > 0
      ? Math.min(
          99,
          Math.max(
            0,
            Math.round(
              ((conversations.length - integrationErrors) /
                conversations.length) *
                100
            )
          )
        )
      : 0;

  return (
    <>
      <style>{`
        @keyframes core-float {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-5px); }
        }
        @keyframes core-orbit {
          from { transform: rotateX(70deg) rotateZ(0deg); }
          to { transform: rotateX(70deg) rotateZ(360deg); }
        }
        @keyframes core-orbit-rev {
          from { transform: rotateX(70deg) rotateZ(360deg); }
          to { transform: rotateX(70deg) rotateZ(0deg); }
        }
        .core-float { animation: core-float 9s ease-in-out infinite; }
        .core-orbit { animation: core-orbit 24s linear infinite; transform-style: preserve-3d; }
        .core-orbit-rev { animation: core-orbit-rev 18s linear infinite; transform-style: preserve-3d; }

        @media (prefers-reduced-motion: reduce) {
          .core-float, .core-orbit, .core-orbit-rev { animation: none !important; }
        }
      `}</style>

      <div className="mx-auto w-full max-w-[1400px] space-y-6 px-0 pb-10">
        {/* ================================================================ */}
        {/* HERO                                                             */}
        {/* ================================================================ */}
        <section className="relative overflow-hidden rounded-2xl border border-base-border bg-base-panel">
          <div className="pointer-events-none absolute inset-0">
            <div className="absolute -right-16 -top-24 h-56 w-56 rounded-full bg-accent-violet/8 blur-3xl" />
            <div className="absolute -bottom-24 left-1/3 h-48 w-48 rounded-full bg-accent-blue/6 blur-3xl" />
          </div>

          <div className="relative flex flex-col gap-8 p-6 sm:p-7 lg:flex-row lg:items-center lg:justify-between lg:p-8">
            <div className="min-w-0 max-w-lg">
              <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wider text-ink-faint">
                Command Center
              </p>
              <h1 className="text-2xl font-semibold tracking-tight text-ink sm:text-[28px]">
                Welcome back,{" "}
                <span className="text-accent-violet">{firstName}</span>
              </h1>
              <p className="mt-2 text-sm leading-relaxed text-ink-muted">
                Monitor conversations, agents, customers and revenue from one
                place.
              </p>

              <div className="mt-6 flex flex-wrap gap-2.5">
                <Link
                  to="/conversations"
                  className="inline-flex h-9 items-center gap-2 rounded-lg bg-accent-violet px-4 text-sm font-medium text-white transition hover:bg-accent-violet/90"
                >
                  <MessageSquare className="h-4 w-4" />
                  Open Inbox
                </Link>
                <Link
                  to="/analytics"
                  className="inline-flex h-9 items-center gap-2 rounded-lg border border-base-border bg-base-panel-2 px-4 text-sm font-medium text-ink transition hover:border-accent-violet/40 hover:bg-accent-violet/5"
                >
                  <BarChart3 className="h-4 w-4" />
                  Analytics
                </Link>
              </div>
            </div>

            {/* 3D Core */}
            <div className="relative mx-auto h-40 w-full max-w-[200px] shrink-0 sm:h-44 lg:mx-0 lg:h-48 lg:w-56">
              <div className="absolute inset-0 [perspective:900px]">
                <div className="core-float relative mx-auto h-full w-full">
                  <div className="absolute left-1/2 top-1/2 h-32 w-32 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent-violet/12 blur-2xl" />
                  <div className="core-orbit absolute left-1/2 top-1/2 h-36 w-36 -translate-x-1/2 -translate-y-1/2 rounded-full border border-accent-violet/15" />
                  <div className="core-orbit-rev absolute left-1/2 top-1/2 h-24 w-24 -translate-x-1/2 -translate-y-1/2 rounded-full border border-accent-blue/20" />

                  <div className="absolute left-1/2 top-1/2 h-20 w-20 -translate-x-1/2 -translate-y-1/2 [transform-style:preserve-3d] sm:h-24 sm:w-24">
                    <div className="absolute inset-0 rounded-2xl border border-accent-violet/25 bg-gradient-to-br from-accent-violet/12 via-base-panel-2 to-accent-blue/8 shadow-lg shadow-accent-violet/10 [transform:translateZ(6px)]" />
                    <div className="absolute inset-2.5 rounded-full border border-accent-violet/20 bg-base-panel/80 backdrop-blur-sm [transform:translateZ(16px)]" />
                    <div className="absolute left-1/2 top-1/2 flex h-11 w-11 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-xl border border-accent-violet/30 bg-accent-violet/10 text-accent-violet [transform:translateZ(28px)] sm:h-12 sm:w-12">
                      <BrainCircuit className="h-5 w-5 sm:h-6 sm:w-6" />
                    </div>
                  </div>

                  <div className="absolute -bottom-0.5 left-1/2 hidden -translate-x-1/2 items-center gap-1.5 rounded-full border border-base-border bg-base-panel/95 px-2.5 py-1 shadow-sm sm:flex">
                    <span className="h-1.5 w-1.5 rounded-full bg-accent-green" />
                    <span className="text-[10px] font-medium text-ink-muted">
                      {activeAgents} agents live
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ================================================================ */}
        {/* CONTROLS                                                         */}
        {/* ================================================================ */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-violet/10 text-accent-violet">
              <BarChart3 className="h-4 w-4" />
            </div>
            <div>
              <p className="text-sm font-semibold text-ink">Business Overview</p>
              <p className="text-xs text-ink-faint">
                Performance across your workspace
              </p>
            </div>
          </div>

          <select
            value={rangeDays}
            onChange={(e) => setRangeDays(Number(e.target.value))}
            className="h-9 w-full rounded-lg border border-base-border bg-base-panel px-3 text-sm font-medium text-ink outline-none transition focus:border-accent-violet/50 focus:ring-2 focus:ring-accent-violet/10 sm:w-auto"
          >
            {RANGE_OPTIONS.map((opt) => (
              <option key={opt.days} value={opt.days}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        {/* ================================================================ */}
        {/* KPI CARDS                                                        */}
        {/* ================================================================ */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
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
            sublabel="Paid revenue this period"
          />
          <StatCard
            icon={BrainCircuit}
            color="accent-orange"
            label="AI Resolution"
            value={`${aiResolutionRate}%`}
            deltaPct={0}
            sublabel={`${activeAgents} active agents`}
            neutralDelta
          />
        </div>

        {/* ================================================================ */}
        {/* CHART + ATTENTION                                                */}
        {/* ================================================================ */}
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
          <div className="overflow-hidden rounded-2xl border border-base-border bg-base-panel p-5 xl:col-span-2">
            <div className="mb-5 flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2.5">
                  <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-violet/10 text-accent-violet">
                    <MessageSquare className="h-4 w-4" />
                  </span>
                  <p className="text-sm font-semibold text-ink">
                    Messages Overview
                  </p>
                </div>
                <p className="mt-1 text-xs text-ink-faint">
                  Daily volume across all channels
                </p>
              </div>
              <Link
                to="/analytics"
                className="hidden items-center gap-1 text-xs font-medium text-accent-violet hover:underline sm:flex"
              >
                Details
                <ChevronRight className="h-3.5 w-3.5" />
              </Link>
            </div>

            <div className="h-52 sm:h-60">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart
                  data={analytics?.messages_per_day ?? []}
                  margin={{ top: 6, right: 4, left: -18, bottom: 0 }}
                >
                  <defs>
                    <linearGradient id="msgFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#8B5CF6" stopOpacity={0.22} />
                      <stop offset="100%" stopColor="#8B5CF6" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid
                    stroke="#232544"
                    vertical={false}
                    strokeDasharray="3 4"
                  />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 10, fill: "#6B6E89" }}
                    axisLine={false}
                    tickLine={false}
                    tickFormatter={(d: string) => d.slice(5)}
                    minTickGap={28}
                  />
                  <YAxis
                    tick={{ fontSize: 10, fill: "#6B6E89" }}
                    axisLine={false}
                    tickLine={false}
                    allowDecimals={false}
                    width={30}
                  />
                  <Tooltip
                    cursor={{ stroke: "#8B5CF6", strokeOpacity: 0.12 }}
                    contentStyle={{
                      borderRadius: 10,
                      border: "1px solid #232544",
                      fontSize: 12,
                      background: "#12132B",
                      color: "#F4F4F8",
                    }}
                  />
                  <Area
                    type="monotone"
                    dataKey="count"
                    name="Messages"
                    stroke="#8B5CF6"
                    strokeWidth={2}
                    fill="url(#msgFill)"
                    activeDot={{ r: 3.5, strokeWidth: 0 }}
                  />
                </AreaChart>
              </ResponsiveContainer>

              {(analytics?.messages_per_day?.length ?? 0) === 0 &&
                !analyticsQuery.isLoading && (
                  <div className="pointer-events-none -mt-24 text-center text-xs text-ink-faint">
                    No messages in this period
                  </div>
                )}
            </div>
          </div>

          <NeedsAttention
            pendingOrders={pendingOrders}
            integrationErrors={integrationErrors}
            conversationsWaiting={0}
          />
        </div>

        {/* ================================================================ */}
        {/* CHANNELS + AGENTS                                                */}
        {/* ================================================================ */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {/* Channels */}
          <div className="overflow-hidden rounded-2xl border border-base-border bg-base-panel p-5">
            <SectionHeader
              icon={Wifi}
              iconColor="bg-accent-blue/10 text-accent-blue"
              title="Channel Health"
              subtitle="Where customers reach you"
              action={{ label: "Manage", to: "/integrations" }}
            />

            {channelBreakdown.length === 0 ? (
              <EmptyState
                icon={Wifi}
                title="No channels active"
                description="Connect WhatsApp, Telegram or others to start receiving conversations."
                action={{ label: "Connect a channel", to: "/integrations" }}
              />
            ) : (
              <div className="mt-1 space-y-0.5">
                {channelBreakdown.slice(0, 5).map((ch) => (
                  <ChannelRow
                    key={ch.platform}
                    platform={ch.platform}
                    count={ch.count}
                    pct={ch.pct}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Agents */}
          <div className="overflow-hidden rounded-2xl border border-base-border bg-base-panel p-5">
            <SectionHeader
              icon={Bot}
              iconColor="bg-accent-violet/10 text-accent-violet"
              title="AI Agents"
              subtitle="Workload by agent"
              action={{ label: "Manage", to: "/agents" }}
            />

            {agentPerformance.length === 0 ? (
              <EmptyState
                icon={Bot}
                title="No agent activity"
                description="Agents will appear here once they start handling conversations."
              />
            ) : (
              <div className="mt-1 space-y-0.5">
                {agentPerformance.map((row) => (
                  <div
                    key={row.agent_id}
                    className="flex items-center gap-3 rounded-lg px-2 py-2.5 transition hover:bg-base-panel-2"
                  >
                    <div className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-violet/10 text-accent-violet">
                      <Bot className="h-4 w-4" />
                      <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full border-2 border-base-panel bg-accent-green" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-ink">
                        {row.agent_name}
                      </p>
                      <p className="mt-0.5 text-[11px] text-ink-faint">
                        {row.conversationCount} conversations ·{" "}
                        <span className="capitalize">{row.status}</span>
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-sm font-semibold tabular-nums text-ink">
                        {row.message_count}
                      </p>
                      <p className="text-[10px] text-ink-faint">messages</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ================================================================ */}
        {/* ORDERS + QUICK ACTIONS                                           */}
        {/* ================================================================ */}
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
          <div className="overflow-hidden rounded-2xl border border-base-border bg-base-panel p-5 xl:col-span-2">
            <SectionHeader
              icon={ShoppingBag}
              iconColor="bg-accent-green/10 text-accent-green"
              title="Recent Orders"
              subtitle="Latest customer orders & payment status"
              action={{ label: "View all", to: "/orders" }}
            />

            {recentOrders.length === 0 ? (
              <EmptyState
                icon={ShoppingBag}
                title="No orders yet"
                description="Customer orders will appear here once they start coming in."
              />
            ) : (
              <>
                <div className="mt-1 overflow-x-auto">
                  <div className="min-w-[520px]">
                    <div className="grid grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1fr)_90px] gap-3 border-b border-base-border px-2 pb-2 text-[10px] font-semibold uppercase tracking-wider text-ink-faint">
                      <span>Order</span>
                      <span>Date</span>
                      <span>Amount</span>
                      <span>Status</span>
                    </div>
                    <div className="divide-y divide-base-border/50">
                      {recentOrders.map((order) => (
                        <Link
                          key={order.id}
                          to="/orders"
                          className="grid grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1fr)_90px] items-center gap-3 px-2 py-3 text-sm transition hover:bg-base-panel-2"
                        >
                          <div className="min-w-0">
                            <p className="truncate font-medium text-ink">
                              #{order.id.slice(0, 8).toUpperCase()}
                            </p>
                            <p className="mt-0.5 text-[11px] text-ink-faint">
                              {order.payment_status === "paid"
                                ? "Payment received"
                                : "Payment pending"}
                            </p>
                          </div>
                          <span className="text-xs text-ink-muted">
                            {new Date(order.created_at).toLocaleDateString()}
                          </span>
                          <span className="font-medium tabular-nums text-ink">
                            {new Intl.NumberFormat(undefined, {
                              style: "currency",
                              currency: order.currency || currency,
                              maximumFractionDigits: 0,
                            }).format(Number(order.total_amount))}
                          </span>
                          <span
                            className={`w-fit rounded-full border px-2 py-0.5 text-[10px] font-medium capitalize ${
                              ORDER_STATUS_STYLES[order.status] ??
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

                <div className="mt-4 grid grid-cols-2 gap-2 border-t border-base-border pt-4 sm:grid-cols-3">
                  <MiniMetric
                    icon={ShoppingBag}
                    label="Total Orders"
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
              </>
            )}
          </div>

          <div className="overflow-hidden rounded-2xl border border-base-border bg-base-panel p-5">
            <SectionHeader
              icon={Zap}
              iconColor="bg-accent-orange/10 text-accent-orange"
              title="Quick Actions"
              subtitle="Common tasks"
            />

            <div className="mt-1 space-y-1.5">
              <QuickAction to="/agents" icon={Bot} label="Create AI Agent" />
              <QuickAction
                to="/knowledge"
                icon={BookOpen}
                label="Upload Knowledge"
              />
              <QuickAction to="/products" icon={Package} label="Add Product" />
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

        {/* ================================================================ */}
        {/* LIVE ACTIVITY                                                    */}
        {/* ================================================================ */}
        <div className="overflow-hidden rounded-2xl border border-base-border bg-base-panel p-5">
          <SectionHeader
            icon={Activity}
            iconColor="bg-accent-blue/10 text-accent-blue"
            title="Live Activity"
            subtitle="Recent events from your workspace"
            action={{ label: "View all", to: "/notifications" }}
            live
          />

          {recentFeed.length === 0 ? (
            <EmptyState
              icon={Bell}
              title="Nothing new yet"
              description="Activity will appear here as your business operates."
            />
          ) : (
            <div className="mt-1 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {recentFeed.map((n) => {
                const Icon = FEED_ICONS[n.type] ?? Bell;
                return (
                  <div
                    key={n.id}
                    className="flex items-start gap-3 rounded-xl border border-base-border/60 bg-base-panel-2/30 p-3 transition hover:border-accent-violet/20 hover:bg-base-panel-2"
                  >
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-base-panel text-ink-muted">
                      <Icon className="h-3.5 w-3.5" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-ink">
                        {n.title}
                      </p>
                      {n.body && (
                        <p className="mt-0.5 truncate text-xs text-ink-muted">
                          {n.body}
                        </p>
                      )}
                      <p className="mt-1 text-[10px] text-ink-faint">
                        {formatDistanceToNow(new Date(n.created_at), {
                          addSuffix: true,
                        })}
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
/* Shared UI                                                                  */
/* ========================================================================== */

function SectionHeader({
  icon: Icon,
  iconColor,
  title,
  subtitle,
  action,
  live = false,
}: {
  icon: ElementType;
  iconColor: string;
  title: string;
  subtitle: string;
  action?: { label: string; to: string };
  live?: boolean;
}) {
  return (
    <div className="mb-4 flex items-start justify-between gap-3">
      <div>
        <div className="flex items-center gap-2.5">
          <span
            className={`relative flex h-8 w-8 items-center justify-center rounded-lg ${iconColor}`}
          >
            <Icon className="h-4 w-4" />
            {live && (
              <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-accent-green" />
            )}
          </span>
          <p className="text-sm font-semibold text-ink">{title}</p>
        </div>
        <p className="mt-1 text-xs text-ink-faint">{subtitle}</p>
      </div>
      {action && (
        <Link
          to={action.to}
          className="flex shrink-0 items-center gap-1 text-xs font-medium text-accent-violet hover:underline"
        >
          {action.label}
          <ChevronRight className="h-3.5 w-3.5" />
        </Link>
      )}
    </div>
  );
}

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
    <div className="rounded-2xl border border-base-border bg-base-panel p-5">
      <div className="flex items-start justify-between gap-3">
        <span
          className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${
            STAT_COLOR_STYLES[color] ?? STAT_COLOR_STYLES["accent-violet"]
          }`}
        >
          <Icon className="h-4.5 w-4.5" />
        </span>
        {neutralDelta ? (
          <span className="rounded-full bg-base-panel-2 px-2 py-0.5 text-[10px] font-medium text-ink-faint">
            Current
          </span>
        ) : (
          <span
            className={`flex items-center gap-0.5 rounded-full px-2 py-0.5 text-[11px] font-semibold ${
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
      <p className="mt-4 text-2xl font-semibold tracking-tight text-ink">
        {value}
      </p>
      <p className="mt-1 text-sm font-medium text-ink-muted">{label}</p>
      <p className="mt-1 text-xs text-ink-faint">{sublabel}</p>
    </div>
  );
}

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
    pendingOrders > 0 || integrationErrors > 0 || conversationsWaiting > 0;
  const total = pendingOrders + integrationErrors + conversationsWaiting;

  return (
    <div className="overflow-hidden rounded-2xl border border-base-border bg-base-panel p-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-amber/10 text-accent-amber">
              <CircleAlert className="h-4 w-4" />
            </span>
            <p className="text-sm font-semibold text-ink">Needs Attention</p>
          </div>
          <p className="mt-1 text-xs text-ink-faint">
            Items that may require action
          </p>
        </div>
        {hasItems && (
          <span className="flex h-6 min-w-6 items-center justify-center rounded-full bg-accent-amber/10 px-2 text-[11px] font-semibold text-accent-amber">
            {total}
          </span>
        )}
      </div>

      {!hasItems ? (
        <div className="flex min-h-[168px] flex-col items-center justify-center rounded-xl border border-accent-green/20 bg-accent-green/[0.03] px-4 text-center">
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-accent-green/10 text-accent-green">
            <CircleCheck className="h-4.5 w-4.5" />
          </span>
          <p className="mt-2.5 text-sm font-medium text-ink">All clear</p>
          <p className="mt-1 max-w-[180px] text-xs leading-relaxed text-ink-faint">
            No urgent actions detected.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {conversationsWaiting > 0 && (
            <AttentionRow
              icon={MessageSquare}
              title={`${conversationsWaiting} conversation${conversationsWaiting === 1 ? "" : "s"} waiting`}
              description="Review your inbox"
              to="/conversations"
              color="blue"
            />
          )}
          {pendingOrders > 0 && (
            <AttentionRow
              icon={ShoppingBag}
              title={`${pendingOrders} order${pendingOrders === 1 ? "" : "s"} need payment`}
              description="Review pending orders"
              to="/orders"
              color="amber"
            />
          )}
          {integrationErrors > 0 && (
            <AttentionRow
              icon={CircleAlert}
              title={`${integrationErrors} integration issue${integrationErrors === 1 ? "" : "s"}`}
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
      wrapper: "hover:border-accent-blue/25",
      icon: "bg-accent-blue/10 text-accent-blue",
    },
    amber: {
      wrapper: "hover:border-accent-amber/25",
      icon: "bg-accent-amber/10 text-accent-amber",
    },
    pink: {
      wrapper: "hover:border-accent-pink/25",
      icon: "bg-accent-pink/10 text-accent-pink",
    },
  };

  return (
    <Link
      to={to}
      className={`group flex items-center gap-3 rounded-xl border border-base-border p-3 transition hover:bg-base-panel-2 ${styles[color].wrapper}`}
    >
      <span
        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${styles[color].icon}`}
      >
        <Icon className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-ink">{title}</p>
        <p className="mt-0.5 truncate text-xs text-ink-faint">{description}</p>
      </div>
      <ArrowRight className="h-3.5 w-3.5 shrink-0 text-ink-faint transition group-hover:translate-x-0.5 group-hover:text-ink" />
    </Link>
  );
}

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
    .replace(/\b\w/g, (l) => l.toUpperCase());

  return (
    <div className="flex items-center gap-3 rounded-lg px-2 py-2.5 transition hover:bg-base-panel-2">
      <span
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
        style={{ backgroundColor: `${color}18`, color }}
      >
        <span
          className="h-2 w-2 rounded-full"
          style={{
            backgroundColor: color,
            boxShadow: `0 0 6px ${color}50`,
          }}
        />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <p className="truncate text-sm font-medium text-ink">{label}</p>
          <span className="text-xs font-semibold tabular-nums text-ink">
            {pct}%
          </span>
        </div>
        <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-base-panel-2">
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{
              width: `${Math.max(3, pct)}%`,
              backgroundColor: color,
            }}
          />
        </div>
      </div>
      <span className="hidden w-8 text-right text-xs tabular-nums text-ink-faint sm:block">
        {count}
      </span>
    </div>
  );
}

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
      className="group flex items-center gap-3 rounded-xl border border-base-border bg-base-panel-2/40 px-3 py-2.5 text-sm font-medium text-ink-muted transition hover:border-accent-violet/30 hover:bg-accent-violet/5 hover:text-accent-violet"
    >
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-base-panel text-ink-faint transition group-hover:text-accent-violet">
        <Icon className="h-3.5 w-3.5" />
      </span>
      <span className="min-w-0 flex-1 truncate">{label}</span>
      <ArrowRight className="h-3.5 w-3.5 shrink-0 text-ink-faint transition group-hover:translate-x-0.5 group-hover:text-accent-violet" />
    </Link>
  );
}

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
      className={`flex items-center gap-2.5 rounded-lg bg-base-panel-2/50 px-3 py-2.5 ${className}`}
    >
      <Icon className="h-3.5 w-3.5 shrink-0 text-ink-faint" />
      <div className="min-w-0">
        <p className="text-[10px] text-ink-faint">{label}</p>
        <p className="text-sm font-semibold text-ink">{value}</p>
      </div>
    </div>
  );
}

function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: ElementType;
  title: string;
  description: string;
  action?: { label: string; to: string };
}) {
  return (
    <div className="flex min-h-[132px] flex-col items-center justify-center rounded-xl border border-dashed border-base-border bg-base-panel-2/25 px-4 py-6 text-center">
      <Icon className="h-5 w-5 text-ink-faint" />
      <p className="mt-2.5 text-sm font-medium text-ink">{title}</p>
      <p className="mt-1 max-w-[220px] text-xs leading-relaxed text-ink-faint">
        {description}
      </p>
      {action && (
        <Link
          to={action.to}
          className="mt-3 inline-flex items-center gap-1.5 text-xs font-semibold text-accent-violet hover:underline"
        >
          {action.label}
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      )}
    </div>
  );
}
