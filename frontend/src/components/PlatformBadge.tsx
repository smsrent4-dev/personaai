import type { Platform } from "@/types";

const PLATFORM_META: Record<string, { label: string; dot: string }> = {
  whatsapp: { label: "WhatsApp", dot: "bg-emerald-500" },
  telegram: { label: "Telegram", dot: "bg-sky-500" },
  instagram: { label: "Instagram", dot: "bg-fuchsia-500" },
  messenger: { label: "Messenger", dot: "bg-orange-500" },
  discord: { label: "Discord", dot: "bg-indigo-400" },
  slack: { label: "Slack", dot: "bg-purple-400" },
  web_widget: { label: "Web Widget", dot: "bg-teal-400" },
  voice: { label: "Voice", dot: "bg-rose-400" },
};

export default function PlatformBadge({ platform, className = "" }: { platform: Platform | string; className?: string }) {
  const meta = PLATFORM_META[platform] ?? { label: platform, dot: "bg-ink-faint" };
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs text-ink-faint ${className}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} />
      {meta.label}
    </span>
  );
}
