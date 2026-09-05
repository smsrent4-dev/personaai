import { Fragment, useState } from "react";
import { NavLink, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  LayoutGrid,
  MessageSquare,
  Bot,
  BookOpen,
  Package,
  ShoppingBag,
  Users,
  Workflow,
  BarChart3,
  Plug,
  Settings,
  Shield,
  Sparkles,
  ChevronDown,
  Menu,
  X,
} from "lucide-react";
import { useAuthStore } from "@/lib/auth-store";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  Conversation,
  Order,
  BillingPlan,
  Subscription,
  AnalyticsSummary,
} from "@/types";

const NAV_ITEMS = [
  { to: "/", label: "Overview", icon: LayoutGrid, end: true },
  {
    to: "/conversations",
    label: "Conversations",
    icon: MessageSquare,
    countFrom: "conversations" as const,
  },
  { to: "/agents", label: "AI Agents", icon: Bot },
  { to: "/knowledge", label: "Knowledge Base", icon: BookOpen },
  { to: "/products", label: "Products", icon: Package },
  {
    to: "/orders",
    label: "Orders",
    icon: ShoppingBag,
    countFrom: "orders" as const,
  },
  { to: "/customers", label: "Customers", icon: Users },
  { to: "/training", label: "Workflows", icon: Workflow },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
  { to: "/integrations", label: "Integrations", icon: Plug },
  { to: "/settings", label: "Settings", icon: Settings },
];

export default function Sidebar() {
  const [mobileOpen, setMobileOpen] = useState(false);

  const user = useAuthStore((s) => s.user);

  const conversationsQuery = useQuery({
    queryKey: ["conversations"],
    queryFn: async () =>
      (await api.get<Conversation[]>("/conversations")).data,
  });

  const ordersQuery = useQuery({
    queryKey: ["orders"],
    queryFn: async () => (await api.get<Order[]>("/orders")).data,
  });

  const analyticsQuery = useQuery({
    queryKey: ["analytics-summary", 30],
    queryFn: async () =>
      (
        await api.get<AnalyticsSummary>("/analytics/summary", {
          params: { days: 30 },
        })
      ).data,
  });

  const subscriptionQuery = useQuery({
    queryKey: ["billing-subscription"],
    queryFn: async () =>
      (await api.get<Subscription | null>("/billing/subscription")).data,
  });

  const plansQuery = useQuery({
    queryKey: ["billing-plans"],
    queryFn: async () =>
      (await api.get<BillingPlan[]>("/billing/plans")).data,
  });

  const counts: Record<string, number> = {
    conversations:
      conversationsQuery.data?.filter((c) => c.status === "open").length ?? 0,
    orders:
      ordersQuery.data?.filter(
        (o) => o.status === "pending" || o.status === "confirmed"
      ).length ?? 0,
  };

  const currentPlan = plansQuery.data?.find(
    (p) => p.id === subscriptionQuery.data?.plan_id
  );

  const messagesThisMonth = analyticsQuery.data?.total_messages ?? 0;
  const messageLimit = currentPlan?.max_messages_per_month ?? null;

  const usagePct = messageLimit
    ? Math.min(
        100,
        Math.round((messagesThisMonth / messageLimit) * 100)
      )
    : null;

  const initials = (user?.full_name ?? "?")
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  const closeMobileMenu = () => {
    setMobileOpen(false);
  };

  const navigation = (
    <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-1 scrollbar-thin">
      {NAV_ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          onClick={closeMobileMenu}
        >
          {({ isActive }) => (
            <span
              className={cn(
                "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-colors",
                isActive
                  ? "bg-accent-violet text-white"
                  : "text-nav-text hover:bg-white/5 hover:text-white"
              )}
            >
              <item.icon className="h-4 w-4 shrink-0" />

              <span className="min-w-0 flex-1 truncate">
                {item.label}
              </span>

              {item.countFrom && counts[item.countFrom] > 0 && (
                <span
                  className={cn(
                    "shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium tabular-nums",
                    isActive
                      ? "bg-white/20 text-white"
                      : "bg-white/10 text-nav-muted"
                  )}
                >
                  {counts[item.countFrom]}
                </span>
              )}
            </span>
          )}
        </NavLink>
      ))}

      {user?.is_platform_admin && (
        <>
          <div className="my-2 border-t border-nav-border" />

          <NavLink
            to="/admin"
            onClick={closeMobileMenu}
          >
            {({ isActive }) => (
              <span
                className={cn(
                  "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-colors",
                  isActive
                    ? "bg-accent-violet text-white"
                    : "text-nav-text hover:bg-white/5 hover:text-white"
                )}
              >
                <Shield className="h-4 w-4 shrink-0" />
                <span className="flex-1">Admin</span>
              </span>
            )}
          </NavLink>
        </>
      )}
    </nav>
  );

  const sidebarContent = (
    <>
      <div className="flex h-16 shrink-0 items-center justify-between px-5 lg:h-auto lg:py-5">
        <Link
          to="/"
          onClick={closeMobileMenu}
          className="flex items-center gap-2"
        >
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-violet">
            <Sparkles className="h-4 w-4 text-white" />
          </div>

          <span className="font-display text-lg font-semibold tracking-tight text-white">
            PersonaAI
          </span>
        </Link>

        <button
          type="button"
          onClick={closeMobileMenu}
          aria-label="Close navigation"
          className="flex h-9 w-9 items-center justify-center rounded-lg text-nav-muted transition-colors hover:bg-white/5 hover:text-white lg:hidden"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      {user && (
        <div className="mx-4 mb-4 flex shrink-0 items-center gap-3 rounded-xl bg-nav-panel p-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent-violet/30 font-display text-xs font-semibold text-white">
            {initials}
          </div>

          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-white">
              {user.business_name ?? user.full_name}
            </p>

            <span className="mt-0.5 inline-flex items-center rounded-md bg-accent-violet/20 px-1.5 py-0.5 text-[10px] font-medium text-accent-violet">
              {user.role === "owner" ? "Business" : user.role}
            </span>
          </div>

          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-nav-muted" />
        </div>
      )}

      {navigation}

      <div className="shrink-0">
        {usagePct !== null && (
          <div className="mx-3 mb-3 rounded-xl bg-nav-panel p-3">
            <div className="mb-2 flex items-center justify-between gap-2 text-xs">
              <span className="min-w-0 truncate text-nav-muted">
                AI Usage This Month
              </span>

              <span className="shrink-0 font-medium text-white">
                {usagePct}%
              </span>
            </div>

            <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/10">
              <div
                className={cn(
                  "h-full rounded-full",
                  usagePct >= 90
                    ? "bg-accent-pink"
                    : "bg-accent-violet"
                )}
                style={{ width: `${usagePct}%` }}
              />
            </div>

            <p className="mt-1.5 text-[11px] tabular-nums text-nav-muted">
              {messagesThisMonth.toLocaleString()} /{" "}
              {messageLimit!.toLocaleString()} messages
            </p>
          </div>
        )}

        <div className="mx-3 mb-3 rounded-xl bg-nav-panel p-3">
          <p className="text-xs text-nav-muted">Current Plan</p>

          <p className="mb-2.5 truncate text-sm font-semibold text-white">
            {currentPlan?.name ?? "No active plan"}
          </p>

          <Link
            to="/billing"
            onClick={closeMobileMenu}
            className="block w-full rounded-lg bg-white/10 py-1.5 text-center text-xs font-medium text-white transition-colors hover:bg-white/15"
          >
            Manage Plan
          </Link>
        </div>

        {user && (
          <Link
            to="/settings"
            onClick={closeMobileMenu}
            className="flex items-center gap-3 border-t border-nav-border px-4 py-3 transition-colors hover:bg-white/5"
          >
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-violet/30 text-[11px] font-semibold text-white">
              {initials}
            </div>

            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium text-white">
                {user.full_name}
              </p>

              <p className="truncate text-[11px] text-nav-muted">
                {user.email}
              </p>
            </div>
          </Link>
        )}
      </div>
    </>
  );

  return (
    <Fragment>
      <button
        type="button"
        onClick={() => setMobileOpen(true)}
        aria-label="Open navigation"
        className="fixed left-4 top-4 z-40 flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-nav-bg/95 text-white shadow-lg backdrop-blur lg:hidden"
      >
        <Menu className="h-5 w-5" />
      </button>

      {mobileOpen && (
        <button
          type="button"
          aria-label="Close navigation overlay"
          onClick={closeMobileMenu}
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-[2px] lg:hidden"
        />
      )}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex w-[min(82vw,320px)] flex-col overflow-hidden bg-nav-bg text-nav-text shadow-2xl transition-transform duration-300 ease-out",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
          "lg:static lg:z-auto lg:h-screen lg:w-64 lg:shrink-0 lg:translate-x-0 lg:shadow-none"
        )}
      >
        {sidebarContent}
      </aside>
    </Fragment>
  );
}