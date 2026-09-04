import { useNavigate } from "react-router-dom";
import type { Agent } from "@/types";
import { agentVisual } from "./agent-visuals";

interface AgentOrbitProps {
  agents: Agent[];
  centerInitials: string;
}

const RADIUS = 210;
const CENTER = 260;

export default function AgentOrbit({ agents, centerInitials }: AgentOrbitProps) {
  const navigate = useNavigate();
  const visibleAgents = agents.slice(0, 8);
  const n = Math.max(visibleAgents.length, 1);

  const positioned = visibleAgents.map((agent, i) => {
    const angle = (2 * Math.PI * i) / n - Math.PI / 2;
    const x = CENTER + RADIUS * Math.cos(angle);
    const y = CENTER + RADIUS * Math.sin(angle);
    return { agent, x, y };
  });

  return (
    <div className="relative mx-auto" style={{ width: CENTER * 2, height: CENTER * 2 }}>
      <svg className="absolute inset-0" width={CENTER * 2} height={CENTER * 2}>
        <defs>
          <linearGradient id="orbit-line-gradient" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#8B5CF6" />
            <stop offset="100%" stopColor="#22D3EE" />
          </linearGradient>
        </defs>
        <circle cx={CENTER} cy={CENTER} r={RADIUS} fill="none" stroke="#23244A" strokeWidth="1" strokeDasharray="2 6" />
        {positioned.map(({ agent, x, y }) => (
          <line key={agent.id} className="orbit-line" x1={CENTER} y1={CENTER} x2={x} y2={y} />
        ))}
      </svg>

      <div
        className="absolute flex flex-col items-center justify-center rounded-full border border-accent-violet/30 bg-gradient-to-br from-base-panel-2 to-base-panel shadow-glow shadow-accent-violet/30"
        style={{ width: 140, height: 140, left: CENTER - 70, top: CENTER - 70 }}
      >
        <div className="absolute inset-0 animate-pulse-slow rounded-full bg-accent-violet/10" />
        <span className="font-display text-3xl font-semibold text-glow-violet">{centerInitials}</span>
        <span className="mt-1 text-[10px] uppercase tracking-wider text-ink-muted">You</span>
      </div>

      {positioned.map(({ agent, x, y }) => {
        const visual = agentVisual(agent.agent_type);
        const Icon = visual.icon;
        const isActive = agent.status === "active";
        return (
          <button
            key={agent.id}
            onClick={() => navigate("/agents")}
            className="group absolute flex flex-col items-center"
            style={{ left: x - 40, top: y - 40, width: 80 }}
          >
            <div
              className={`flex h-14 w-14 items-center justify-center rounded-full border bg-gradient-to-br ${visual.gradient} transition-transform group-hover:scale-110`}
              style={{ borderColor: `${visual.color}55` }}
            >
              <Icon className="h-6 w-6" style={{ color: visual.color }} />
            </div>
            <span className="mt-1.5 max-w-[90px] truncate text-[11px] font-medium text-ink">{agent.name}</span>
            <span className="flex items-center gap-1 text-[10px] text-ink-muted">
              <span className={`status-dot ${isActive ? "bg-accent-green animate-pulse-slow" : "bg-ink-faint"}`} />
              {isActive ? "Active" : agent.status}
            </span>
          </button>
        );
      })}
    </div>
  );
}
