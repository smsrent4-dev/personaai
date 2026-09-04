import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Loader2, X } from "lucide-react";
import { toast } from "sonner";
import { api, apiErrorMessage } from "@/lib/api";
import type { Agent, AgentType } from "@/types";
import { agentVisual } from "@/components/dashboard/agent-visuals";

const AGENT_TYPES: AgentType[] = ["personal", "sales", "support", "opportunity", "custom"];

export default function AgentsPage() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);

  const { data: agents = [], isLoading } = useQuery({
    queryKey: ["agents"],
    queryFn: async () => (await api.get<Agent[]>("/agents")).data,
  });

  const updateStatus = useMutation({
    mutationFn: async ({ id, status }: { id: string; status: Agent["status"] }) =>
      api.patch(`/agents/${id}`, { status }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["agents"] }),
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  const deleteAgent = useMutation({
    mutationFn: async (id: string) => api.delete(`/agents/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      toast.success("Agent deleted");
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-xl font-semibold">Agents</h1>
          <p className="text-sm text-ink-muted">Your AI team - each one has its own role, tone, and knowledge.</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-accent-violet to-accent-blue px-4 py-2 text-sm font-medium text-white hover:opacity-90"
        >
          <Plus className="h-4 w-4" />
          New Agent
        </button>
      </div>

      {isLoading ? (
        <Loader2 className="h-6 w-6 animate-spin text-ink-faint" />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {agents.map((agent) => {
            const visual = agentVisual(agent.agent_type);
            const Icon = visual.icon;
            return (
              <div key={agent.id} className="panel space-y-3 p-4">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div
                      className={`flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br ${visual.gradient}`}
                    >
                      <Icon className="h-5 w-5" style={{ color: visual.color }} />
                    </div>
                    <div>
                      <p className="text-sm font-medium text-ink">{agent.name}</p>
                      <p className="text-xs capitalize text-ink-faint">{agent.agent_type}</p>
                    </div>
                  </div>
                  <button
                    onClick={() => deleteAgent.mutate(agent.id)}
                    className="text-ink-faint transition-colors hover:text-accent-pink"
                    aria-label={`Delete ${agent.name}`}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>

                <p className="line-clamp-2 text-xs text-ink-muted">{agent.description ?? "No description."}</p>

                <div className="flex items-center justify-between">
                  <select
                    value={agent.status}
                    onChange={(e) => updateStatus.mutate({ id: agent.id, status: e.target.value as Agent["status"] })}
                    className="rounded-lg border border-base-border bg-base-panel-2 px-2 py-1 text-xs text-ink focus:outline-none"
                  >
                    <option value="active">Active</option>
                    <option value="paused">Paused</option>
                    <option value="draft">Draft</option>
                  </select>
                  <span className="font-mono text-[10px] text-ink-faint">temp {agent.temperature}</span>
                </div>
              </div>
            );
          })}

          {agents.length === 0 && (
            <p className="col-span-full text-sm text-ink-faint">No agents yet - create one to get started.</p>
          )}
        </div>
      )}

      {showCreate && <CreateAgentModal onClose={() => setShowCreate(false)} />}
    </div>
  );
}

function CreateAgentModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [agentType, setAgentType] = useState<AgentType>("custom");
  const [description, setDescription] = useState("");
  const [instructions, setInstructions] = useState("");

  const create = useMutation({
    mutationFn: async () => api.post("/agents", { name, agent_type: agentType, description, instructions }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      toast.success("Agent created");
      onClose();
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="panel panel-glow w-full max-w-md p-5" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-display text-base font-semibold">New Agent</h2>
          <button onClick={onClose} className="text-ink-faint hover:text-ink">
            <X className="h-4 w-4" />
          </button>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
          className="space-y-3"
        >
          <div>
            <label className="mb-1 block text-xs text-ink-muted">Name</label>
            <input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-sm focus:outline-none"
              placeholder="Warranty Agent"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-ink-muted">Type</label>
            <select
              value={agentType}
              onChange={(e) => setAgentType(e.target.value as AgentType)}
              className="w-full rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-sm focus:outline-none"
            >
              {AGENT_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-ink-muted">Description</label>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-sm focus:outline-none"
              placeholder="What this agent handles"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-ink-muted">Instructions</label>
            <textarea
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              rows={4}
              className="w-full rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-sm focus:outline-none"
              placeholder="You handle warranty claims for the business..."
            />
          </div>
          <button
            type="submit"
            disabled={create.isPending}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-accent-violet to-accent-blue px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
          >
            {create.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Create agent
          </button>
        </form>
      </div>
    </div>
  );
}
