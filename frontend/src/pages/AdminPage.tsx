import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Shield,
  Users,
  Building2,
  Wallet,
  Bot,
  Search,
  Ban,
  CheckCircle2,
  ShieldPlus,
  Loader2,
  CreditCard,
  ArrowUpRight,
  ArrowDownRight,
  Database,
  HardDrive,
  Bell,
  UserPlus,
  Settings,
  Receipt,
} from "lucide-react";
import { toast } from "sonner";
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
import { api, apiErrorMessage } from "@/lib/api";
import { cn } from "@/lib/utils";

interface AdminUserRow {
  id: string;
  email: string;
  full_name: string;
  business_name: string | null;
  is_active: boolean;
  is_email_verified: boolean;
  is_platform_admin: boolean;
  created_at: string;
  agent_count: number;
  conversation_count: number;
  message_count: number;
}

interface PlanDistributionRow {
  plan_id: string | null;
  plan_name: string;
  count: number;
  percent: number;
}

interface RecentTransactionRow {
  id: string;
  user_email: string | null;
  user_full_name: string | null;
  amount: number | null;
  currency: string | null;
  event_type: string;
  processed: boolean;
  created_at: string;
}

interface AdminDashboard {
  total_users: number;
  active_businesses: number;
  monthly_revenue: number;
  monthly_revenue_currency: string;
  monthly_revenue_change_pct: number | null;
  active_agents: number;
  revenue_last_7_days: { date: string; amount: number }[];
  subscription_distribution: PlanDistributionRow[];
  recent_users: AdminUserRow[];
  recent_transactions: RecentTransactionRow[];
  system_health: { database_ok: boolean; storage_ok: boolean; storage_used_bytes: number | null };
}

const DONUT_COLORS = ["#8B5CF6", "#3B82F6", "#22C55E", "#F59E0B", "#EC4899", "#22D3EE"];

const TX_STATUS_STYLE: Record<string, string> = {
  true: "bg-emerald-500/15 text-emerald-400",
  false: "bg-amber-500/15 text-amber-400",
};

export default function AdminPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");

  const dashboardQuery = useQuery({
    queryKey: ["admin-dashboard"],
    queryFn: async () => (await api.get<AdminDashboard>("/admin/dashboard")).data,
  });

  const usersQuery = useQuery({
    queryKey: ["admin-users", search],
    queryFn: async () =>
      (await api.get<AdminUserRow[]>("/admin/users", { params: search ? { search } : {} })).data,
  });

  const suspend = useMutation({
    mutationFn: async (id: string) => api.post(`/admin/users/${id}/suspend`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      queryClient.invalidateQueries({ queryKey: ["admin-dashboard"] });
      toast.success("User suspended");
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  const reactivate = useMutation({
    mutationFn: async (id: string) => api.post(`/admin/users/${id}/reactivate`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      queryClient.invalidateQueries({ queryKey: ["admin-dashboard"] });
      toast.success("User reactivated");
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  const promote = useMutation({
    mutationFn: async (id: string) => api.post(`/admin/users/${id}/promote`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      toast.success("User promoted to platform admin");
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  const dash = dashboardQuery.data;
  const users = usersQuery.data ?? [];
  const currencyFmt = new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: dash?.monthly_revenue_currency ?? "NGN",
    maximumFractionDigits: 0,
  });

  return (
    <div className="-mx-8 -my-6 min-h-[calc(100vh-4rem)] bg-[#0B0C1E] p-8 text-[#C6C8DA]">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Shield className="h-5 w-5 text-violet-400" />
          <div>
            <h1 className="font-display text-xl font-semibold text-white">Welcome back, Admin 👋</h1>
            <p className="text-sm text-[#7A7E9C]">Here's what's happening on your platform today.</p>
          </div>
        </div>
        <Link
          to="/admin/billing-plans"
          className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-sm text-[#C6C8DA] transition-colors hover:bg-white/10"
        >
          <CreditCard className="h-4 w-4" />
          Billing Plans
        </Link>
      </div>

      {/* Top stat row */}
      <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <DarkStat icon={Users} color="#8B5CF6" label="Total Users" value={dash?.total_users?.toLocaleString()} />
        <DarkStat
          icon={Building2}
          color="#3B82F6"
          label="Active Businesses"
          value={dash?.active_businesses?.toLocaleString()}
        />
        <DarkStat
          icon={Wallet}
          color="#22C55E"
          label="Monthly Revenue"
          value={dash ? currencyFmt.format(dash.monthly_revenue) : undefined}
          deltaPct={dash?.monthly_revenue_change_pct ?? undefined}
        />
        <DarkStat icon={Bot} color="#F59E0B" label="Active AI Agents" value={dash?.active_agents?.toLocaleString()} />
      </div>

      {/* Revenue chart + distribution + quick actions */}
      <div className="mb-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="rounded-2xl border border-white/10 bg-[#12132B] p-5 xl:col-span-1">
          <div className="mb-1 flex items-center justify-between">
            <p className="text-sm font-semibold text-white">Revenue Overview</p>
            <span className="rounded-lg border border-white/10 px-2 py-1 text-[11px] text-[#7A7E9C]">Last 7 days</span>
          </div>
          <div className="mb-3 flex items-baseline gap-2">
            <span className="flex items-center gap-1 text-[11px] text-violet-400">
              <span className="h-1.5 w-1.5 rounded-full bg-violet-400" /> Total Revenue
            </span>
          </div>
          <p className="mb-2 font-display text-2xl font-semibold text-white">
            {dash ? currencyFmt.format(dash.monthly_revenue) : "—"}
            {dash?.monthly_revenue_change_pct != null && (
              <span
                className={cn(
                  "ml-2 inline-flex items-center gap-0.5 align-middle text-xs font-medium",
                  dash.monthly_revenue_change_pct >= 0 ? "text-emerald-400" : "text-rose-400"
                )}
              >
                {dash.monthly_revenue_change_pct >= 0 ? (
                  <ArrowUpRight className="h-3 w-3" />
                ) : (
                  <ArrowDownRight className="h-3 w-3" />
                )}
                {Math.abs(dash.monthly_revenue_change_pct)}%
              </span>
            )}
          </p>
          <div className="h-40">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={dash?.revenue_last_7_days ?? []}>
                <defs>
                  <linearGradient id="adminRevenueFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#8B5CF6" stopOpacity={0.4} />
                    <stop offset="100%" stopColor="#8B5CF6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 10, fill: "#7A7E9C" }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={(d: string) => d.slice(5)}
                />
                <YAxis tick={{ fontSize: 10, fill: "#7A7E9C" }} axisLine={false} tickLine={false} width={40} />
                <Tooltip
                  contentStyle={{
                    borderRadius: 12,
                    border: "1px solid rgba(255,255,255,0.1)",
                    background: "#12132B",
                    fontSize: 12,
                    color: "#fff",
                  }}
                  formatter={(value: number) => currencyFmt.format(value)}
                />
                <Area type="monotone" dataKey="amount" name="Revenue" stroke="#8B5CF6" strokeWidth={2} fill="url(#adminRevenueFill)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded-2xl border border-white/10 bg-[#12132B] p-5">
          <p className="mb-4 text-sm font-semibold text-white">Subscription Distribution</p>
          {!dash || dash.subscription_distribution.length === 0 ? (
            <p className="text-xs text-[#7A7E9C]">No active subscriptions yet.</p>
          ) : (
            <>
              <div className="relative h-40">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={dash.subscription_distribution}
                      dataKey="count"
                      nameKey="plan_name"
                      innerRadius={45}
                      outerRadius={65}
                      paddingAngle={2}
                      stroke="none"
                    >
                      {dash.subscription_distribution.map((row, i) => (
                        <Cell key={row.plan_id ?? row.plan_name} fill={DONUT_COLORS[i % DONUT_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{
                        borderRadius: 12,
                        border: "1px solid rgba(255,255,255,0.1)",
                        background: "#12132B",
                        fontSize: 12,
                        color: "#fff",
                      }}
                    />
                  </PieChart>
                </ResponsiveContainer>
                <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                  <p className="text-lg font-semibold text-white">{dash.active_businesses.toLocaleString()}</p>
                  <p className="text-[10px] text-[#7A7E9C]">Total Plans</p>
                </div>
              </div>
              <div className="mt-3 space-y-1.5">
                {dash.subscription_distribution.map((row, i) => (
                  <div key={row.plan_id ?? row.plan_name} className="flex items-center justify-between text-xs">
                    <span className="flex items-center gap-2 text-[#C6C8DA]">
                      <span
                        className="h-2 w-2 rounded-full"
                        style={{ backgroundColor: DONUT_COLORS[i % DONUT_COLORS.length] }}
                      />
                      {row.plan_name}
                    </span>
                    <span className="tabular-nums text-[#7A7E9C]">
                      {row.percent}% ({row.count})
                    </span>
                  </div>
                ))}
              </div>
              <Link
                to="/admin/billing-plans"
                className="mt-3 inline-block text-xs text-violet-400 hover:underline"
              >
                View all plans →
              </Link>
            </>
          )}
        </div>

        <div className="rounded-2xl border border-white/10 bg-[#12132B] p-5">
          <p className="mb-4 text-sm font-semibold text-white">Quick Actions</p>
          <div className="space-y-1">
            <QuickAction to="/admin/billing-plans" icon={CreditCard} label="Create Billing Plan" />
            <QuickAction to="#all-users" icon={UserPlus} label="Add New Admin" hint="promote from the table below" />
            <QuickAction to="/admin/billing-plans" icon={Receipt} label="View All Transactions" />
            <QuickAction to="#all-users" icon={Bell} label="Send Notification" hint="coming soon" disabled />
            <QuickAction to="/settings" icon={Settings} label="System Settings" />
          </div>
        </div>
      </div>

      {/* Recent users / transactions / system health */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="rounded-2xl border border-white/10 bg-[#12132B] p-5">
          <div className="mb-3 flex items-center justify-between">
            <p className="text-sm font-semibold text-white">Recent Users</p>
            <a href="#all-users" className="text-xs text-violet-400 hover:underline">
              View all users →
            </a>
          </div>
          <div className="space-y-3">
            {(dash?.recent_users ?? []).map((u) => (
              <div key={u.id} className="flex items-center gap-3">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-violet-500/20 text-xs font-semibold text-violet-300">
                  {u.full_name.charAt(0).toUpperCase()}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-medium text-white">{u.full_name}</p>
                  <p className="truncate text-[11px] text-[#7A7E9C]">{u.email}</p>
                </div>
                <span
                  className={cn(
                    "shrink-0 rounded-full px-2 py-0.5 text-[10px]",
                    u.is_active ? "bg-emerald-500/15 text-emerald-400" : "bg-rose-500/15 text-rose-400"
                  )}
                >
                  {u.is_active ? "Active" : "Suspended"}
                </span>
              </div>
            ))}
            {dash && dash.recent_users.length === 0 && <p className="text-xs text-[#7A7E9C]">No users yet.</p>}
          </div>
        </div>

        <div className="rounded-2xl border border-white/10 bg-[#12132B] p-5">
          <div className="mb-3 flex items-center justify-between">
            <p className="text-sm font-semibold text-white">Recent Transactions</p>
          </div>
          <div className="space-y-3">
            {(dash?.recent_transactions ?? []).map((tx) => (
              <div key={tx.id} className="flex items-center justify-between text-xs">
                <div className="min-w-0">
                  <p className="truncate text-white">{tx.user_full_name ?? tx.user_email ?? "Unknown user"}</p>
                  <p className="text-[10px] text-[#7A7E9C]">{new Date(tx.created_at).toLocaleDateString()}</p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <span className="tabular-nums text-[#C6C8DA]">
                    {tx.amount != null
                      ? new Intl.NumberFormat(undefined, {
                          style: "currency",
                          currency: tx.currency ?? "NGN",
                          maximumFractionDigits: 0,
                        }).format(tx.amount)
                      : "—"}
                  </span>
                  <span className={cn("rounded-full px-2 py-0.5 text-[10px]", TX_STATUS_STYLE[String(tx.processed)])}>
                    {tx.processed ? "Completed" : "Pending"}
                  </span>
                </div>
              </div>
            ))}
            {dash && dash.recent_transactions.length === 0 && (
              <p className="text-xs text-[#7A7E9C]">No transactions yet.</p>
            )}
          </div>
        </div>

        <div className="rounded-2xl border border-white/10 bg-[#12132B] p-5">
          <p className="mb-3 text-sm font-semibold text-white">System Health</p>
          <div className="mb-4 flex items-center gap-2 rounded-xl bg-emerald-500/10 px-3 py-2">
            <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
            <div>
              <p className="text-xs font-medium text-emerald-400">
                {dash?.system_health.database_ok && dash?.system_health.storage_ok
                  ? "All Systems Operational"
                  : "Attention Needed"}
              </p>
              <p className="text-[11px] text-[#7A7E9C]">Live checks, not simulated.</p>
            </div>
          </div>
          <div className="space-y-3">
            <HealthRow icon={Database} label="Database" ok={dash?.system_health.database_ok} />
            <HealthRow
              icon={HardDrive}
              label="Storage"
              ok={dash?.system_health.storage_ok}
              detail={
                dash?.system_health.storage_used_bytes != null
                  ? `${(dash.system_health.storage_used_bytes / 1024 / 1024).toFixed(1)} MB used`
                  : undefined
              }
            />
          </div>
        </div>
      </div>

      {/* Full user management table */}
      <div id="all-users" className="mt-6 scroll-mt-6">
        <div className="mb-3 flex items-center gap-2 rounded-2xl border border-white/10 bg-[#12132B] p-3">
          <Search className="ml-2 h-4 w-4 shrink-0 text-[#7A7E9C]" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search users by name or email…"
            className="w-full bg-transparent text-sm text-white placeholder:text-[#7A7E9C] focus:outline-none"
          />
        </div>

        <div className="overflow-x-auto rounded-2xl border border-white/10 bg-[#12132B]">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-white/10 text-xs text-[#7A7E9C]">
                <th className="px-4 py-3 font-medium">User</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Agents</th>
                <th className="px-4 py-3 font-medium">Conversations</th>
                <th className="px-4 py-3 font-medium">Messages</th>
                <th className="px-4 py-3 font-medium">Joined</th>
                <th className="px-4 py-3 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/10">
              {usersQuery.isLoading && (
                <tr>
                  <td colSpan={7} className="px-4 py-6 text-center text-[#7A7E9C]">
                    Loading…
                  </td>
                </tr>
              )}
              {users.map((row) => (
                <tr key={row.id}>
                  <td className="px-4 py-3">
                    <p className="text-white">{row.full_name}</p>
                    <p className="text-xs text-[#7A7E9C]">
                      {row.email}
                      {row.is_platform_admin && (
                        <span className="ml-2 rounded-full bg-violet-500/15 px-1.5 py-0.5 text-[10px] text-violet-300">
                          admin
                        </span>
                      )}
                    </p>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={cn(
                        "rounded-full px-2 py-0.5 text-[10px]",
                        row.is_active ? "bg-emerald-500/15 text-emerald-400" : "bg-rose-500/15 text-rose-400"
                      )}
                    >
                      {row.is_active ? "active" : "suspended"}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-[#7A7E9C]">{row.agent_count}</td>
                  <td className="px-4 py-3 font-mono text-xs text-[#7A7E9C]">{row.conversation_count}</td>
                  <td className="px-4 py-3 font-mono text-xs text-[#7A7E9C]">{row.message_count}</td>
                  <td className="px-4 py-3 text-xs text-[#7A7E9C]">{new Date(row.created_at).toLocaleDateString()}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      {row.is_active ? (
                        <button
                          onClick={() => suspend.mutate(row.id)}
                          disabled={suspend.isPending}
                          className="flex items-center gap-1 text-xs text-[#7A7E9C] hover:text-rose-400"
                          title="Suspend"
                        >
                          <Ban className="h-3.5 w-3.5" />
                        </button>
                      ) : (
                        <button
                          onClick={() => reactivate.mutate(row.id)}
                          disabled={reactivate.isPending}
                          className="flex items-center gap-1 text-xs text-[#7A7E9C] hover:text-emerald-400"
                          title="Reactivate"
                        >
                          <CheckCircle2 className="h-3.5 w-3.5" />
                        </button>
                      )}
                      {!row.is_platform_admin && (
                        <button
                          onClick={() => promote.mutate(row.id)}
                          disabled={promote.isPending}
                          className="flex items-center gap-1 text-xs text-[#7A7E9C] hover:text-violet-400"
                          title="Promote to platform admin"
                        >
                          <ShieldPlus className="h-3.5 w-3.5" />
                        </button>
                      )}
                      {(suspend.isPending || reactivate.isPending || promote.isPending) && (
                        <Loader2 className="h-3.5 w-3.5 animate-spin text-[#7A7E9C]" />
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {!usersQuery.isLoading && users.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-6 text-center text-[#7A7E9C]">
                    No users found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function DarkStat({
  icon: Icon,
  color,
  label,
  value,
  deltaPct,
}: {
  icon: React.ElementType;
  color: string;
  label: string;
  value: string | undefined;
  deltaPct?: number;
}) {
  return (
    <div className="rounded-2xl border border-white/10 bg-[#12132B] p-4">
      <div className="mb-3 flex items-center justify-between">
        <span
          className="flex h-9 w-9 items-center justify-center rounded-xl"
          style={{ backgroundColor: `${color}22`, color }}
        >
          <Icon className="h-4 w-4" />
        </span>
        {deltaPct != null && (
          <span
            className={cn(
              "flex items-center gap-0.5 text-[11px] font-medium",
              deltaPct >= 0 ? "text-emerald-400" : "text-rose-400"
            )}
          >
            {deltaPct >= 0 ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
            {Math.abs(deltaPct)}%
          </span>
        )}
      </div>
      <p className="font-display text-xl font-semibold text-white tabular-nums">{value ?? "—"}</p>
      <p className="mt-1 text-xs text-[#7A7E9C]">{label}</p>
    </div>
  );
}

function QuickAction({
  to,
  icon: Icon,
  label,
  hint,
  disabled,
}: {
  to: string;
  icon: React.ElementType;
  label: string;
  hint?: string;
  disabled?: boolean;
}) {
  const content = (
    <span
      className={cn(
        "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-colors",
        disabled ? "cursor-not-allowed text-[#4B4F6B]" : "text-[#C6C8DA] hover:bg-white/5 hover:text-white"
      )}
      title={hint}
    >
      <Icon className="h-4 w-4 shrink-0" />
      <span className="flex-1">{label}</span>
      {hint && <span className="text-[10px] text-[#4B4F6B]">{hint}</span>}
    </span>
  );
  if (disabled) return content;
  return <Link to={to}>{content}</Link>;
}

function HealthRow({
  icon: Icon,
  label,
  ok,
  detail,
}: {
  icon: React.ElementType;
  label: string;
  ok: boolean | undefined;
  detail?: string;
}) {
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="flex items-center gap-2 text-[#C6C8DA]">
        <Icon className="h-3.5 w-3.5 text-[#7A7E9C]" />
        {label}
      </span>
      <span className={cn("flex items-center gap-1.5", ok ? "text-emerald-400" : "text-rose-400")}>
        <span className={cn("h-1.5 w-1.5 rounded-full", ok ? "bg-emerald-400" : "bg-rose-400")} />
        {detail ?? (ok ? "Operational" : "Issue detected")}
      </span>
    </div>
  );
}
