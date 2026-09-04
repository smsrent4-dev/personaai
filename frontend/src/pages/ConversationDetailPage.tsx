import { useParams, Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  FileText,
  MapPin,
  User as UserIcon,
  Send,
  UserRoundCheck,
  Bot,
} from "lucide-react";
import { format } from "date-fns";
import { api } from "@/lib/api";
import type { Conversation, Integration, Message } from "@/types";
import { cn } from "@/lib/utils";
import PlatformBadge from "@/components/PlatformBadge";

function MessageMedia({
  message,
  integration,
}: {
  message: Message;
  integration: Integration | undefined;
}) {
  // Media playback/preview/download only works for platforms with a
  // media-proxy endpoint (WhatsApp today — see whatsapp_webhook.py's
  // /whatsapp/media route). Other platforms fall back to a plain label.
  const mediaUrl =
    integration &&
    integration.platform === "whatsapp" &&
    message.media_file_id
      ? `/api/v1/whatsapp/media/${integration.id}/${message.media_file_id}`
      : null;

  if (message.message_type === "image") {
    return mediaUrl ? (
      <img
        src={mediaUrl}
        alt="Shared image"
        className="mb-2 max-h-64 rounded-lg object-cover"
      />
    ) : (
      <p className="italic text-ink-faint">[image]</p>
    );
  }

  if (message.message_type === "video") {
    return mediaUrl ? (
      <video
        src={mediaUrl}
        controls
        className="mb-2 max-h-64 rounded-lg"
      />
    ) : (
      <p className="italic text-ink-faint">[video]</p>
    );
  }

  if (message.message_type === "voice") {
    return mediaUrl ? (
      <audio src={mediaUrl} controls className="mb-2 w-64" />
    ) : (
      <p className="italic text-ink-faint">[voice message]</p>
    );
  }

  if (message.message_type === "document") {
    const filename = message.platform_metadata?.filename ?? "document";

    return mediaUrl ? (
      <a
        href={mediaUrl}
        download={filename}
        className="mb-2 flex items-center gap-2 text-accent-blue hover:underline"
      >
        <FileText className="h-4 w-4" />
        {filename}
      </a>
    ) : (
      <p className="italic text-ink-faint">
        [document: {filename}]
      </p>
    );
  }

  if (
    message.message_type === "location" &&
    message.latitude != null &&
    message.longitude != null
  ) {
    return (
      <a
        href={`https://maps.google.com/?q=${message.latitude},${message.longitude}`}
        target="_blank"
        rel="noreferrer"
        className="mb-2 flex items-center gap-2 text-accent-blue hover:underline"
      >
        <MapPin className="h-4 w-4" />
        {message.platform_metadata?.name ?? "Shared location"}
      </a>
    );
  }

  if (message.message_type === "contact") {
    const contacts = message.platform_metadata?.contacts ?? [];

    return (
      <div className="mb-2 space-y-1">
        {contacts.length > 0 ? (
          contacts.map((c: any, i: number) => (
            <div
              key={i}
              className="flex items-center gap-2 rounded-lg border border-base-border px-3 py-2"
            >
              <UserIcon className="h-4 w-4 text-ink-faint" />

              <div className="text-xs">
                <p className="text-ink">
                  {c.name?.formatted_name}
                </p>

                <p className="text-ink-faint">
                  {c.phones?.[0]?.phone}
                </p>
              </div>
            </div>
          ))
        ) : (
          <p className="italic text-ink-faint">
            [contact card]
          </p>
        )}
      </div>
    );
  }

  return null;
}

export default function ConversationDetailPage() {
  const { conversationId } = useParams<{
    conversationId: string;
  }>();

  const queryClient = useQueryClient();

  const [reply, setReply] = useState("");
  const [isTakingOver, setIsTakingOver] = useState(false);
  const [isSending, setIsSending] = useState(false);

  const messagesContainerRef = useRef<HTMLDivElement>(null);

  // Used to determine whether we should automatically follow new messages.
  const shouldScrollToBottom = useRef(true);

  const hasInitializedScroll = useRef(false);

  const { data: conversation } = useQuery({
    queryKey: ["conversation", conversationId],
    queryFn: async () =>
      (
        await api.get<Conversation>(
          `/conversations/${conversationId}`
        )
      ).data,
    enabled: !!conversationId,
  });

  const { data: messages = [], isLoading } = useQuery({
    queryKey: ["conversation-messages", conversationId],
    queryFn: async () =>
      (
        await api.get<Message[]>(
          `/conversations/${conversationId}/messages`
        )
      ).data,
    enabled: !!conversationId,
    refetchInterval: 10_000,
  });

  const { data: integrations = [] } = useQuery({
    queryKey: ["integrations"],
    queryFn: async () =>
      (await api.get<Integration[]>("/integrations")).data,
  });

  const integration = integrations.find(
    (i) => i.platform === conversation?.platform
  );

  const isNearBottom = (element: HTMLDivElement) => {
    return (
      element.scrollHeight -
        element.scrollTop -
        element.clientHeight <
      100
    );
  };

  const scrollToBottom = (behavior: ScrollBehavior = "auto") => {
    const container = messagesContainerRef.current;

    if (!container) return;

    container.scrollTo({
      top: container.scrollHeight,
      behavior,
    });
  };

  const handleMessagesScroll = () => {
    const container = messagesContainerRef.current;

    if (!container) return;

    shouldScrollToBottom.current = isNearBottom(container);
  };

  // On the initial load, start at the newest messages.
  useEffect(() => {
    if (
      isLoading ||
      messages.length === 0 ||
      hasInitializedScroll.current
    ) {
      return;
    }

    requestAnimationFrame(() => {
      scrollToBottom();
      hasInitializedScroll.current = true;
      shouldScrollToBottom.current = true;
    });
  }, [isLoading, messages.length]);

  // When new messages arrive, only follow them if the user is
  // already near the bottom.
  useEffect(() => {
    if (
      !hasInitializedScroll.current ||
      messages.length === 0 ||
      !shouldScrollToBottom.current
    ) {
      return;
    }

    requestAnimationFrame(() => {
      scrollToBottom("smooth");
    });
  }, [messages]);

  const takeOver = async () => {
    if (!conversationId) return;

    setIsTakingOver(true);

    try {
      await api.post(
        `/conversations/${conversationId}/takeover`
      );

      await queryClient.invalidateQueries({
        queryKey: ["conversation", conversationId],
      });
    } finally {
      setIsTakingOver(false);
    }
  };

  const releaseToAI = async () => {
    if (!conversationId) return;

    setIsTakingOver(true);

    try {
      await api.post(
        `/conversations/${conversationId}/release`
      );

      await queryClient.invalidateQueries({
        queryKey: ["conversation", conversationId],
      });
    } finally {
      setIsTakingOver(false);
    }
  };

  const sendReply = async () => {
    if (
      !conversationId ||
      !reply.trim() ||
      isSending
    ) {
      return;
    }

    setIsSending(true);

    try {
      await api.post(
        `/conversations/${conversationId}/messages`,
        {
          content: reply.trim(),
        }
      );

      setReply("");

      shouldScrollToBottom.current = true;

      await queryClient.invalidateQueries({
        queryKey: [
          "conversation-messages",
          conversationId,
        ],
      });

      requestAnimationFrame(() => {
        scrollToBottom("smooth");
      });
    } finally {
      setIsSending(false);
    }
  };

  return (
    <div className="mx-auto flex h-[calc(100vh-2rem)] max-w-2xl flex-col">
      {/* Back link */}
      <div className="shrink-0 pb-4">
        <Link
          to="/conversations"
          className="flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to conversations
        </Link>
      </div>

      {conversation && (
        <div className="panel shrink-0 rounded-b-none border-b-0 p-4">
          <div className="flex items-center justify-between gap-4">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-ink">
                {conversation.external_user_name ??
                  conversation.external_conversation_id}
              </p>

              <div className="mt-0.5 flex items-center gap-2">
                <PlatformBadge
                  platform={conversation.platform}
                />

                <span className="truncate text-xs text-ink-faint">
                  · {conversation.external_conversation_id} ·{" "}
                  {conversation.status}
                </span>
              </div>
            </div>

            {conversation.assigned_to_human ? (
              <button
                onClick={releaseToAI}
                disabled={isTakingOver}
                className="flex shrink-0 items-center gap-2 rounded-lg bg-base-panel-2 px-3 py-2 text-xs font-medium text-ink transition-colors hover:bg-base-panel-2/80 disabled:opacity-50"
              >
                <Bot className="h-4 w-4" />

                {isTakingOver
                  ? "Releasing…"
                  : "Release to AI"}
              </button>
            ) : (
              <button
                onClick={takeOver}
                disabled={isTakingOver}
                className="flex shrink-0 items-center gap-2 rounded-lg bg-accent-violet px-3 py-2 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                <UserRoundCheck className="h-4 w-4" />

                {isTakingOver
                  ? "Taking over…"
                  : "Take Over"}
              </button>
            )}
          </div>
        </div>
      )}

      {/* Chat window */}
      <div
        className={cn(
          "panel flex min-h-0 flex-1 flex-col overflow-hidden",
          conversation?.assigned_to_human
            ? "rounded-none border-b-0"
            : "rounded-t-none"
        )}
      >
        {/* Messages */}
        <div
          ref={messagesContainerRef}
          onScroll={handleMessagesScroll}
          className="min-h-0 flex-1 overflow-y-auto px-4 py-4"
        >
          {isLoading && (
            <p className="text-sm text-ink-faint">
              Loading…
            </p>
          )}

          {!isLoading && messages.length === 0 && (
            <p className="text-sm text-ink-faint">
              No messages yet.
            </p>
          )}

          <div className="space-y-3">
            {messages.map((message) => (
              <div
                key={message.id}
                className={cn(
                  "flex",
                  message.role === "user"
                    ? "justify-start"
                    : "justify-end"
                )}
              >
                <div
                  className={cn(
                    "max-w-[75%] rounded-2xl px-4 py-2 text-sm",
                    message.role === "user"
                      ? "bg-base-panel-2 text-ink"
                      : "bg-gradient-to-br from-accent-violet/30 to-accent-blue/20 text-ink"
                  )}
                >
                  <MessageMedia
                    message={message}
                    integration={integration}
                  />

                  {message.content}

                  <p className="mt-1 font-mono text-[10px] text-ink-faint">
                    {format(
                      new Date(message.created_at),
                      "MMM d, HH:mm"
                    )}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Human reply composer */}
        {conversation?.assigned_to_human && (
          <div className="shrink-0 border-t border-base-border p-3">
            <div className="mb-2 flex items-center gap-2 text-xs text-ink-muted">
              <UserRoundCheck className="h-3.5 w-3.5" />
              You are handling this conversation
            </div>

            <div className="flex gap-2">
              <textarea
                value={reply}
                onChange={(e) =>
                  setReply(e.target.value)
                }
                onKeyDown={(e) => {
                  if (
                    e.key === "Enter" &&
                    !e.shiftKey
                  ) {
                    e.preventDefault();
                    sendReply();
                  }
                }}
                placeholder="Type your reply…"
                rows={2}
                className="min-h-[44px] flex-1 resize-none rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-sm text-ink outline-none placeholder:text-ink-faint focus:border-accent-violet"
              />

              <button
                onClick={sendReply}
                disabled={
                  !reply.trim() || isSending
                }
                className="self-end rounded-lg bg-accent-violet p-2.5 text-white transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                <Send className="h-4 w-4" />
              </button>
            </div>

            <p className="mt-1.5 text-[10px] text-ink-faint">
              Press Enter to send · Shift+Enter for a new line
            </p>
          </div>
        )}
      </div>
    </div>
  );
}