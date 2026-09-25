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
  MessageCircle,
  Sparkles,
  Clock3,
  CheckCheck,
  Loader2,
  Circle,
  MoreHorizontal,
} from "lucide-react";
import { format } from "date-fns";
import { api } from "@/lib/api";
import type {
  Conversation,
  Integration,
  Message,
} from "@/types";
import { cn } from "@/lib/utils";
import PlatformBadge from "@/components/PlatformBadge";

/* -------------------------------------------------------------------------- */
/* Helpers                                                                    */
/* -------------------------------------------------------------------------- */

function getDisplayName(
  conversation?: Conversation
) {
  if (!conversation) return "Conversation";

  return (
    conversation.external_user_name ??
    conversation.external_conversation_id ??
    "Customer"
  );
}

function getInitials(name: string) {
  const parts = name
    .trim()
    .split(/\s+/)
    .filter(Boolean);

  if (parts.length === 0) return "C";

  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }

  return (
    parts[0][0] + parts[parts.length - 1][0]
  ).toUpperCase();
}

/* -------------------------------------------------------------------------- */
/* Media                                                                      */
/* -------------------------------------------------------------------------- */

function MessageMedia({
  message,
  integration,
}: {
  message: Message;
  integration: Integration | undefined;
}) {
  const mediaUrl =
    integration &&
    integration.platform === "whatsapp" &&
    message.media_file_id
      ? `/api/v1/whatsapp/media/${integration.id}/${message.media_file_id}`
      : null;

  if (message.message_type === "image") {
    return mediaUrl ? (
      <div className="group relative mb-2 overflow-hidden rounded-2xl">
        <img
          src={mediaUrl}
          alt="Shared image"
          loading="lazy"
          className="max-h-[360px] w-full max-w-[320px] rounded-2xl object-cover transition-transform duration-500 ease-out group-hover:scale-[1.02]"
        />

        <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/20 via-transparent to-transparent opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
      </div>
    ) : (
      <div className="mb-2 flex items-center gap-2 text-xs italic text-ink-faint">
        <MessageCircle className="h-4 w-4" />
        Image
      </div>
    );
  }

  if (message.message_type === "video") {
    return mediaUrl ? (
      <div className="mb-2 overflow-hidden rounded-2xl">
        <video
          src={mediaUrl}
          controls
          preload="metadata"
          className="max-h-[360px] w-full max-w-[360px] rounded-2xl"
        />
      </div>
    ) : (
      <p className="mb-2 flex items-center gap-2 text-xs italic text-ink-faint">
        <MessageCircle className="h-4 w-4" />
        Video
      </p>
    );
  }

  if (message.message_type === "voice") {
    return mediaUrl ? (
      <div className="mb-2 rounded-2xl bg-black/5 p-2 dark:bg-white/5">
        <audio
          src={mediaUrl}
          controls
          preload="metadata"
          className="w-full max-w-[320px]"
        />
      </div>
    ) : (
      <p className="mb-2 flex items-center gap-2 text-xs italic text-ink-faint">
        <MessageCircle className="h-4 w-4" />
        Voice message
      </p>
    );
  }

  if (message.message_type === "document") {
    const filename =
      message.platform_metadata?.filename ??
      "document";

    return mediaUrl ? (
      <a
        href={mediaUrl}
        download={filename}
        className="group mb-2 flex max-w-[320px] items-center gap-3 rounded-2xl border border-base-border bg-base-panel-2/70 px-3 py-3 transition-all duration-200 hover:-translate-y-0.5 hover:border-accent-violet/40 hover:bg-base-panel-2"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent-blue/10 text-accent-blue">
          <FileText className="h-4 w-4" />
        </span>

        <span className="min-w-0 flex-1">
          <span className="block truncate text-xs font-medium text-ink">
            {filename}
          </span>

          <span className="mt-0.5 block text-[10px] text-ink-faint">
            Download document
          </span>
        </span>
      </a>
    ) : (
      <p className="mb-2 text-xs italic text-ink-faint">
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
        className="group mb-2 flex max-w-[280px] items-center gap-3 rounded-2xl border border-base-border bg-base-panel-2/70 px-3 py-3 transition-all duration-200 hover:-translate-y-0.5 hover:border-accent-blue/40"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent-blue/10 text-accent-blue">
          <MapPin className="h-4 w-4" />
        </span>

        <span className="min-w-0">
          <span className="block text-xs font-medium text-ink">
            {message.platform_metadata?.name ??
              "Shared location"}
          </span>

          <span className="mt-0.5 block text-[10px] text-accent-blue">
            Open in Maps
          </span>
        </span>
      </a>
    );
  }

  if (message.message_type === "contact") {
    const contacts =
      message.platform_metadata?.contacts ?? [];

    return (
      <div className="mb-2 space-y-2">
        {contacts.length > 0 ? (
          contacts.map((c: any, i: number) => (
            <div
              key={i}
              className="flex items-center gap-3 rounded-2xl border border-base-border bg-base-panel-2/70 px-3 py-3"
            >
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent-violet/10 text-accent-violet">
                <UserIcon className="h-4 w-4" />
              </span>

              <div className="min-w-0">
                <p className="truncate text-xs font-medium text-ink">
                  {c.name?.formatted_name ??
                    "Contact"}
                </p>

                <p className="truncate text-[10px] text-ink-faint">
                  {c.phones?.[0]?.phone ??
                    "No phone number"}
                </p>
              </div>
            </div>
          ))
        ) : (
          <p className="text-xs italic text-ink-faint">
            [contact card]
          </p>
        )}
      </div>
    );
  }

  return null;
}

/* -------------------------------------------------------------------------- */
/* Animated background                                                        */
/* -------------------------------------------------------------------------- */

function ConversationBackdrop() {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 overflow-hidden"
    >
      <div className="absolute -left-32 top-16 h-64 w-64 rounded-full bg-accent-violet/5 blur-3xl animate-[pulse_7s_ease-in-out_infinite]" />

      <div className="absolute -right-32 bottom-20 h-72 w-72 rounded-full bg-accent-blue/5 blur-3xl animate-[pulse_9s_ease-in-out_infinite]" />

      <div className="absolute left-1/2 top-1/3 h-40 w-40 -translate-x-1/2 rounded-full bg-accent-violet/[0.025] blur-3xl animate-[spin_30s_linear_infinite]" />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Customer avatar                                                            */
/* -------------------------------------------------------------------------- */

function CustomerAvatar({
  name,
  size = "md",
}: {
  name: string;
  size?: "sm" | "md";
}) {
  return (
    <div
      className={cn(
        "relative flex shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-accent-violet/20 via-accent-blue/10 to-base-panel-2 text-accent-violet ring-1 ring-inset ring-accent-violet/10",
        size === "sm"
          ? "h-8 w-8 rounded-xl"
          : "h-10 w-10"
      )}
    >
      <span
        className={cn(
          "font-semibold",
          size === "sm"
            ? "text-[10px]"
            : "text-xs"
        )}
      >
        {getInitials(name)}
      </span>

      <span className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-base-panel bg-accent-green" />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Message bubble                                                             */
/* -------------------------------------------------------------------------- */

function MessageBubble({
  message,
  integration,
  index,
}: {
  message: Message;
  integration: Integration | undefined;
  index: number;
}) {
  const isCustomer = message.role === "user";

  return (
    <div
      className={cn(
        "group flex w-full animate-[messageIn_0.35s_ease-out_both]",
        isCustomer
          ? "justify-start"
          : "justify-end"
      )}
      style={{
        animationDelay: `${Math.min(
          index * 20,
          180
        )}ms`,
      }}
    >
      <div
        className={cn(
          "flex max-w-[92%] items-end gap-2 sm:max-w-[78%] lg:max-w-[72%]",
          isCustomer
            ? "flex-row"
            : "flex-row-reverse"
        )}
      >
        {/* Avatar */}
        {isCustomer ? (
          <CustomerAvatar
            name={
              message.platform_metadata
                ?.sender_name ??
              "Customer"
            }
            size="sm"
          />
        ) : (
          <div className="relative hidden h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-accent-violet/20 to-accent-blue/10 text-accent-violet ring-1 ring-inset ring-accent-violet/10 sm:flex">
            <Bot className="h-4 w-4" />

            <Sparkles className="absolute -right-1 -top-1 h-3 w-3 animate-pulse text-accent-violet" />
          </div>
        )}

        <div
          className={cn(
            "min-w-0 rounded-2xl px-3.5 py-2.5 shadow-sm transition-all duration-200 hover:shadow-md sm:px-4 sm:py-3",
            isCustomer
              ? "rounded-bl-md bg-base-panel-2 text-ink ring-1 ring-inset ring-base-border/70"
              : "rounded-br-md bg-gradient-to-br from-accent-violet/20 via-accent-violet/10 to-accent-blue/10 text-ink ring-1 ring-inset ring-accent-violet/20"
          )}
        >
          <MessageMedia
            message={message}
            integration={integration}
          />

          {message.content && (
            <p className="whitespace-pre-wrap break-words text-[13px] leading-5 sm:text-sm sm:leading-6">
              {message.content}
            </p>
          )}

          <div
            className={cn(
              "mt-1.5 flex items-center gap-1.5",
              isCustomer
                ? "justify-start"
                : "justify-end"
            )}
          >
            <span className="font-mono text-[9px] text-ink-faint sm:text-[10px]">
              {format(
                new Date(message.created_at),
                "MMM d, HH:mm"
              )}
            </span>

            {!isCustomer && (
              <CheckCheck className="h-3 w-3 text-accent-violet/70" />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Loading messages                                                           */
/* -------------------------------------------------------------------------- */

function MessageLoading() {
  return (
    <div className="flex items-end gap-2">
      <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-accent-violet/10 text-accent-violet">
        <Bot className="h-4 w-4" />
      </div>

      <div className="rounded-2xl rounded-bl-md bg-base-panel-2 px-4 py-3 ring-1 ring-inset ring-base-border">
        <div className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-ink-faint [animation-delay:-0.3s]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-ink-faint [animation-delay:-0.15s]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-ink-faint" />
        </div>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Main                                                                       */
/* -------------------------------------------------------------------------- */

export default function ConversationDetailPage() {
  const { conversationId } = useParams<{
    conversationId: string;
  }>();

  const queryClient = useQueryClient();

  const [reply, setReply] = useState("");
  const [isTakingOver, setIsTakingOver] =
    useState(false);
  const [isSending, setIsSending] = useState(false);

  const messagesContainerRef =
    useRef<HTMLDivElement>(null);

  const shouldScrollToBottom =
    useRef(true);

  const hasInitializedScroll =
    useRef(false);

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

  const {
    data: messages = [],
    isLoading,
    isFetching,
  } = useQuery({
    queryKey: [
      "conversation-messages",
      conversationId,
    ],
    queryFn: async () =>
      (
        await api.get<Message[]>(
          `/conversations/${conversationId}/messages`
        )
      ).data,
    enabled: !!conversationId,
    refetchInterval: 10_000,
  });

  const { data: integrations = [] } =
    useQuery({
      queryKey: ["integrations"],
      queryFn: async () =>
        (
          await api.get<Integration[]>(
            "/integrations"
          )
        ).data,
    });

  const integration = integrations.find(
    (i) =>
      i.platform === conversation?.platform
  );

  const displayName =
    getDisplayName(conversation);

  const isHumanAssigned =
    Boolean(conversation?.assigned_to_human);

  const isNearBottom = (
    element: HTMLDivElement
  ) => {
    return (
      element.scrollHeight -
        element.scrollTop -
        element.clientHeight <
      120
    );
  };

  const scrollToBottom = (
    behavior: ScrollBehavior = "auto"
  ) => {
    const container =
      messagesContainerRef.current;

    if (!container) return;

    container.scrollTo({
      top: container.scrollHeight,
      behavior,
    });
  };

  const handleMessagesScroll = () => {
    const container =
      messagesContainerRef.current;

    if (!container) return;

    shouldScrollToBottom.current =
      isNearBottom(container);
  };

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
        queryKey: [
          "conversation",
          conversationId,
        ],
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
        queryKey: [
          "conversation",
          conversationId,
        ],
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
    <div className="relative flex h-[calc(100dvh-1rem)] min-h-0 w-full flex-col overflow-hidden sm:h-[calc(100dvh-2rem)]">
      <ConversationBackdrop />

      {/* ------------------------------------------------------------------ */}
      {/* Top navigation                                                      */}
      {/* ------------------------------------------------------------------ */}

      <div className="relative z-10 shrink-0 px-2 pb-2 sm:px-0 sm:pb-3">
        <div className="flex items-center justify-between gap-2">
          <Link
            to="/conversations"
            className="group flex min-w-0 items-center gap-2 rounded-xl px-2 py-2 text-xs font-medium text-ink-muted transition-all duration-200 hover:bg-base-panel-2 hover:text-ink sm:px-3 sm:text-sm"
          >
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-base-panel-2 transition-transform duration-200 group-hover:-translate-x-0.5">
              <ArrowLeft className="h-3.5 w-3.5" />
            </span>

            <span className="hidden sm:inline">
              Conversations
            </span>
          </Link>

          {isFetching &&
            !isLoading && (
              <div className="flex items-center gap-1.5 text-[10px] text-ink-faint">
                <Loader2 className="h-3 w-3 animate-spin" />
                Updating
              </div>
            )}
        </div>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Conversation shell                                                  */}
      {/* ------------------------------------------------------------------ */}

      <div className="relative z-10 flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-base-border bg-base-panel/90 shadow-2xl shadow-black/10 backdrop-blur-xl sm:rounded-3xl">
        {/* ---------------------------------------------------------------- */}
        {/* Header                                                            */}
        {/* ---------------------------------------------------------------- */}

        {conversation && (
          <header className="relative shrink-0 border-b border-base-border bg-base-panel/95 px-3 py-3 backdrop-blur-xl sm:px-5 sm:py-4">
            <div className="flex min-w-0 items-center gap-3">
              <CustomerAvatar
                name={displayName}
              />

              <div className="min-w-0 flex-1">
                <div className="flex min-w-0 items-center gap-2">
                  <h1 className="truncate text-sm font-semibold text-ink sm:text-base">
                    {displayName}
                  </h1>

                  <span className="hidden shrink-0 items-center gap-1 rounded-full bg-accent-green/10 px-2 py-0.5 text-[9px] font-medium text-accent-green sm:flex">
                    <Circle className="h-1.5 w-1.5 fill-current" />
                    Active
                  </span>
                </div>

                <div className="mt-1 flex min-w-0 items-center gap-2">
                  <PlatformBadge
                    platform={
                      conversation.platform
                    }
                  />

                  <span className="hidden h-3 w-px bg-base-border sm:block" />

                  <span className="hidden min-w-0 truncate text-[10px] text-ink-faint sm:block">
                    {conversation.external_conversation_id}
                  </span>

                  <span className="flex items-center gap-1 text-[10px] text-ink-faint">
                    <Clock3 className="h-3 w-3" />
                    {conversation.status}
                  </span>
                </div>
              </div>

              <div className="flex shrink-0 items-center gap-2">
                <div className="hidden items-center gap-1 rounded-xl border border-base-border bg-base-panel-2/60 px-2.5 py-2 text-[10px] text-ink-muted lg:flex">
                  <MessageCircle className="h-3.5 w-3.5" />
                  {messages.length} messages
                </div>

                <button
                  type="button"
                  aria-label="More conversation options"
                  className="flex h-9 w-9 items-center justify-center rounded-xl border border-base-border bg-base-panel-2/50 text-ink-muted transition-all duration-200 hover:border-base-border hover:bg-base-panel-2 hover:text-ink"
                >
                  <MoreHorizontal className="h-4 w-4" />
                </button>
              </div>
            </div>

            {/* Takeover control */}
            <div className="mt-3 sm:absolute sm:right-5 sm:top-1/2 sm:mt-0 sm:-translate-y-1/2 sm:pr-12">
              {isHumanAssigned ? (
                <button
                  onClick={releaseToAI}
                  disabled={isTakingOver}
                  className="flex w-full items-center justify-center gap-2 rounded-xl border border-base-border bg-base-panel-2 px-3 py-2.5 text-xs font-medium text-ink transition-all duration-200 hover:-translate-y-0.5 hover:border-accent-violet/30 hover:bg-base-panel-2/80 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
                >
                  {isTakingOver ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Bot className="h-3.5 w-3.5" />
                  )}

                  {isTakingOver
                    ? "Releasing…"
                    : "Release to AI"}
                </button>
              ) : (
                <button
                  onClick={takeOver}
                  disabled={isTakingOver}
                  className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-accent-violet to-accent-blue px-3.5 py-2.5 text-xs font-semibold text-white shadow-lg shadow-accent-violet/10 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-xl hover:shadow-accent-violet/20 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
                >
                  {isTakingOver ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <UserRoundCheck className="h-3.5 w-3.5" />
                  )}

                  {isTakingOver
                    ? "Taking over…"
                    : "Take Over"}
                </button>
              )}
            </div>
          </header>
        )}

        {/* ---------------------------------------------------------------- */}
        {/* Messages                                                          */}
        {/* ---------------------------------------------------------------- */}

        <div
          ref={messagesContainerRef}
          onScroll={handleMessagesScroll}
          className="relative min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 py-5 scrollbar-thin sm:px-5 sm:py-6 lg:px-8"
        >
          <div className="mx-auto flex w-full max-w-4xl flex-col">
            {/* Conversation date divider */}
            {messages.length > 0 && (
              <div className="mb-5 flex items-center gap-3">
                <div className="h-px flex-1 bg-base-border" />

                <span className="shrink-0 rounded-full border border-base-border bg-base-panel-2/80 px-3 py-1 text-[9px] font-medium uppercase tracking-wider text-ink-faint">
                  Conversation
                </span>

                <div className="h-px flex-1 bg-base-border" />
              </div>
            )}

            {/* Loading */}
            {isLoading && (
              <div className="flex min-h-[220px] items-center justify-center">
                <div className="flex flex-col items-center gap-3">
                  <div className="relative flex h-12 w-12 items-center justify-center rounded-2xl bg-accent-violet/10 text-accent-violet">
                    <Bot className="h-5 w-5" />

                    <span className="absolute inset-0 rounded-2xl border border-accent-violet/20 animate-ping [animation-duration:2s]" />
                  </div>

                  <p className="text-xs text-ink-faint">
                    Loading conversation…
                  </p>
                </div>
              </div>
            )}

            {/* Empty */}
            {!isLoading &&
              messages.length === 0 && (
                <div className="flex min-h-[320px] flex-col items-center justify-center px-4 text-center">
                  <div className="relative mb-5 flex h-16 w-16 items-center justify-center rounded-3xl bg-gradient-to-br from-accent-violet/15 to-accent-blue/10 text-accent-violet ring-1 ring-inset ring-accent-violet/10">
                    <MessageCircle className="h-7 w-7" />

                    <Sparkles className="absolute -right-1 -top-1 h-4 w-4 animate-pulse" />
                  </div>

                  <h2 className="text-sm font-semibold text-ink">
                    No messages yet
                  </h2>

                  <p className="mt-1 max-w-xs text-xs leading-5 text-ink-faint">
                    Messages from this customer will
                    appear here when the conversation
                    begins.
                  </p>
                </div>
              )}

            {/* Messages */}
            {!isLoading &&
              messages.length > 0 && (
                <div className="space-y-3 sm:space-y-4">
                  {messages.map(
                    (message, index) => (
                      <MessageBubble
                        key={message.id}
                        message={message}
                        integration={
                          integration
                        }
                        index={index}
                      />
                    )
                  )}
                </div>
              )}

            {/* Typing-style refresh indicator */}
            {isFetching &&
              !isLoading &&
              messages.length > 0 && (
                <div className="mt-5 flex justify-center">
                  <div className="flex items-center gap-2 rounded-full border border-base-border bg-base-panel-2/70 px-3 py-1.5 text-[9px] text-ink-faint backdrop-blur">
                    <span className="flex gap-0.5">
                      <span className="h-1 w-1 rounded-full bg-accent-violet animate-pulse" />
                      <span className="h-1 w-1 rounded-full bg-accent-violet animate-pulse [animation-delay:150ms]" />
                      <span className="h-1 w-1 rounded-full bg-accent-violet animate-pulse [animation-delay:300ms]" />
                    </span>
                    Syncing
                  </div>
                </div>
              )}
          </div>
        </div>

        {/* ---------------------------------------------------------------- */}
        {/* Human composer                                                    */}
        {/* ---------------------------------------------------------------- */}

        {isHumanAssigned ? (
          <div className="relative shrink-0 border-t border-base-border bg-base-panel/95 px-3 pb-3 pt-2.5 backdrop-blur-xl sm:px-5 sm:pb-4 sm:pt-3">
            <div className="mx-auto w-full max-w-4xl">
              <div className="mb-2 flex items-center gap-2 text-[10px] text-ink-muted">
                <span className="flex h-5 w-5 items-center justify-center rounded-lg bg-accent-violet/10 text-accent-violet">
                  <UserRoundCheck className="h-3 w-3" />
                </span>

                <span>
                  You are handling this conversation
                </span>

                <span className="ml-auto flex items-center gap-1 text-accent-green">
                  <span className="h-1.5 w-1.5 rounded-full bg-accent-green animate-pulse" />
                  Live
                </span>
              </div>

              <div className="relative rounded-2xl border border-base-border bg-base-panel-2/70 p-1.5 shadow-inner transition-all duration-200 focus-within:border-accent-violet/40 focus-within:shadow-lg focus-within:shadow-accent-violet/5">
                <div className="flex items-end gap-2">
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
                    placeholder="Write a reply…"
                    rows={1}
                    className="max-h-32 min-h-[42px] flex-1 resize-none bg-transparent px-3 py-2.5 text-sm leading-5 text-ink outline-none placeholder:text-ink-faint"
                  />

                  <button
                    onClick={sendReply}
                    disabled={
                      !reply.trim() ||
                      isSending
                    }
                    aria-label="Send reply"
                    className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-accent-violet to-accent-blue text-white shadow-lg shadow-accent-violet/10 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-xl hover:shadow-accent-violet/20 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:translate-y-0"
                  >
                    {isSending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Send className="h-4 w-4" />
                    )}
                  </button>
                </div>
              </div>

              <div className="mt-1.5 flex items-center justify-between gap-3 px-1">
                <p className="text-[9px] text-ink-faint">
                  <span className="hidden sm:inline">
                    Enter to send · Shift+Enter for
                    new line
                  </span>

                  <span className="sm:hidden">
                    Enter to send
                  </span>
                </p>

                <span className="text-[9px] tabular-nums text-ink-faint">
                  {reply.length > 0
                    ? `${reply.length}`
                    : ""}
                </span>
              </div>
            </div>
          </div>
        ) : (
          <div className="shrink-0 border-t border-base-border bg-base-panel/90 px-3 py-3 backdrop-blur-xl sm:px-5">
            <div className="mx-auto flex w-full max-w-4xl items-center justify-center gap-2 rounded-xl border border-base-border bg-base-panel-2/50 px-3 py-2.5 text-[10px] text-ink-faint">
              <Bot className="h-3.5 w-3.5 text-accent-violet" />

              <span>
                PersonaAI is currently handling this
                conversation.
              </span>
            </div>
          </div>
        )}
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Animation styles                                                    */}
      {/* ------------------------------------------------------------------ */}

      <style>{`
        @keyframes messageIn {
          from {
            opacity: 0;
            transform: translateY(8px) scale(0.985);
          }

          to {
            opacity: 1;
            transform: translateY(0) scale(1);
          }
        }

        @media (prefers-reduced-motion: reduce) {
          *,
          *::before,
          *::after {
            animation-duration: 0.01ms !important;
            animation-iteration-count: 1 !important;
            scroll-behavior: auto !important;
            transition-duration: 0.01ms !important;
          }
        }
      `}</style>
    </div>
  );
}
