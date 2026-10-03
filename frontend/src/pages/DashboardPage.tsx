import { useMemo, useState, type ElementType, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  MessageSquare, ShoppingBag, Users, Wallet, Bot, BookOpen, Package,
  Workflow, Send, BarChart3, Bell, ArrowUpRight, ArrowDownRight,
  ChevronRight, CircleAlert, CircleCheck, Receipt, CheckCircle2,
  AlertTriangle, Radio, Plus,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";

import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import type {
  Agent, Conversation, Order, Customer, AnalyticsSummary, Notification,
  NotificationType,
} from "@/types";

/* ------------------------------ Configuration ----------------------------- */

const RANGES = [
  { label: "Last 7 days", days: 7 },
  { label: "Last 14 days", days: 14 },
  { label: "Last 30 days", days: 30 },
  { label: "Last 90 days", days: 90 },
];

const CHANNEL_COLORS: Record<string, string> = {
  whatsapp: "#22C55E", telegram: "#3B82F6", instagram: "#EC4899",
  messenger: "#FB923C", discord: "#8B5CF6", slack: "#A855F7",
  web_widget: "#22D3EE", voice: "#F59E0B",
};

const STATUS_STYLES: Record<string, string> = {
  pending: "bg-accent-amber/10 text-accent-amber",
  confirmed: "bg-accent-blue/10 text-accent-blue",
  preparing: "bg-accent-violet/10 text-accent-violet",
  ready: "bg-accent-cyan/10 text-accent-cyan",
  delivered: "bg-accent-green/10 text-accent-green",
  cancelled: "bg-ink-faint/10 text-ink-faint",
  refunded: "bg-accent-pink/10 text-accent-pink",
};

const FEED_ICONS: Record<NotificationType, ElementType> = {
  new_conversation: MessageSquare,
  knowledge_ingestion_failed: AlertTriangle,
  integration_error: AlertTriangle,
  new_order: ShoppingBag,
  receipt_uploaded: Receipt,
  payment_confirmed: CheckCircle2,
};

const DAY = 86_400_000;
const byNewest = (a: { created_at: string }, b: { created_at: string }) =>
  new Date(b.created_at).getTime() - new Date(a.created_at).getTime();

/* ---------------------------- 3D layered model ---------------------------- */

const MODEL_CSS = `
.pa-scene{perspective:1000px}
.pa-stack{transform-style:preserve-3d;transform:rotateX(58deg) rotateZ(-38deg);animation:pa-drift 9s ease-in-out infinite}
.pa-plate{position:absolute;inset:0;border-radius:22px;transform-style:preserve-3d}
.pa-plate::after{content:"";position:absolute;inset:0;border-radius:inherit;transform:translateZ(-7px);background:rgb(0 0 0/.35);filter:blur(.5px)}
.pa-node{position:absolute;width:14px;height:14px;border-radius:999px;transform:translateZ(20px)}
.pa-beam{position:absolute;left:50%;top:50%;width:2px;height:150px;margin:-75px 0 0 -1px;transform:rotateX(-90deg);transform-origin:center;background:linear-gradient(to top,transparent,rgb(139 92 246/.9),transparent)}
@keyframes pa-drift{0%,100%{transform:rotateX(58deg) rotateZ(-38deg) translateZ(0)}50%{transform:rotateX(58deg) rotateZ(-30deg) translateZ(10px)}}
@media (prefers-reduced-motion:reduce){.pa-stack{animation:none}}
`;

function LayerModel({ channels, agents, orders }: { channels: number; agents: number; orders: number }) {
  const layers = [
    { name: "Orders", value: orders, z: 0, tint: "from-accent-green/30 to-accent-green/5 border-accent-green/40", dot: "#22C55E" },
    { name: "Agents", value: agents, z: 46, tint: "from-accent-violet/40 to-accent-violet/10 border-accent-violet/50", dot: "#8B5CF6" },
    { name: "Channels", value: channels, z: 92, tint: "from-accent-blue/30 to-accent-blue/5 border-accent-blue/40", dot: "#3B82F6" },
  ];

  return (
    <div className="flex w-full flex-col items-center gap-5 sm:flex-row sm:justify-end lg:gap-8">
      <div className="pa-scene relative h-44 w-44 shrink-0 sm:h-52 sm:w-52" aria-hidden="true">
        <style>{MODEL_CSS}</style>
        <div className="pa-stack absolute left-1/2 top-1/2 h-28 w-28 -ml-14 -mt-14 sm:h-32 sm:w-32 sm:-ml-16 sm:-mt-16">
          {layers.map((l) => (
            <div
              key={l.name}
              className={`pa-plate border bg-gradient-to-br ${l.tint}`}
              style={{ transform: `translateZ(${l.z}px)` }}
            >
              <span className="pa-node" style={{ background: l.dot, boxShadow: `0 0 18px ${l.dot}` }} />
            </div>
          ))}
          <span className="pa-beam" />
        </div>
      </div>

      <dl className="grid w-full max-w-xs grid-cols-3 gap-2 sm:w-40 sm:grid-cols-1">
        {[...layers].reverse().map((l) => (
          <div key={l.name} className="flex items-baseline justify-between gap-2 rounded-lg bg-base-panel-2/70 px-3 py-2 sm:py-1.5">
            <dt className="flex items-center gap-2 text-xs text-ink-muted">
              <span className="h-2 w-2 rounded-full" style={{ background: l.dot }} />
              {l.name}
            </dt>
            <dd className="text-sm font-semibold tabular-nums text-ink">{l.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/* ---------------------------------- Page ---------------------------------- */

export default function DashboardPage() {
  const user = useAuthStore((s) => s.user);
  const [rangeDays, setRangeDays] = useState(30);

  const analyticsQ = useQuery({
    queryKey: ["analytics-summary", rangeDays],
    queryFn: async () =>
      (await api.get<AnalyticsSummary>("/analytics/summary", { params: { days: rangeDays } })).data,
  });
  const agents = useQuery({ queryKey: ["agents"], queryFn: async () => (await api.get<Agent[]>("/agents")).data }).data ?? [];
  const conversations = useQuery({ queryKey: ["conversations"], queryFn: async () => (await api.get<Conversation[]>("/conversations")).data }).data ?? [];
  const orders = useQuery({ queryKey: ["orders"], queryFn: async () => (await api.get<Order[]>("/orders")).data }).data ?? [];
  const customers = useQuery({ queryKey: ["customers"], queryFn: async () => (await api.get<Customer[]>("/customers")).data }).data ?? [];
  const notifications = useQuery({ queryKey: ["notifications"], queryFn: async () => (await api.get<Notification[]>("/notifications")).data }).data ?? [];

  const analytics = analyticsQ.data;
  const firstName = user?.full_name?.trim()?.split(/\s+/)[0] || "there";

  /* Period comparison */
  const { current: cutCur, previous: cutPrev } = useMemo(() => {
    const now = Date.now();
    return { current: now - rangeDays * DAY, previous: now - 2 * rangeDays * DAY };
  }, [rangeDays]);

  const pctChange = (cur: number, prev: number) =>
    prev === 0 ? (cur > 0 ? 100 : 0) : Math.round(((cur - prev) / prev) * 100);

  const countWindow = (items: { created_at: string }[]) => {
    let cur = 0, prev = 0;
    for (const i of items) {
      const t = new Date(i.created_at).getTime();
      if (t >= cutCur) cur++;
      else if (t >= cutPrev) prev++;
    }
    return { cur, pct: pctChange(cur, prev) };
  };

  const convW = countWindow(conversations);
  const custW = countWindow(customers);

  const revenueIn = (from: number, to: number) =>
    orders
      .filter((o) => {
        const t = new Date(o.created_at).getTime();
        return o.payment_status === "paid" && t >= from && t < to;
      })
      .reduce((s, o) => s + Number(o.total_amount), 0);

  const revenue = revenueIn(cutCur, Infinity);
  const revenuePct = pctChange(revenue, revenueIn(cutPrev, cutCur));
  const currency = orders[0]?.currency ?? "NGN";
  const money = (v: number, c = currency) =>
    new Intl.NumberFormat(undefined, { style: "currency", currency: c, maximumFractionDigits: 0 }).format(v);

  /* Derived lists */
  const channels = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const c of conversations) {
      const p = c.platform || "unknown";
      counts[p] = (counts[p] ?? 0) + 1;
    }
    const total = conversations.length || 1;
    return Object.entries(counts)
      .map(([platform, count]) => ({ platform, count, pct: Math.round((count / total) * 100) }))
      .sort((a, b) => b.count - a.count);
  }, [conversations]);

  const topAgents = useMemo(() => {
    const convBy: Record<string, number> = {};
    for (const c of conversations) if (c.agent_id) convBy[c.agent_id] = (convBy[c.agent_id] ?? 0) + 1;
    return (analytics?.messages_by_agent ?? [])
      .map((r) => ({
        ...r,
        conversations: convBy[r.agent_id] ?? 0,
        status: agents.find((a) => a.id === r.agent_id)?.status ?? "active",
      }))
      .sort((a, b) => b.message_count - a.message_count)
      .slice(0, 4);
  }, [analytics, conversations, agents]);

  const recentOrders = [...orders].sort(byNewest).slice(0, 5);
  const feed = [...notifications].sort(byNewest).slice(0, 6);

  const activeAgents = agents.filter((a) => a.status === "active").length;
  const paidOrders = orders.filter((o) => o.payment_status === "paid").length;
  const pendingOrders = orders.filter(
    (o) => o.payment_status !== "paid" && o.status !== "cancelled" && o.status !== "refunded"
  ).length;
  const integrationErrors = notifications.filter((n) => n.type === "integration_error").length;

  const chartData = analytics?.messages_per_day ?? [];

  return (
    <div className="mx-auto w-full min-w-0 max-w-[1400px] space-y-4 pb-8 sm:space-y-5">
      {/* Header: greeting + 3D model */}
      <section className="relative overflow-hidden rounded-2xl border border-base-border bg-base-panel">
        <div className="grid min-w-0 items-center gap-6 p-5 sm:p-7 lg:grid-cols-[1fr_auto] lg:gap-10 lg:p-8">
          <div className="min-w-0">
            <h1 className="font-display text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
              Welcome back, {firstName}
            </h1>
            <p className="mt-2 max-w-md text-sm leading-6 text-ink-muted">
              {conversations.length > 0
                ? `${convW.cur} new conversations and ${money(revenue)} in paid orders over the last ${rangeDays} days.`
                : "Connect a channel and your first conversations will show up here."}
            </p>
            <div className="mt-5 flex flex-col gap-2 sm:flex-row">
              <Link to="/conversations" className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-accent-violet px-4 text-sm font-medium text-white transition hover:brightness-110 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-violet">
                <MessageSquare className="h-4 w-4" /> Open inbox
              </Link>
              <Link to="/analytics" className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-base-border bg-base-panel-2 px-4 text-sm font-medium text-ink transition hover:border-accent-violet/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-violet">
                <BarChart3 className="h-4 w-4" /> View analytics
              </Link>
            </div>
          </div>
          <LayerModel channels={channels.length} agents={activeAgents} orders={orders.length} />
        </div>
      </section>

      {/* Range */}
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-ink">Overview</h2>
        <select
          value={rangeDays}
          onChange={(e) => setRangeDays(Number(e.target.value))}
          aria-label="Date range"
          className="h-9 rounded-lg border border-base-border bg-base-panel px-3 text-sm text-ink outline-none transition focus:border-accent-violet/50 focus:ring-2 focus:ring-accent-violet/15"
        >
          {RANGES.map((r) => (
            <option key={r.days} value={r.days}>{r.label}</option>
          ))}
        </select>
      </div>

      {/* KPI strip: one joined panel */}
      <section className="grid grid-cols-2 overflow-hidden rounded-2xl border border-base-border bg-base-panel lg:grid-cols-4">
        <Kpi icon={MessageSquare} tone="text-accent-violet" label="Conversations" value={conversations.length.toLocaleString()} delta={convW.pct} note={`${convW.cur} this period`} className="border-b border-r border-base-border lg:border-b-0" />
        <Kpi icon={Users} tone="text-accent-green" label="Customers" value={customers.length.toLocaleString()} delta={custW.pct} note={`${custW.cur} new this period`} className="border-b border-base-border lg:border-b-0 lg:border-r" />
        <Kpi icon={Wallet} tone="text-accent-blue" label="Paid revenue" value={money(revenue)} delta={revenuePct} note={`${paidOrders} paid orders`} className="border-r border-base-border" />
        <Kpi icon={Bot} tone="text-accent-orange" label="Active agents" value={`${activeAgents}`} note={`of ${agents.length} total`} />
      </section>

      {/* Chart + attention */}
      <div className="grid min-w-0 gap-4 xl:grid-cols-3">
        <Panel className="xl:col-span-2" title="Messages" hint="Daily volume across all channels" action={<PanelLink to="/analytics">Details</PanelLink>}>
          <div className="relative h-56 min-w-0 sm:h-72">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 8, right: 4, left: -22, bottom: 0 }}>
                <defs>
                  <linearGradient id="paFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#8B5CF6" stopOpacity={0.28} />
                    <stop offset="100%" stopColor="#8B5CF6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#232544" vertical={false} strokeDasharray="3 5" />
                <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#6B6E89" }} axisLine={false} tickLine={false} tickFormatter={(d: string) => d.slice(5)} minTickGap={24} />
                <YAxis tick={{ fontSize: 11, fill: "#6B6E89" }} axisLine={false} tickLine={false} allowDecimals={false} width={36} />
                <Tooltip
                  cursor={{ stroke: "#8B5CF6", strokeOpacity: 0.2 }}
                  contentStyle={{ borderRadius: 10, border: "1px solid #232544", fontSize: 12, background: "#12132B", color: "#F4F4F8" }}
                  labelStyle={{ color: "#F4F4F8", fontWeight: 600 }}
                />
                <Area type="monotone" dataKey="count" name="Messages" stroke="#8B5CF6" strokeWidth={2} fill="url(#paFill)" activeDot={{ r: 4 }} />
              </AreaChart>
            </ResponsiveContainer>
            {chartData.length === 0 && !analyticsQ.isLoading && (
              <p className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-ink-faint">
                No messages in this period
              </p>
            )}
          </div>
        </Panel>

        <Panel title="Needs attention" hint="Items waiting on you">
          {pendingOrders + integrationErrors === 0 ? (
            <div className="flex min-h-40 flex-col items-center justify-center gap-2 text-center">
              <CircleCheck className="h-6 w-6 text-accent-green" />
              <p className="text-sm font-medium text-ink">All clear</p>
              <p className="max-w-[220px] text-xs leading-5 text-ink-faint">Nothing needs action right now.</p>
            </div>
          ) : (
            <ul className="space-y-2">
              {pendingOrders > 0 && (
                <Attention to="/orders" icon={ShoppingBag} tone="bg-accent-amber/10 text-accent-amber" title={`${pendingOrders} unpaid ${pendingOrders === 1 ? "order" : "orders"}`} sub="Review pending orders" />
              )}
              {integrationErrors > 0 && (
                <Attention to="/integrations" icon={CircleAlert} tone="bg-accent-pink/10 text-accent-pink" title={`${integrationErrors} integration ${integrationErrors === 1 ? "error" : "errors"}`} sub="Fix connection problems" />
              )}
            </ul>
          )}
        </Panel>
      </div>

      {/* Channels + agents */}
      <div className="grid min-w-0 gap-4 lg:grid-cols-2">
        <Panel title="Channels" hint="Where customers reach you" action={<PanelLink to="/integrations">Manage</PanelLink>}>
          {channels.length === 0 ? (
            <Empty icon={Radio} title="No channels yet" body="Connect WhatsApp or Telegram to start receiving conversations." to="/integrations" cta="Connect a channel" />
          ) : (
            <ul className="space-y-4">
              {channels.slice(0, 5).map((c) => {
                const color = CHANNEL_COLORS[c.platform] ?? "#6B6E89";
                return (
                  <li key={c.platform} className="min-w-0">
                    <div className="mb-1.5 flex items-center justify-between gap-3 text-sm">
                      <span className="flex min-w-0 items-center gap-2 text-ink">
                        <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: color }} />
                        <span className="truncate capitalize">{c.platform.replace(/_/g, " ")}</span>
                      </span>
                      <span className="shrink-0 tabular-nums text-ink-muted">
                        {c.count} <span className="text-ink-faint">· {c.pct}%</span>
                      </span>
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-base-panel-2">
                      <div className="h-full rounded-full transition-[width] duration-700" style={{ width: `${Math.max(2, c.pct)}%`, background: color }} />
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </Panel>

        <Panel title="AI agents" hint="Who is handling the workload" action={<PanelLink to="/agents">Manage</PanelLink>}>
          {topAgents.length === 0 ? (
            <Empty icon={Bot} title="No agent activity yet" body="Agents appear here once they start answering conversations." to="/agents" cta="Create an agent" />
          ) : (
            <ul className="divide-y divide-base-border/60">
              {topAgents.map((a) => (
                <li key={a.agent_id} className="flex min-w-0 items-center gap-3 py-3 first:pt-0 last:pb-0">
                  <span className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-violet/10 text-accent-violet">
                    <Bot className="h-4 w-4" />
                    <span className={`absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-base-panel ${a.status === "active" ? "bg-accent-green" : "bg-ink-faint"}`} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-ink">{a.agent_name}</p>
                    <p className="truncate text-xs text-ink-faint">
                      {a.conversations} conversations · <span className="capitalize">{a.status}</span>
                    </p>
                  </div>
                  <p className="shrink-0 text-right text-sm font-semibold tabular-nums text-ink">
                    {a.message_count.toLocaleString()}
                    <span className="block text-xs font-normal text-ink-faint">messages</span>
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      {/* Orders + quick actions */}
      <div className="grid min-w-0 gap-4 xl:grid-cols-3">
        <Panel className="xl:col-span-2" title="Recent orders" hint="Latest orders and payment status" action={<PanelLink to="/orders">View all</PanelLink>}>
          {recentOrders.length === 0 ? (
            <Empty icon={ShoppingBag} title="No orders yet" body="Orders placed through your agents will show up here." />
          ) : (
            <div className="-mx-4 overflow-x-auto sm:mx-0">
              <table className="w-full min-w-[520px] text-left text-sm">
                <thead>
                  <tr className="border-b border-base-border text-xs text-ink-faint">
                    <th className="px-4 pb-2 font-medium sm:px-0">Order</th>
                    <th className="pb-2 font-medium">Date</th>
                    <th className="pb-2 text-right font-medium">Amount</th>
                    <th className="px-4 pb-2 text-right font-medium sm:px-0">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-base-border/60">
                  {recentOrders.map((o) => (
                    <tr key={o.id} className="transition hover:bg-base-panel-2/60">
                      <td className="px-4 py-3 sm:px-0">
                        <Link to="/orders" className="font-medium text-ink hover:text-accent-violet">#{o.id.slice(0, 8).toUpperCase()}</Link>
                        <p className="text-xs text-ink-faint">{o.payment_status === "paid" ? "Paid" : "Awaiting payment"}</p>
                      </td>
                      <td className="py-3 text-ink-muted">{new Date(o.created_at).toLocaleDateString()}</td>
                      <td className="py-3 text-right font-semibold tabular-nums text-ink">{money(Number(o.total_amount), o.currency || currency)}</td>
                      <td className="px-4 py-3 text-right sm:px-0">
                        <span className={`inline-block rounded-md px-2 py-1 text-xs font-medium capitalize ${STATUS_STYLES[o.status] ?? "bg-ink-faint/10 text-ink-faint"}`}>{o.status}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        <Panel title="Quick actions" hint="Set things up faster">
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
            {[
              { to: "/agents", icon: Bot, label: "Create agent" },
              { to: "/knowledge", icon: BookOpen, label: "Upload knowledge" },
              { to: "/products", icon: Package, label: "Add product" },
              { to: "/training", icon: Workflow, label: "Build workflow" },
              { to: "/integrations", icon: Send, label: "Connect channel" },
            ].map(({ to, icon: Icon, label }) => (
              <Link key={to} to={to} className="group flex h-11 items-center gap-3 rounded-lg border border-base-border px-3 text-sm text-ink-muted transition hover:border-accent-violet/40 hover:bg-base-panel-2 hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent-violet">
                <Icon className="h-4 w-4 shrink-0 text-ink-faint transition group-hover:text-accent-violet" />
                <span className="flex-1 truncate">{label}</span>
                <Plus className="h-3.5 w-3.5 shrink-0 text-ink-faint" />
              </Link>
            ))}
          </div>
        </Panel>
      </div>

      {/* Activity */}
      <Panel title="Activity" hint="Recent events in your workspace" action={<PanelLink to="/notifications">View all</PanelLink>}>
        {feed.length === 0 ? (
          <Empty icon={Bell} title="Nothing new" body="Events show up here as your business runs." />
        ) : (
          <ul className="grid gap-x-8 gap-y-1 md:grid-cols-2">
            {feed.map((n) => {
              const Icon = FEED_ICONS[n.type] ?? Bell;
              return (
                <li key={n.id} className="flex min-w-0 items-start gap-3 border-b border-base-border/50 py-3">
                  <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-base-panel-2 text-ink-muted">
                    <Icon className="h-4 w-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-ink">{n.title}</p>
                    {n.body && <p className="truncate text-xs text-ink-muted">{n.body}</p>}
                  </div>
                  <time className="shrink-0 pt-0.5 text-xs text-ink-faint">
                    {formatDistanceToNow(new Date(n.created_at), { addSuffix: true })}
                  </time>
                </li>
              );
            })}
          </ul>
        )}
      </Panel>
    </div>
  );
}

/* ------------------------------ Building blocks --------------------------- */

function Kpi({
  icon: Icon, tone, label, value, delta, note, className = "",
}: {
  icon: ElementType; tone: string; label: string; value: string;
  delta?: number; note: string; className?: string;
}) {
  const up = (delta ?? 0) >= 0;
  return (
    <div className={`min-w-0 p-4 sm:p-5 ${className}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-sm text-ink-muted">
          <Icon className={`h-4 w-4 ${tone}`} />
          <span className="truncate">{label}</span>
        </span>
        {delta !== undefined && (
          <span className={`flex shrink-0 items-center text-xs font-medium tabular-nums ${up ? "text-accent-green" : "text-accent-pink"}`}>
            {up ? <ArrowUpRight className="h-3.5 w-3.5" /> : <ArrowDownRight className="h-3.5 w-3.5" />}
            {Math.abs(delta)}%
          </span>
        )}
      </div>
      <p className="mt-3 truncate text-xl font-semibold tabular-nums tracking-tight text-ink sm:text-2xl">{value}</p>
      <p className="mt-1 truncate text-xs text-ink-faint">{note}</p>
    </div>
  );
}

function Panel({
  title, hint, action, className = "", children,
}: {
  title: string; hint?: string; action?: ReactNode; className?: string; children: ReactNode;
}) {
  return (
    <section className={`min-w-0 rounded-2xl border border-base-border bg-base-panel p-4 sm:p-5 ${className}`}>
      <header className="mb-4 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold text-ink">{title}</h2>
          {hint && <p className="mt-0.5 text-xs text-ink-faint">{hint}</p>}
        </div>
        {action}
      </header>
      {children}
    </section>
  );
}

function PanelLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="flex shrink-0 items-center gap-0.5 text-xs font-medium text-accent-violet hover:underline">
      {children}
      <ChevronRight className="h-3.5 w-3.5" />
    </Link>
  );
}

function Attention({
  to, icon: Icon, tone, title, sub,
}: { to: string; icon: ElementType; tone: string; title: string; sub: string }) {
  return (
    <li>
      <Link to={to} className="group flex items-center gap-3 rounded-lg border border-base-border p-3 transition hover:bg-base-panel-2">
        <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${tone}`}>
          <Icon className="h-4 w-4" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-ink">{title}</span>
          <span className="block truncate text-xs text-ink-faint">{sub}</span>
        </span>
        <ChevronRight className="h-4 w-4 shrink-0 text-ink-faint transition group-hover:translate-x-0.5" />
      </Link>
    </li>
  );
}

function Empty({
  icon: Icon, title, body, to, cta,
}: { icon: ElementType; title: string; body: string; to?: string; cta?: string }) {
  return (
    <div className="flex min-h-32 flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-base-border px-4 py-6 text-center">
      <Icon className="h-5 w-5 text-ink-faint" />
      <p className="mt-1 text-sm font-medium text-ink">{title}</p>
      <p className="max-w-xs text-xs leading-5 text-ink-faint">{body}</p>
      {to && cta && (
        <Link to={to} className="mt-2 text-xs font-medium text-accent-violet hover:underline">{cta}</Link>
      )}
    </div>
  );
}
