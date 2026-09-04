import { User, Handshake, LifeBuoy, Trophy, Sparkles, type LucideIcon } from "lucide-react";
import type { AgentType } from "@/types";

interface AgentVisual {
  icon: LucideIcon;
  color: string; // tailwind color token used for glow/ring
  gradient: string; // tailwind gradient classes
}

export const AGENT_VISUALS: Record<AgentType, AgentVisual> = {
  personal: { icon: User, color: "#3B82F6", gradient: "from-accent-blue/40 to-accent-blue/10" },
  sales: { icon: Handshake, color: "#34D399", gradient: "from-accent-green/40 to-accent-green/10" },
  support: { icon: LifeBuoy, color: "#EC4899", gradient: "from-accent-pink/40 to-accent-pink/10" },
  opportunity: { icon: Trophy, color: "#F5B342", gradient: "from-accent-amber/40 to-accent-amber/10" },
  custom: { icon: Sparkles, color: "#8B5CF6", gradient: "from-accent-violet/40 to-accent-violet/10" },
};

export function agentVisual(type: AgentType): AgentVisual {
  return AGENT_VISUALS[type] ?? AGENT_VISUALS.custom;
}
