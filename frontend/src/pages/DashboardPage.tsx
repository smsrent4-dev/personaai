import { useMemo, useState } from "react";
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
  pending: "bg-accent-amber/15 text-accent-amber",
  confirmed: "bg-accent-blue/15 text-accent-blue",
  preparing: "bg-accent-violet/15 text-accent-violet",
  ready: "bg-accent-cyan/15 text-accent-cyan",
  delivered: "bg-accent-green/15 text-accent-green",
  cancelled: "bg-ink-faint/15 text-ink-faint",
  refunded: "bg-accent-pink/15 text-accent-pink",
};

const FEED_ICONS: Record<NotificationType, React.ElementType> = {
  new_conversation: FeedConversation,
  knowledge_ingestion_failed: FeedAlert,
  integration_error: FeedAlert,
  new_order: FeedOrder,
  receipt_uploaded: FeedReceipt,
  payment_confirmed: FeedPaid,
};

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
      const t = new Date(item.created_at).getTime();

      if (t >= cutoffs.current) {
        current += 1;
      } else if (t >= cutoffs.previous) {
        previous += 1;
      }
    }

    const pct =
      previous === 0
        ? current > 0
          ? 100
          : 0
        : Math.round(((current - previous) / previous) * 100);

    return { current, pct };
  }

  const conversationsWindow = windowDelta(conversations);
  const ordersWindow = windowDelta(orders);
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

  const currency = orders[0]?.currency ?? "USD";

  const currencyFmt = new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  });

  const channelBreakdown = useMemo(() => {
    const counts = conversations.reduce<Record<string, number>>(
      (acc, conversation) => {
        acc[conversation.platform] =
          (acc[conversation.platform] ?? 0) + 1;

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
        conversationCount: convByAgent[row.agent_id] ?? 0,
        status:
          agents.find((agent) => agent.id === row.agent_id)?.status ??
          "active",
      }))
      .sort((a, b) => b.message_count - a.message_count)
      .slice(0, 4);
  }, [analytics, conversations, agents]);

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
    .slice(0, 5);

  return (
    <div className="w-full min-w-0 space-y-5 sm:space-y-6">
      <div className="flex min-w-0 flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h1 className="font-display text-xl font-semibold text-ink sm:text-2xl">
            Overview
          </h1>

          <p className="mt-1 max-w-2xl text-xs leading-5 text-ink-muted sm:text-sm">
            Welcome back, {user?.full_name.split(" ")[0]}! Here's what's
            happening with your business.
          </p>
        </div>

        <select
          value={rangeDays}
          onChange={(event) =>
            setRangeDays(Number(event.target.value))
          }
          className="w-full shrink-0 rounded-xl border border-base-border bg-base-panel px-3 py-2.5 text-sm text-ink focus:outline-none sm:w-auto"
        >
          {RANGE_OPTIONS.map((option) => (
            <option key={option.days} value={option.days}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      <div className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4 xl:grid-cols-4">
        <StatCard
          icon={MessageSquare}
          color="accent-violet"
          label="Total Conversations"
          value={conversations.length.toLocaleString()}
          deltaPct={conversationsWindow.pct}
          sublabel={`${conversationsWindow.current} in this window`}
        />

        <StatCard
          icon={ShoppingBag}
          color="accent-green"
          label="Orders Created"
          value={orders.length.toLocaleString()}
          deltaPct={ordersWindow.pct}
          sublabel={`${ordersWindow.current} in this window`}
        />

        <StatCard
          icon={DollarSign}
          color="accent-blue"
          label="Revenue Generated"
          value={currencyFmt.format(paidRevenue)}
          deltaPct={revenuePct}
          sublabel="paid orders, this window"
        />

        <StatCard
          icon={UserPlus}
          color="accent-orange"
          label="New Customers"
          value={customersWindow.current.toLocaleString()}
          deltaPct={customersWindow.pct}
          sublabel={`of ${customers.length} total`}
        />
      </div>

      <div className="grid min-w-0 grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="panel min-w-0 overflow-hidden p-4 sm:p-5 xl:col-span-2">
          <div className="mb-4 min-w-0">
            <p className="text-sm font-semibold text-ink">
              Messages Overview
            </p>

            <p className="mt-1 text-xs leading-5 text-ink-faint">
              Daily message volume across every conversation
            </p>
          </div>

          <div className="h-56 min-w-0 sm:h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart
                data={analytics?.messages_per_day ?? []}
                margin={{
                  top: 5,
                  right: 5,
                  left: -20,
                  bottom: 0,
                }}
              >
                <defs>
                  <linearGradient
                    id="messagesFill"
                    x1="0"
                    y1="0"
                    x2="0"
                    y2="1"
                  >
                    <stop
                      offset="0%"
                      stopColor="#8B5CF6"
                      stopOpacity={0.25}
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
                  minTickGap={18}
                />

                <YAxis
                  tick={{
                    fontSize: 10,
                    fill: "#6B6E89",
                  }}
                  axisLine={false}
                  tickLine={false}
                  allowDecimals={false}
                  width={35}
                />

                <Tooltip
                  contentStyle={{
                    borderRadius: 12,
                    border: "1px solid #232544",
                    fontSize: 12,
                    background: "#12132B",
                    color: "#F4F4F8",
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
                  strokeWidth={2}
                  fill="url(#messagesFill)"
                />
              </AreaChart>
            </ResponsiveContainer>

            {(analytics?.messages_per_day?.length ?? 0) === 0 &&
              !analyticsQuery.isLoading && (
                <div className="pointer-events-none -mt-32 text-center text-xs text-ink-faint sm:-mt-40">
                  No messages yet in this window.
                </div>
              )}
          </div>
        </div>

        <div className="panel min-w-0 overflow-hidden p-4 sm:p-5">
          <p className="mb-4 text-sm font-semibold text-ink">
            Top Channels
          </p>

          {channelBreakdown.length === 0 ? (
            <p className="text-xs leading-5 text-ink-faint">
              No conversations yet —{" "}
              <Link
                to="/integrations"
                className="text-accent-violet hover:underline"
              >
                connect a channel
              </Link>{" "}
              to start.
            </p>
          ) : (
            <>
              <div className="h-40 min-w-0">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={channelBreakdown}
                      dataKey="count"
                      nameKey="platform"
                      innerRadius={42}
                      outerRadius={62}
                      paddingAngle={2}
                      stroke="none"
                    >
                      {channelBreakdown.map((entry) => (
                        <Cell
                          key={entry.platform}
                          fill={
                            CHANNEL_COLORS[entry.platform] ??
                            "#6B6E89"
                          }
                        />
                      ))}
                    </Pie>

                    <Tooltip
                      contentStyle={{
                        borderRadius: 12,
                        border: "1px solid #232544",
                        fontSize: 12,
                        background: "#12132B",
                        color: "#F4F4F8",
                      }}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>

              <div className="mt-2 space-y-2">
                {channelBreakdown.map((channel) => (
                  <div
                    key={channel.platform}
                    className="flex min-w-0 items-center justify-between gap-3 text-xs"
                  >
                    <span className="flex min-w-0 items-center gap-2 capitalize text-ink-muted">
                      <span
                        className="h-2 w-2 shrink-0 rounded-full"
                        style={{
                          backgroundColor:
                            CHANNEL_COLORS[channel.platform] ??
                            "#6B6E89",
                        }}
                      />

                      <span className="truncate">
                        {channel.platform.replace("_", " ")}
                      </span>
                    </span>

                    <span className="shrink-0 tabular-nums text-ink">
                      {channel.count} ({channel.pct}%)
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      <div className="grid min-w-0 grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="panel min-w-0 overflow-hidden p-4 sm:p-5">
          <div className="mb-4 flex items-center justify-between gap-3">
            <p className="text-sm font-semibold text-ink">
              AI Agents Performance
            </p>

            <Link
              to="/agents"
              className="shrink-0 text-xs text-accent-violet hover:underline"
            >
              Manage
            </Link>
          </div>

          <div className="space-y-4">
            {agentPerformance.length === 0 && (
              <p className="text-xs text-ink-faint">
                No agent activity in this window yet.
              </p>
            )}

            {agentPerformance.map((row) => (
              <div
                key={row.agent_id}
                className="flex min-w-0 items-center gap-3"
              >
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent-violet/10 text-accent-violet">
                  <Bot className="h-4 w-4" />
                </span>

                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-ink">
                    {row.agent_name}
                  </p>

                  <p className="truncate text-xs text-ink-faint">
                    {row.conversationCount} conversations
                  </p>
                </div>

                <p className="shrink-0 text-xs font-semibold tabular-nums text-ink sm:text-sm">
                  {row.message_count} msgs
                </p>
              </div>
            ))}
          </div>
        </div>

        <div className="panel min-w-0 overflow-hidden p-4 sm:p-5">
          <div className="mb-4 flex items-center justify-between gap-3">
            <p className="text-sm font-semibold text-ink">
              Recent Orders
            </p>

            <Link
              to="/orders"
              className="shrink-0 text-xs text-accent-violet hover:underline"
            >
              View all
            </Link>
          </div>

          <div className="space-y-1">
            {recentOrders.length === 0 && (
              <p className="text-xs text-ink-faint">
                No orders yet.
              </p>
            )}

            {recentOrders.map((order) => (
              <Link
                key={order.id}
                to="/orders"
                className="flex min-w-0 items-center justify-between gap-3 rounded-lg px-1.5 py-2.5 text-xs transition-colors hover:bg-base-panel-2"
              >
                <div className="min-w-0">
                  <p className="truncate font-medium text-ink">
                    #{order.id.slice(0, 8).toUpperCase()}
                  </p>

                  <p className="text-ink-faint">
                    {new Date(
                      order.created_at
                    ).toLocaleDateString()}
                  </p>
                </div>

                <div className="flex shrink-0 items-center gap-2">
                  <span className="hidden tabular-nums text-ink-muted sm:inline">
                    {new Intl.NumberFormat(undefined, {
                      style: "currency",
                      currency: order.currency,
                      maximumFractionDigits: 0,
                    }).format(Number(order.total_amount))}
                  </span>

                  <span
                    className={`rounded-full px-2 py-0.5 text-[10px] font-medium capitalize ${
                      ORDER_STATUS_STYLES[order.status] ??
                      "bg-ink-faint/15 text-ink-faint"
                    }`}
                  >
                    {order.status}
                  </span>
                </div>
              </Link>
            ))}
          </div>
        </div>

        <div className="panel min-w-0 overflow-hidden p-4 sm:p-5">
          <p className="mb-4 text-sm font-semibold text-ink">
            Quick Actions
          </p>

          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <QuickAction
              to="/agents"
              icon={Bot}
              label="Create AI Agent"
            />

            <QuickAction
              to="/knowledge"
              icon={BookOpen}
              label="Upload to Knowledge Base"
            />

            <QuickAction
              to="/products"
              icon={Package}
              label="Add New Product"
            />

            <QuickAction
              to="/training"
              icon={Workflow}
              label="Create Workflow"
            />

            <QuickAction
              to="/analytics"
              icon={BarChart3}
              label="View Analytics"
              className="sm:col-span-2"
            />
          </div>
        </div>
      </div>

      <div className="panel min-w-0 overflow-hidden p-4 sm:p-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <p className="text-sm font-semibold text-ink">
            Live Feed
          </p>

          <Link
            to="/notifications"
            className="shrink-0 text-xs text-accent-violet hover:underline"
          >
            View all
          </Link>
        </div>

        {recentFeed.length === 0 ? (
          <p className="flex items-start gap-2 text-xs leading-5 text-ink-faint">
            <Bell className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              Nothing new yet — activity will show up here as it
              happens.
            </span>
          </p>
        ) : (
          <div className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {recentFeed.map((notification) => {
              const Icon =
                FEED_ICONS[notification.type] ?? Bell;

              return (
                <div
                  key={notification.id}
                  className="flex min-w-0 items-start gap-3 rounded-xl border border-base-border p-3"
                >
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-base-panel-2 text-ink-muted">
                    <Icon className="h-4 w-4" />
                  </span>

                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-medium text-ink">
                      {notification.title}
                    </p>

                    {notification.body && (
                      <p className="truncate text-[11px] text-ink-muted">
                        {notification.body}
                      </p>
                    )}

                    <p className="mt-0.5 text-[10px] text-ink-faint">
                      {formatDistanceToNow(
                        new Date(notification.created_at),
                        { addSuffix: true }
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
  );
}

const STAT_COLOR_STYLES: Record<string, string> = {
  "accent-violet":
    "bg-accent-violet/10 text-accent-violet",
  "accent-green":
    "bg-accent-green/10 text-accent-green",
  "accent-blue":
    "bg-accent-blue/10 text-accent-blue",
  "accent-orange":
    "bg-accent-orange/10 text-accent-orange",
};

function StatCard({
  icon: Icon,
  color,
  label,
  value,
  deltaPct,
  sublabel,
}: {
  icon: React.ElementType;
  color: string;
  label: string;
  value: string;
  deltaPct: number;
  sublabel: string;
}) {
  const positive = deltaPct >= 0;

  return (
    <div className="panel min-w-0 overflow-hidden p-4 sm:p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <span
          className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${
            STAT_COLOR_STYLES[color] ??
            STAT_COLOR_STYLES["accent-violet"]
          }`}
        >
          <Icon className="h-5 w-5" />
        </span>

        <span
          className={`flex shrink-0 items-center gap-0.5 text-xs font-medium ${
            positive
              ? "text-accent-green"
              : "text-accent-pink"
          }`}
        >
          {positive ? (
            <ArrowUpRight className="h-3.5 w-3.5" />
          ) : (
            <ArrowDownRight className="h-3.5 w-3.5" />
          )}

          {Math.abs(deltaPct)}%
        </span>
      </div>

      <p className="stat-value max-w-full truncate text-xl sm:text-2xl">
        {value}
      </p>

      <p className="mt-1 truncate text-xs text-ink-muted">
        {label}
      </p>

      <p className="mt-2 truncate text-[11px] text-ink-faint">
        {sublabel}
      </p>
    </div>
  );
}

function QuickAction({
  to,
  icon: Icon,
  label,
  className = "",
}: {
  to: string;
  icon: React.ElementType;
  label: string;
  className?: string;
}) {
  return (
    <Link
      to={to}
      className={`flex min-w-0 items-center gap-2 rounded-xl border border-base-border px-3 py-3 text-xs font-medium text-ink-muted transition-colors hover:border-accent-violet/40 hover:bg-accent-violet/5 hover:text-accent-violet ${className}`}
    >
      <Icon className="h-3.5 w-3.5 shrink-0" />

      <span className="min-w-0 break-words">
        {label}
      </span>
    </Link>
  );
}