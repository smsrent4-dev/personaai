import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  MessageSquare,
  Search,
  Inbox,
  Clock3,
  CheckCircle2,
  Bot,
  ChevronRight,
  RefreshCw,
  Sparkles,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { api } from "@/lib/api";
import type { Conversation, Platform } from "@/types";
import PlatformBadge from "@/components/PlatformBadge";

type ChannelFilter = "all" | Platform;

export default function ConversationsPage() {
  const [filter, setFilter] =
    useState<ChannelFilter>("all");

  const [search, setSearch] = useState("");

  const {
    data: conversations = [],
    isLoading,
    isError,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ["conversations"],
    queryFn: async () =>
      (
        await api.get<Conversation[]>(
          "/conversations",
        )
      ).data,
  });

  const availablePlatforms = useMemo(
    () =>
      Array.from(
        new Set(
          conversations.map(
            (conversation) =>
              conversation.platform,
          ),
        ),
      ) as Platform[],
    [conversations],
  );

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();

    return conversations.filter((conversation) => {
      const matchesPlatform =
        filter === "all" ||
        conversation.platform === filter;

      if (!matchesPlatform) {
        return false;
      }

      if (!query) {
        return true;
      }

      const name =
        conversation.external_user_name ??
        "";

      const externalId =
        conversation.external_conversation_id ??
        "";

      const platform =
        conversation.platform ?? "";

      const status =
        conversation.status ?? "";

      return (
        name.toLowerCase().includes(query) ||
        externalId.toLowerCase().includes(query) ||
        platform.toLowerCase().includes(query) ||
        status.toLowerCase().includes(query)
      );
    });
  }, [
    conversations,
    filter,
    search,
  ]);

  const activeCount = conversations.filter(
    (conversation) =>
      conversation.status === "active" ||
      conversation.status === "open",
  ).length;

  const waitingCount = conversations.filter(
    (conversation) =>
      conversation.status === "waiting" ||
      conversation.status === "pending",
  ).length;

  const platformCount =
    availablePlatforms.length;

  const clearSearch = () => {
    setSearch("");
  };

  return (
    <div className="relative mx-auto w-full max-w-[1600px] space-y-5 pb-8 sm:space-y-6">
      {/* Ambient background */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-20 -top-24 -z-10 h-72 w-72 rounded-full bg-accent-violet/10 blur-3xl"
      />

      <div
        aria-hidden="true"
        className="pointer-events-none absolute left-0 top-72 -z-10 h-64 w-64 rounded-full bg-accent-blue/5 blur-3xl"
      />

      {/* ------------------------------------------------------------------ */}
      {/* Header                                                              */}
      {/* ------------------------------------------------------------------ */}

      <section className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <div className="mb-2 flex items-center gap-2">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-accent-violet/20 to-accent-blue/20 ring-1 ring-white/5">
              <MessageSquare className="h-4 w-4 text-accent-violet" />
            </div>

            <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-ink-faint">
              Unified inbox
            </span>
          </div>

          <h1 className="font-display text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
            Conversations
          </h1>

          <p className="mt-1.5 max-w-2xl text-sm leading-6 text-ink-muted">
            Every customer conversation across your
            connected platforms, organized in one place.
          </p>
        </div>

        <button
          type="button"
          onClick={() => refetch()}
          disabled={isFetching}
          className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-base-border bg-base-panel-2 px-4 py-2.5 text-xs font-medium text-ink transition-all duration-200 hover:-translate-y-0.5 hover:bg-base-border disabled:cursor-not-allowed disabled:opacity-60 sm:w-auto"
        >
          <RefreshCw
            className={`h-3.5 w-3.5 ${
              isFetching
                ? "animate-spin"
                : ""
            }`}
          />

          Refresh
        </button>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* Stats                                                               */}
      {/* ------------------------------------------------------------------ */}

      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          icon={Inbox}
          label="Total conversations"
          value={conversations.length}
          accent="violet"
        />

        <StatCard
          icon={CheckCircle2}
          label="Active"
          value={activeCount}
          accent="green"
        />

        <StatCard
          icon={Clock3}
          label="Waiting"
          value={waitingCount}
          accent="amber"
        />

        <StatCard
          icon={Bot}
          label="Connected channels"
          value={platformCount}
          accent="blue"
        />
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* Main inbox                                                          */}
      {/* ------------------------------------------------------------------ */}

      <section className="panel overflow-hidden">
        {/* Toolbar */}
        <div className="border-b border-base-border p-3 sm:p-4">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
            {/* Search */}
            <div className="relative min-w-0 flex-1 xl:max-w-xl">
              <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />

              <input
                value={search}
                onChange={(event) =>
                  setSearch(event.target.value)
                }
                placeholder="Search conversations..."
                className="h-11 w-full rounded-xl border border-base-border bg-base-panel-2 pl-10 pr-10 text-sm text-ink outline-none transition-all duration-200 placeholder:text-ink-faint focus:border-accent-violet/50 focus:ring-2 focus:ring-accent-violet/10"
              />

              {search && (
                <button
                  type="button"
                  onClick={clearSearch}
                  aria-label="Clear search"
                  className="absolute right-2.5 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-lg text-ink-faint transition-colors hover:bg-base-border hover:text-ink"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>

            {/* Channel filters */}
            <div className="flex min-w-0 items-center gap-2 overflow-x-auto pb-0.5 scrollbar-none">
              <div className="mr-1 flex h-9 shrink-0 items-center justify-center rounded-lg bg-base-panel-2 px-2.5">
                <SlidersHorizontal className="h-3.5 w-3.5 text-ink-faint" />
              </div>

              <FilterButton
                active={filter === "all"}
                onClick={() =>
                  setFilter("all")
                }
              >
                All
              </FilterButton>

              {availablePlatforms.map(
                (platform) => (
                  <FilterButton
                    key={platform}
                    active={
                      filter === platform
                    }
                    onClick={() =>
                      setFilter(platform)
                    }
                  >
                    <PlatformBadge
                      platform={platform}
                    />
                    <span className="capitalize">
                      {platform}
                    </span>
                  </FilterButton>
                ),
              )}
            </div>
          </div>

          {/* Result count */}
          <div className="mt-3 flex items-center justify-between gap-3">
            <p className="text-[11px] text-ink-faint">
              Showing{" "}
              <span className="font-medium text-ink-muted">
                {filtered.length}
              </span>{" "}
              {filtered.length === 1
                ? "conversation"
                : "conversations"}
            </p>

            {(search ||
              filter !== "all") && (
              <button
                type="button"
                onClick={() => {
                  setSearch("");
                  setFilter("all");
                }}
                className="text-[11px] font-medium text-accent-violet transition-colors hover:text-accent-blue"
              >
                Clear filters
              </button>
            )}
          </div>
        </div>

        {/* Loading */}
        {isLoading && (
          <ConversationSkeletonList />
        )}

        {/* Error */}
        {!isLoading && isError && (
          <ErrorState
            onRetry={() => refetch()}
          />
        )}

        {/* Empty */}
        {!isLoading &&
          !isError &&
          conversations.length === 0 && (
            <EmptyConversationsState />
          )}

        {/* Search empty */}
        {!isLoading &&
          !isError &&
          conversations.length > 0 &&
          filtered.length === 0 && (
            <NoResultsState
              onClear={() => {
                setSearch("");
                setFilter("all");
              }}
            />
          )}

        {/* Conversation list */}
        {!isLoading &&
          !isError &&
          filtered.length > 0 && (
            <div className="divide-y divide-base-border">
              {filtered.map(
                (conversation, index) => (
                  <ConversationRow
                    key={conversation.id}
                    conversation={conversation}
                    index={index}
                  />
                ),
              )}
            </div>
          )}
      </section>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Stat Card                                                                  */
/* -------------------------------------------------------------------------- */

function StatCard({
  icon: Icon,
  label,
  value,
  accent,
}: {
  icon: typeof Inbox;
  label: string;
  value: number;
  accent:
    | "violet"
    | "green"
    | "amber"
    | "blue";
}) {
  const styles = {
    violet:
      "bg-accent-violet/10 text-accent-violet ring-accent-violet/20",
    green:
      "bg-accent-green/10 text-accent-green ring-accent-green/20",
    amber:
      "bg-accent-amber/10 text-accent-amber ring-accent-amber/20",
    blue:
      "bg-accent-blue/10 text-accent-blue ring-accent-blue/20",
  };

  return (
    <div className="group relative overflow-hidden rounded-2xl border border-base-border bg-base-panel p-3.5 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-lg sm:p-4">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-8 -top-8 h-20 w-20 rounded-full bg-accent-violet/5 blur-2xl transition-transform duration-500 group-hover:scale-150"
      />

      <div className="relative flex items-center gap-3">
        <div
          className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ring-1 ${styles[accent]}`}
        >
          <Icon className="h-4 w-4" />
        </div>

        <div className="min-w-0">
          <p className="truncate text-[10px] font-medium uppercase tracking-wider text-ink-faint">
            {label}
          </p>

          <p className="mt-0.5 font-display text-lg font-semibold text-ink">
            {value}
          </p>
        </div>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Filter Button                                                              */
/* -------------------------------------------------------------------------- */

function FilterButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex h-9 shrink-0 items-center gap-1.5 rounded-lg px-3 text-xs font-medium transition-all duration-200 ${
        active
          ? "bg-base-panel-2 text-ink shadow-sm ring-1 ring-base-border"
          : "text-ink-faint hover:bg-base-panel-2 hover:text-ink"
      }`}
    >
      {children}
    </button>
  );
}

/* -------------------------------------------------------------------------- */
/* Conversation Row                                                           */
/* -------------------------------------------------------------------------- */

function ConversationRow({
  conversation,
  index,
}: {
  conversation: Conversation;
  index: number;
}) {
  const displayName =
    conversation.external_user_name?.trim() ||
    conversation.external_conversation_id;

  const initial =
    displayName?.charAt(0)?.toUpperCase() ||
    "?";

  const status =
    conversation.status?.toLowerCase() ||
    "unknown";

  const isActive =
    status === "active" ||
    status === "open";

  const isWaiting =
    status === "waiting" ||
    status === "pending";

  return (
    <Link
      to={`/conversations/${conversation.id}`}
      className="group relative block overflow-hidden px-3 py-3.5 transition-all duration-300 hover:bg-white/[0.025] sm:px-4 lg:px-5"
      style={{
        animationDelay: `${Math.min(
          index * 35,
          300,
        )}ms`,
      }}
    >
      {/* Active hover indicator */}
      <div className="absolute bottom-0 left-0 top-0 w-0.5 origin-bottom scale-y-0 bg-gradient-to-b from-accent-violet to-accent-blue transition-transform duration-300 group-hover:scale-y-100" />

      <div className="flex items-center gap-3 sm:gap-4">
        {/* Avatar */}
        <div className="relative shrink-0">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-accent-violet/15 to-accent-blue/10 text-sm font-semibold text-ink ring-1 ring-base-border transition-all duration-300 group-hover:scale-105 group-hover:ring-accent-violet/30 sm:h-12 sm:w-12">
            {initial}
          </div>

          {/* Online/status dot */}
          <span
            className={`absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-base-panel ${
              isActive
                ? "bg-accent-green"
                : isWaiting
                  ? "bg-accent-amber"
                  : "bg-ink-faint"
            }`}
          />

          {isActive && (
            <span className="absolute -bottom-0.5 -right-0.5 h-3 w-3 animate-ping rounded-full bg-accent-green/40 motion-reduce:hidden" />
          )}
        </div>

        {/* Main content */}
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-ink transition-colors group-hover:text-white">
                {displayName}
              </p>

              <div className="mt-1.5 flex min-w-0 items-center gap-2">
                <PlatformBadge
                  platform={
                    conversation.platform
                  }
                />

                <span className="hidden truncate text-[10px] text-ink-faint sm:inline">
                  {conversation.external_conversation_id}
                </span>
              </div>
            </div>

            {/* Time */}
            {conversation.last_message_at && (
              <span className="shrink-0 whitespace-nowrap text-[10px] font-medium text-ink-faint sm:text-[11px]">
                {formatDistanceToNow(
                  new Date(
                    conversation.last_message_at,
                  ),
                  {
                    addSuffix: true,
                  },
                )}
              </span>
            )}
          </div>

          {/* Bottom metadata */}
          <div className="mt-2 flex items-center gap-2">
            <StatusBadge
              status={status}
            />

            <span className="h-1 w-1 shrink-0 rounded-full bg-ink-faint/50" />

            <span className="truncate text-[10px] capitalize text-ink-faint">
              {conversation.platform}
            </span>
          </div>
        </div>

        {/* Arrow */}
        <div className="hidden shrink-0 sm:flex">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg text-ink-faint transition-all duration-300 group-hover:translate-x-0.5 group-hover:bg-base-panel-2 group-hover:text-ink">
            <ChevronRight className="h-4 w-4" />
          </div>
        </div>
      </div>
    </Link>
  );
}

/* -------------------------------------------------------------------------- */
/* Status Badge                                                               */
/* -------------------------------------------------------------------------- */

function StatusBadge({
  status,
}: {
  status: string;
}) {
  const normalized =
    status.toLowerCase();

  const isActive =
    normalized === "active" ||
    normalized === "open";

  const isWaiting =
    normalized === "waiting" ||
    normalized === "pending";

  let className =
    "bg-ink-faint/10 text-ink-faint ring-ink-faint/10";

  if (isActive) {
    className =
      "bg-accent-green/10 text-accent-green ring-accent-green/15";
  } else if (isWaiting) {
    className =
      "bg-accent-amber/10 text-accent-amber ring-accent-amber/15";
  }

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[9px] font-semibold capitalize ring-1 ${className}`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${
          isActive
            ? "bg-accent-green"
            : isWaiting
              ? "bg-accent-amber"
              : "bg-ink-faint"
        }`}
      />

      {status}
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/* Loading Skeleton                                                           */
/* -------------------------------------------------------------------------- */

function ConversationSkeletonList() {
  return (
    <div className="divide-y divide-base-border">
      {Array.from({ length: 7 }).map(
        (_, index) => (
          <div
            key={index}
            className="flex animate-pulse items-center gap-3 px-3 py-4 sm:gap-4 sm:px-5"
          >
            <div className="h-11 w-11 shrink-0 rounded-2xl bg-base-panel-2 sm:h-12 sm:w-12" />

            <div className="min-w-0 flex-1 space-y-2">
              <div className="h-3.5 w-36 rounded bg-base-panel-2" />

              <div className="h-2.5 w-52 max-w-[70%] rounded bg-base-panel-2" />

              <div className="h-2.5 w-20 rounded bg-base-panel-2" />
            </div>

            <div className="hidden h-3 w-16 rounded bg-base-panel-2 sm:block" />
          </div>
        ),
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Error State                                                                */
/* -------------------------------------------------------------------------- */

function ErrorState({
  onRetry,
}: {
  onRetry: () => void;
}) {
  return (
    <div className="flex min-h-[360px] flex-col items-center justify-center px-5 py-12 text-center">
      <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-accent-red/10 ring-1 ring-accent-red/10">
        <MessageSquare className="h-6 w-6 text-accent-red" />
      </div>

      <h3 className="text-sm font-semibold text-ink">
        Couldn't load conversations
      </h3>

      <p className="mt-1.5 max-w-sm text-xs leading-5 text-ink-muted">
        We couldn't retrieve your inbox right now.
        Check your connection and try again.
      </p>

      <button
        type="button"
        onClick={onRetry}
        className="mt-5 inline-flex items-center gap-2 rounded-xl bg-base-panel-2 px-4 py-2.5 text-xs font-semibold text-ink transition-all hover:bg-base-border"
      >
        <RefreshCw className="h-3.5 w-3.5" />
        Try again
      </button>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Empty State                                                                */
/* -------------------------------------------------------------------------- */

function EmptyConversationsState() {
  return (
    <div className="relative flex min-h-[430px] flex-col items-center justify-center overflow-hidden px-5 py-14 text-center">
      {/* Ambient glow */}
      <div
        aria-hidden="true"
        className="absolute left-1/2 top-1/2 h-48 w-48 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent-violet/10 blur-3xl"
      />

      {/* 3D AI Core */}
      <div className="relative mb-7 h-28 w-28 [perspective:700px]">
        {/* Outer glow */}
        <div className="absolute inset-5 animate-pulse rounded-full bg-accent-violet/20 blur-xl motion-reduce:animate-none" />

        {/* Sphere */}
        <div className="absolute inset-5 rounded-full bg-gradient-to-br from-accent-violet/30 via-accent-blue/15 to-transparent shadow-[inset_0_0_25px_rgba(139,92,246,0.15),0_0_40px_rgba(99,102,241,0.12)]">
          <div className="absolute inset-2 rounded-full border border-white/5 bg-base-panel-2/80">
            <Bot className="absolute left-1/2 top-1/2 h-7 w-7 -translate-x-1/2 -translate-y-1/2 text-accent-violet" />
          </div>
        </div>

        {/* X ring */}
        <div className="absolute inset-1 [transform:rotateX(65deg)]">
          <div className="h-full w-full animate-spin rounded-full border border-accent-violet/20 border-l-transparent border-r-transparent motion-reduce:animate-none" />
        </div>

        {/* Y ring */}
        <div className="absolute inset-1 [transform:rotateY(65deg)]">
          <div className="h-full w-full animate-[spin_8s_linear_infinite_reverse] rounded-full border border-accent-blue/20 border-t-transparent border-b-transparent motion-reduce:animate-none" />
        </div>

        {/* Orbit dot */}
        <span className="absolute left-1/2 top-0 h-2 w-2 -translate-x-1/2 rounded-full bg-accent-violet shadow-[0_0_12px_rgba(139,92,246,0.7)]" />
      </div>

      <div className="relative">
        <div className="mb-2 flex items-center justify-center gap-1.5">
          <Sparkles className="h-3.5 w-3.5 text-accent-violet" />

          <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-accent-violet">
            PersonaAI Inbox
          </span>
        </div>

        <h3 className="font-display text-base font-semibold text-ink sm:text-lg">
          No conversations yet
        </h3>

        <p className="mx-auto mt-1.5 max-w-md text-xs leading-5 text-ink-muted">
          Once your connected platforms start
          receiving customer messages, they'll appear
          here automatically.
        </p>

        <Link
          to="/integrations"
          className="mt-5 inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-accent-violet to-accent-blue px-4 py-2.5 text-xs font-semibold text-white shadow-lg shadow-accent-violet/10 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-xl hover:shadow-accent-violet/20"
        >
          Connect a platform
          <ChevronRight className="h-3.5 w-3.5" />
        </Link>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* No Results                                                                 */
/* -------------------------------------------------------------------------- */

function NoResultsState({
  onClear,
}: {
  onClear: () => void;
}) {
  return (
    <div className="flex min-h-[320px] flex-col items-center justify-center px-5 py-12 text-center">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-base-panel-2">
        <Search className="h-5 w-5 text-ink-faint" />
      </div>

      <h3 className="text-sm font-semibold text-ink">
        No matching conversations
      </h3>

      <p className="mt-1.5 max-w-sm text-xs leading-5 text-ink-muted">
        Try another name, conversation ID, platform,
        or clear your filters.
      </p>

      <button
        type="button"
        onClick={onClear}
        className="mt-4 rounded-xl bg-base-panel-2 px-4 py-2.5 text-xs font-semibold text-ink transition-all hover:bg-base-border"
      >
        Clear filters
      </button>
    </div>
  );
}
