import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain, Trash2, Loader2, Plus } from "lucide-react";
import { toast } from "sonner";
import { api, apiErrorMessage } from "@/lib/api";
import type { MemoryEntry, MemoryType } from "@/types";
import { cn } from "@/lib/utils";

const TYPE_STYLES: Record<MemoryType, string> = {
  fact: "bg-accent-blue/15 text-accent-blue",
  preference: "bg-accent-violet/15 text-accent-violet",
  event: "bg-accent-amber/15 text-accent-amber",
  conversation_summary: "bg-accent-green/15 text-accent-green",
};

export default function MemoryPage() {
  const queryClient = useQueryClient();
  const [content, setContent] = useState("");
  const [memoryType, setMemoryType] = useState<MemoryType>("fact");

  const { data: memories = [], isLoading } = useQuery({
    queryKey: ["memory"],
    queryFn: async () => (await api.get<MemoryEntry[]>("/memory")).data,
  });

  const create = useMutation({
    mutationFn: async () => api.post("/memory", { memory_type: memoryType, content }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["memory"] });
      setContent("");
      toast.success("Memory added");
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  const remove = useMutation({
    mutationFn: async (id: string) => api.delete(`/memory/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["memory"] }),
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-xl font-semibold">Memory</h1>
        <p className="text-sm text-ink-muted">
          Facts, preferences, and events your agents remember. Use "Teach My AI" on the dashboard for the fast path -
          this is the full list.
        </p>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (content.trim()) create.mutate();
        }}
        className="panel flex items-center gap-3 p-3"
      >
        <select
          value={memoryType}
          onChange={(e) => setMemoryType(e.target.value as MemoryType)}
          className="shrink-0 rounded-lg border border-base-border bg-base-panel-2 px-2 py-2 text-xs text-ink focus:outline-none"
        >
          <option value="fact">Fact</option>
          <option value="preference">Preference</option>
          <option value="event">Event</option>
        </select>
        <input
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="e.g. Our office is now in Lagos"
          className="w-full bg-transparent text-sm text-ink placeholder:text-ink-faint focus:outline-none"
        />
        <button
          type="submit"
          disabled={create.isPending || !content.trim()}
          className="flex shrink-0 items-center gap-2 rounded-lg bg-gradient-to-r from-accent-violet to-accent-blue px-4 py-2 text-xs font-medium text-white hover:opacity-90 disabled:opacity-40"
        >
          {create.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
          Add
        </button>
      </form>

      <div className="panel divide-y divide-base-border">
        {isLoading && <p className="p-4 text-sm text-ink-faint">Loading…</p>}
        {!isLoading && memories.length === 0 && (
          <div className="flex flex-col items-center gap-2 p-10 text-center">
            <Brain className="h-6 w-6 text-ink-faint" />
            <p className="text-sm text-ink-muted">Nothing remembered yet.</p>
          </div>
        )}
        {memories.map((memory) => (
          <div key={memory.id} className="flex items-center justify-between gap-3 px-4 py-3">
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm text-ink">{memory.content}</p>
              <p className="text-xs text-ink-faint">
                {memory.source === "teach" ? "via Teach My AI" : memory.source}
              </p>
            </div>
            <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-[10px]", TYPE_STYLES[memory.memory_type])}>
              {memory.memory_type.replace("_", " ")}
            </span>
            <button
              onClick={() => remove.mutate(memory.id)}
              className="shrink-0 text-ink-faint hover:text-accent-pink"
              aria-label="Forget"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
