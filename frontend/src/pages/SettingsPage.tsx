import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api, apiErrorMessage } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";

export default function SettingsPage() {
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [businessName, setBusinessName] = useState(user?.business_name ?? "");

  const save = useMutation({
    mutationFn: async () => api.patch("/users/me", { full_name: fullName, business_name: businessName || null }),
    onSuccess: ({ data }) => {
      setUser(data);
      toast.success("Profile updated");
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  if (!user) return null;

  return (
    <div className="max-w-lg space-y-6">
      <div>
        <h1 className="font-display text-xl font-semibold">Settings</h1>
        <p className="text-sm text-ink-muted">Your account and business details.</p>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
        className="panel space-y-4 p-5"
      >
        <div>
          <label className="mb-1.5 block text-xs text-ink-muted">Email</label>
          <input
            disabled
            value={user.email}
            className="w-full rounded-lg border border-base-border bg-base-panel-2/40 px-3 py-2 text-sm text-ink-faint"
          />
        </div>
        <div>
          <label className="mb-1.5 block text-xs text-ink-muted">Full name</label>
          <input
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            className="w-full rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-sm text-ink focus:border-accent-violet/50 focus:outline-none"
          />
        </div>
        <div>
          <label className="mb-1.5 block text-xs text-ink-muted">Business name</label>
          <input
            value={businessName}
            onChange={(e) => setBusinessName(e.target.value)}
            className="w-full rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-sm text-ink focus:border-accent-violet/50 focus:outline-none"
          />
        </div>
        <div>
          <label className="mb-1.5 block text-xs text-ink-muted">Role</label>
          <input
            disabled
            value={user.role}
            className="w-full rounded-lg border border-base-border bg-base-panel-2/40 px-3 py-2 text-sm capitalize text-ink-faint"
          />
        </div>
        <button
          type="submit"
          disabled={save.isPending}
          className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-accent-violet to-accent-blue px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
        >
          {save.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
          Save changes
        </button>
      </form>
    </div>
  );
}
