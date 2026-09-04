import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search, LogOut, Settings, ChevronDown, Gift } from "lucide-react";
import { useAuthStore } from "@/lib/auth-store";
import NotificationsBell from "./NotificationsBell";

const SEARCH_TARGETS: { label: string; to: string; keywords: string[] }[] = [
  { label: "Conversations", to: "/conversations", keywords: ["conversation", "chat", "message"] },
  { label: "AI Agents", to: "/agents", keywords: ["agent", "ai", "bot"] },
  { label: "Knowledge Base", to: "/knowledge", keywords: ["knowledge", "document", "faq"] },
  { label: "Products", to: "/products", keywords: ["product", "inventory", "catalog"] },
  { label: "Orders", to: "/orders", keywords: ["order", "sale"] },
  { label: "Customers", to: "/customers", keywords: ["customer", "contact"] },
  { label: "Analytics", to: "/analytics", keywords: ["analytics", "stats", "report"] },
  { label: "Integrations", to: "/integrations", keywords: ["integration", "telegram", "whatsapp", "channel"] },
  { label: "Settings", to: "/settings", keywords: ["settings", "profile", "account"] },
];

export default function Topbar() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return SEARCH_TARGETS.filter(
      (t) => t.label.toLowerCase().includes(q) || t.keywords.some((k) => k.includes(q))
    ).slice(0, 6);
  }, [query]);

  const initials = (user?.full_name ?? "?")
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  function goTo(to: string) {
    setQuery("");
    navigate(to);
  }

  return (
    <header className="flex h-16 shrink-0 items-center justify-between border-b border-base-border bg-base-panel px-8">
      <div className="relative w-full max-w-sm">
        <div className="flex items-center gap-2 rounded-xl border border-base-border bg-base-panel-2 px-3 py-2">
          <Search className="h-4 w-4 text-ink-faint" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && matches[0] && goTo(matches[0].to)}
            placeholder="Search anything…"
            className="w-full bg-transparent text-sm text-ink placeholder:text-ink-faint focus:outline-none"
          />
          <kbd className="rounded border border-base-border px-1.5 py-0.5 font-mono text-[10px] text-ink-faint">⌘K</kbd>
        </div>
        {matches.length > 0 && (
          <>
            <div className="fixed inset-0 z-10" onClick={() => setQuery("")} />
            <div className="absolute left-0 right-0 z-20 mt-1.5 overflow-hidden rounded-xl border border-base-border bg-base-panel shadow-card">
              {matches.map((m) => (
                <button
                  key={m.to}
                  onClick={() => goTo(m.to)}
                  className="block w-full px-3.5 py-2.5 text-left text-sm text-ink transition-colors hover:bg-base-panel-2"
                >
                  {m.label}
                </button>
              ))}
            </div>
          </>
        )}
      </div>

      <div className="flex items-center gap-3">
        <button
          title="Refer a business, earn credit — coming soon"
          className="flex h-9 w-9 items-center justify-center rounded-xl border border-base-border bg-base-panel text-ink-muted transition-colors hover:text-ink"
        >
          <Gift className="h-4 w-4" />
        </button>

        <NotificationsBell />

        <div className="relative">
          <button
            onClick={() => setMenuOpen((v) => !v)}
            className="flex items-center gap-2 rounded-xl border border-base-border bg-base-panel py-1 pl-1 pr-2 transition-colors hover:bg-base-panel-2"
          >
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-accent-violet/10 text-xs font-semibold text-accent-violet">
              {initials}
            </span>
            <ChevronDown className="h-3.5 w-3.5 text-ink-faint" />
          </button>

          {menuOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
              <div className="absolute right-0 z-20 mt-2 w-52 overflow-hidden rounded-xl border border-base-border bg-base-panel shadow-card">
                <div className="border-b border-base-border px-3.5 py-3">
                  <p className="truncate text-sm font-medium text-ink">{user?.full_name}</p>
                  <p className="truncate text-xs text-ink-faint">{user?.email}</p>
                </div>
                <button
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
    </header>
  );
}
