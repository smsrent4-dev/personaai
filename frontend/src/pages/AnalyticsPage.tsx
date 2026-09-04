import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart3, MessageSquare, Bot, BookOpen, Package } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { api } from "@/lib/api";
import type { AnalyticsSummary } from "@/types";

const RANGE_OPTIONS = [7, 14, 30, 90];

export default function AnalyticsPage() {
  const [days, setDays] = useState(30);

  const { data, isLoading } = useQuery({
    queryKey: ["analytics-summary", days],
    queryFn: async () => (await api.get<AnalyticsSummary>("/analytics/summary", { params: { days } })).data,
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-xl font-semibold text-ink">Analytics</h1>
          <p className="text-sm text-ink-muted">Real aggregates from your conversations, agents, and knowledge base.</p>
        </div>
        <select
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          className="rounded-xl border border-base-border bg-base-panel px-3 py-2 text-sm text-ink focus:outline-none"
        >
          {RANGE_OPTIONS.map((d) => (
            <option key={d} value={d}>
              Last {d} days
            </option>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <SummaryCard icon={MessageSquare} label="Total Conversations" value={data?.total_conversations} />
        <SummaryCard icon={BarChart3} label="Total Messages" value={data?.total_messages} />
        <SummaryCard icon={Bot} label="Active Agents" value={data?.active_agents} />
        <SummaryCard icon={BookOpen} label="Knowledge Docs Ready" value={data?.knowledge_documents_ready} />
      </div>

      <div className="panel p-5">
        <p className="mb-4 text-sm font-semibold text-ink">Messages per day</p>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data?.messages_per_day ?? []}>
              <CartesianGrid stroke="#232544" vertical={false} />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#6B6E89" }} axisLine={false} tickLine={false} tickFormatter={(d: string) => d.slice(5)} />
              <YAxis tick={{ fontSize: 11, fill: "#6B6E89" }} axisLine={false} tickLine={false} allowDecimals={false} />
              <Tooltip contentStyle={{ borderRadius: 12, border: "1px solid #232544", fontSize: 12, background: "#12132B", color: "#F4F4F8" }} />
              <Bar dataKey="count" name="Messages" fill="#8B5CF6" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        {!isLoading && (data?.messages_per_day?.length ?? 0) === 0 && (
          <p className="-mt-52 text-center text-xs text-ink-faint">No messages yet in this window.</p>
        )}
      </div>

      <div className="panel p-5">
        <p className="mb-4 text-sm font-semibold text-ink">Messages by agent</p>
        <div className="space-y-3">
          {(data?.messages_by_agent ?? []).length === 0 && <p className="text-xs text-ink-faint">No agent activity yet.</p>}
          {data?.messages_by_agent.map((row) => {
            const max = Math.max(...data.messages_by_agent.map((r) => r.message_count), 1);
            return (
              <div key={row.agent_id}>
                <div className="mb-1 flex items-center justify-between text-xs">
                  <span className="text-ink">{row.agent_name}</span>
                  <span className="tabular-nums text-ink-muted">{row.message_count}</span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-base-panel-2">
                  <div
                    className="h-full rounded-full bg-accent-violet"
                    style={{ width: `${Math.max(4, Math.round((row.message_count / max) * 100))}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="panel flex items-center gap-3 p-4">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent-blue/10 text-accent-blue">
          <Package className="h-4 w-4" />
        </span>
        <p className="text-sm text-ink-muted">
          <span className="font-semibold text-ink">{data?.active_products ?? 0}</span> active products your Sales
          Agent can currently search and recommend.
        </p>
      </div>
    </div>
  );
}

function SummaryCard({ icon: Icon, label, value }: { icon: React.ElementType; label: string; value?: number }) {
  return (
    <div className="panel p-5">
      <span className="mb-3 flex h-9 w-9 items-center justify-center rounded-xl bg-accent-violet/10 text-accent-violet">
        <Icon className="h-4 w-4" />
      </span>
      <p className="stat-value">{value ?? "—"}</p>
      <p className="mt-1 text-xs text-ink-muted">{label}</p>
    </div>
  );
}
