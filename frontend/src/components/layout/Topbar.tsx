import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Search,
  LogOut,
  Settings,
  ChevronDown,
  Gift,
  X,
} from "lucide-react";
import { useAuthStore } from "@/lib/auth-store";
import NotificationsBell from "./NotificationsBell";

const SEARCH_TARGETS: {
  label: string;
  to: string;
  keywords: string[];
}[] = [
  {
    label: "Conversations",
    to: "/conversations",
    keywords: ["conversation", "chat", "message"],
  },
  {
    label: "AI Agents",
    to: "/agents",
    keywords: ["agent", "ai", "bot"],
  },
  {
    label: "Knowledge Base",
    to: "/knowledge",
    keywords: ["knowledge", "document", "faq"],
  },
  {
    label: "Products",
    to: "/products",
    keywords: ["product", "inventory", "catalog"],
  },
  {
    label: "Orders",
    to: "/orders",
    keywords: ["order", "sale"],
  },
  {
    label: "Customers",
    to: "/customers",
    keywords: ["customer", "contact"],
  },
  {
    label: "Analytics",
    to: "/analytics",
    keywords: ["analytics", "stats", "report"],
  },
  {
    label: "Integrations",
    to: "/integrations",
    keywords: ["integration", "telegram", "whatsapp", "channel"],
  },
  {
    label: "Settings",
    to: "/settings",
    keywords: ["settings", "profile", "account"],
  },
];

export default function Topbar() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const navigate = useNavigate();

  const [query, setQuery] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [mobileSearchOpen, setMobileSearchOpen] = useState(false);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();

    if (!q) return [];

    return SEARCH_TARGETS.filter(
      (target) =>
        target.label.toLowerCase().includes(q) ||
        target.keywords.some((keyword) => keyword.includes(q))
    ).slice(0, 6);
  }, [query]);

  const initials = (user?.full_name ?? "?")
    .split(" ")
    .map((part) => part[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  function goTo(to: string) {
    setQuery("");
    setMobileSearchOpen(false);
    navigate(to);
  }

  function closeSearch() {
    setQuery("");
    setMobileSearchOpen(false);
  }

  return (
    <header className="relative z-30 flex h-16 shrink-0 items-center border-b border-base-border bg-base-panel px-4 sm:px-6 lg:px-8">
      <div className="flex min-w-0 flex-1 items-center">
        <div className="relative hidden w-full max-w-sm md:block">
          <div className="flex items-center gap-2 rounded-xl border border-base-border bg-base-panel-2 px-3 py-2">
            <Search className="h-4 w-4 shrink-0 text-ink-faint" />

            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && matches[0]) {
                  goTo(matches[0].to);
                }
              }}
              placeholder="Search anything…"
              className="w-full min-w-0 bg-transparent text-sm text-ink placeholder:text-ink-faint focus:outline-none"
            />

            <kbd className="hidden shrink-0 rounded border border-base-border px-1.5 py-0.5 font-mono text-[10px] text-ink-faint lg:block">
              ⌘K
            </kbd>
          </div>

          {matches.length > 0 && (
            <>
              <button
                type="button"
                aria-label="Close search results"
                onClick={() => setQuery("")}
                className="fixed inset-0 z-10 cursor-default"
              />

              <div className="absolute left-0 right-0 z-20 mt-1.5 overflow-hidden rounded-xl border border-base-border bg-base-panel shadow-card">
                {matches.map((match) => (
                  <button
                    key={match.to}
                    type="button"
                    onClick={() => goTo(match.to)}
                    className="block w-full px-3.5 py-2.5 text-left text-sm text-ink transition-colors hover:bg-base-panel-2"
                  >
                    {match.label}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>

        <button
          type="button"
          aria-label="Search"
          onClick={() => setMobileSearchOpen(true)}
          className="flex h-10 w-10 items-center justify-center rounded-xl border border-base-border bg-base-panel-2 text-ink-muted transition-colors hover:text-ink md:hidden"
        >
          <Search className="h-4 w-4" />
        </button>
      </div>

      <div className="flex shrink-0 items-center gap-2 sm:gap-3">
        <button
          type="button"
          title="Refer a business, earn credit — coming soon"
          className="hidden h-9 w-9 items-center justify-center rounded-xl border border-base-border bg-base-panel text-ink-muted transition-colors hover:text-ink sm:flex"
        >
          <Gift className="h-4 w-4" />
        </button>

        <NotificationsBell />

        <div className="relative">
          <button
            type="button"
            onClick={() => setMenuOpen((value) => !value)}
            className="flex h-10 items-center gap-1.5 rounded-xl border border-base-border bg-base-panel py-1 pl-1 pr-2 transition-colors hover:bg-base-panel-2"
            aria-expanded={menuOpen}
            aria-label="Account menu"
          >
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-violet/10 text-xs font-semibold text-accent-violet">
              {initials}
            </span>

            <ChevronDown className="hidden h-3.5 w-3.5 text-ink-faint sm:block" />
          </button>

          {menuOpen && (
            <>
              <button
                type="button"
                aria-label="Close account menu"
                onClick={() => setMenuOpen(false)}
                className="fixed inset-0 z-10 cursor-default"
              />

              <div className="absolute right-0 z-20 mt-2 w-[calc(100vw-32px)] max-w-52 overflow-hidden rounded-xl border border-base-border bg-base-panel shadow-card">
                <div className="border-b border-base-border px-3.5 py-3">
                  <p className="truncate text-sm font-medium text-ink">
                    {user?.full_name}
                  </p>

                  <p className="truncate text-xs text-ink-faint">
                    {user?.email}
                  </p>
                </div>

                <button
                  type="button"
                  onClick={() => {
                    setMenuOpen(false);
                    navigate("/settings");
                  }}
                  className="flex w-full items-center gap-2 px-3.5 py-2.5 text-left text-sm text-ink-muted transition-colors hover:bg-base-panel-2 hover:text-ink"
                >
                  <Settings className="h-3.5 w-3.5" />
                  Settings
                </button>

                <button
                  type="button"
                  onClick={() => {
                    logout();
                    navigate("/login");
                  }}
                  className="flex w-full items-center gap-2 px-3.5 py-2.5 text-left text-sm text-accent-pink transition-colors hover:bg-accent-pink/5"
                >
                  <LogOut className="h-3.5 w-3.5" />
                  Sign out
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      {mobileSearchOpen && (
        <div className="absolute inset-0 flex items-center gap-2 bg-base-panel px-4 md:hidden">
          <button
            type="button"
            onClick={closeSearch}
            aria-label="Close search"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-ink-muted hover:bg-base-panel-2 hover:text-ink"
          >
            <X className="h-5 w-5" />
          </button>

          <div className="relative min-w-0 flex-1">
            <div className="flex items-center gap-2 rounded-xl border border-base-border bg-base-panel-2 px-3 py-2">
              <Search className="h-4 w-4 shrink-0 text-ink-faint" />

              <input
                autoFocus
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && matches[0]) {
                    goTo(matches[0].to);
                  }
                }}
                placeholder="Search…"
                className="w-full min-w-0 bg-transparent text-sm text-ink placeholder:text-ink-faint focus:outline-none"
              />
            </div>

            {matches.length > 0 && (
              <div className="absolute left-0 right-0 top-full z-50 mt-1.5 overflow-hidden rounded-xl border border-base-border bg-base-panel shadow-card">
                {matches.map((match) => (
                  <button
                    key={match.to}
                    type="button"
                    onClick={() => goTo(match.to)}
                    className="block w-full px-3.5 py-3 text-left text-sm text-ink transition-colors hover:bg-base-panel-2"
                  >
                    {match.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </header>
  );
}