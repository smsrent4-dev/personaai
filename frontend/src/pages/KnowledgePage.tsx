import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Upload, FileText, Trash2, Loader2, Search, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { api, apiErrorMessage } from "@/lib/api";
import type { KnowledgeDocument } from "@/types";
import { cn } from "@/lib/utils";

const STATUS_STYLES: Record<KnowledgeDocument["status"], string> = {
  ready: "bg-accent-green/15 text-accent-green",
  processing: "bg-accent-blue/15 text-accent-blue",
  pending: "bg-accent-amber/15 text-accent-amber",
  failed: "bg-accent-pink/15 text-accent-pink",
};

export default function KnowledgePage() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [pasteTitle, setPasteTitle] = useState("");
  const [pasteContent, setPasteContent] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<
    { chunk_id: string; document_title: string; content: string; score: number }[] | null
  >(null);
  const [searching, setSearching] = useState(false);

  const { data: documents = [], isLoading } = useQuery({
    queryKey: ["knowledge-documents"],
    queryFn: async () => (await api.get<KnowledgeDocument[]>("/knowledge/documents")).data,
  });

  const uploadFile = useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append("file", file);
      return api.post("/knowledge/documents/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledge-documents"] });
      toast.success("Document uploaded and processed");
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Upload failed")),
  });

  const pasteText = useMutation({
    mutationFn: async () => api.post("/knowledge/documents/text", { title: pasteTitle, content: pasteContent }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledge-documents"] });
      setPasteTitle("");
      setPasteContent("");
      toast.success("Added to knowledge base");
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  const reprocess = useMutation({
    mutationFn: async (id: string) => api.post(`/knowledge/documents/${id}/reprocess`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["knowledge-documents"] }),
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  const deleteDoc = useMutation({
    mutationFn: async (id: string) => api.delete(`/knowledge/documents/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["knowledge-documents"] }),
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    setSearching(true);
    try {
      const { data } = await api.post("/knowledge/search", { query: searchQuery, top_k: 5 });
      setSearchResults(data.results);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    } finally {
      setSearching(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-xl font-semibold">Knowledge Base</h1>
        <p className="text-sm text-ink-muted">
          What your agents know - upload files or paste text; it's chunked, embedded, and searchable.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="panel space-y-3 p-4">
          <p className="text-xs font-medium text-ink-muted">Upload a file</p>
          <p className="text-xs text-ink-faint">PDF, Word (.docx), text, or markdown.</p>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx,.txt,.md,.markdown"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) uploadFile.mutate(file);
              e.target.value = "";
            }}
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploadFile.isPending}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-base-border py-6 text-sm text-ink-muted transition-colors hover:border-accent-violet/50 hover:text-ink disabled:opacity-60"
          >
            {uploadFile.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            {uploadFile.isPending ? "Processing…" : "Choose a file"}
          </button>
        </div>

        <div className="panel space-y-3 p-4">
          <p className="text-xs font-medium text-ink-muted">Paste text / FAQ</p>
          <input
            value={pasteTitle}
            onChange={(e) => setPasteTitle(e.target.value)}
            placeholder="Title"
            className="w-full rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-sm focus:outline-none"
          />
          <textarea
            value={pasteContent}
            onChange={(e) => setPasteContent(e.target.value)}
            rows={3}
            placeholder="Paste your FAQ, policy, or any text…"
            className="w-full rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-sm focus:outline-none"
          />
          <button
            onClick={() => pasteText.mutate()}
            disabled={pasteText.isPending || !pasteTitle.trim() || !pasteContent.trim()}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-accent-violet to-accent-blue px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
          >
            {pasteText.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Add to knowledge base
          </button>
        </div>
      </div>

      <form onSubmit={handleSearch} className="panel flex items-center gap-3 p-3">
        <Search className="ml-2 h-4 w-4 shrink-0 text-ink-faint" />
        <input
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Test what your agents would retrieve for a question…"
          className="w-full bg-transparent text-sm text-ink placeholder:text-ink-faint focus:outline-none"
        />
        <button
          type="submit"
          disabled={searching}
          className="shrink-0 rounded-lg border border-base-border px-3 py-1.5 text-xs text-ink-muted hover:text-ink"
        >
          {searching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Search"}
        </button>
      </form>

      {searchResults && (
        <div className="panel space-y-3 p-4">
          <p className="text-xs font-medium text-ink-muted">Top matches</p>
          {searchResults.length === 0 && <p className="text-xs text-ink-faint">No matches yet.</p>}
          {searchResults.map((r) => (
            <div key={r.chunk_id} className="rounded-lg border border-base-border p-3">
              <div className="mb-1 flex items-center justify-between">
                <span className="text-xs font-medium text-ink">{r.document_title}</span>
                <span className="font-mono text-[10px] text-ink-faint">{(r.score * 100).toFixed(0)}%</span>
              </div>
              <p className="text-xs text-ink-muted">{r.content}</p>
            </div>
          ))}
        </div>
      )}

      <div className="panel divide-y divide-base-border">
        {isLoading && <p className="p-4 text-sm text-ink-faint">Loading…</p>}
        {!isLoading && documents.length === 0 && (
          <div className="flex flex-col items-center gap-2 p-10 text-center">
            <FileText className="h-6 w-6 text-ink-faint" />
            <p className="text-sm text-ink-muted">No documents yet.</p>
          </div>
        )}
        {documents.map((doc) => (
          <div key={doc.id} className="flex items-center justify-between px-4 py-3">
            <div className="min-w-0">
              <p className="truncate text-sm text-ink">{doc.title}</p>
              <p className="text-xs uppercase text-ink-faint">{doc.source_type}</p>
              {doc.status === "failed" && doc.error_message && (
                <p className="mt-0.5 truncate text-xs text-accent-pink">{doc.error_message}</p>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <span className={cn("rounded-full px-2 py-0.5 text-[10px]", STATUS_STYLES[doc.status])}>
                {doc.status}
              </span>
              {doc.status === "failed" && (
                <button
                  onClick={() => reprocess.mutate(doc.id)}
                  className="text-ink-faint hover:text-accent-blue"
                  aria-label="Retry"
                >
                  <RefreshCw className="h-4 w-4" />
                </button>
              )}
              <button
                onClick={() => deleteDoc.mutate(doc.id)}
                className="text-ink-faint hover:text-accent-pink"
                aria-label="Delete"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
