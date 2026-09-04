import { Construction } from "lucide-react";

export default function ComingSoonPage({ title }: { title: string }) {
  return (
    <div className="flex h-[70vh] flex-col items-center justify-center gap-3 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-full border border-base-border bg-base-panel-2">
        <Construction className="h-6 w-6 text-ink-faint" />
      </div>
      <h1 className="font-display text-lg font-semibold">{title}</h1>
      <p className="max-w-sm text-sm text-ink-muted">
        This section isn't built yet — it's planned for a later milestone and isn't wired to the backend.
      </p>
    </div>
  );
}
