export type AgentType = "personal" | "sales" | "support" | "opportunity" | "custom";
export type AgentStatus = "active" | "paused" | "draft";

export interface Agent {
  id: string;
  name: string;
  description: string | null;
  avatar_url: string | null;
  agent_type: AgentType;
  instructions: string;
  model: string;
  temperature: number;
  permissions: Record<string, unknown>;
  status: AgentStatus;
  created_at: string;
  updated_at: string;
}

export type MemoryType = "fact" | "preference" | "event" | "conversation_summary";
export type MemorySource = "teach" | "conversation" | "manual";

export interface MemoryEntry {
  id: string;
  agent_id: string | null;
  memory_type: MemoryType;
  source: MemorySource;
  content: string;
  created_at: string;
}

export type KnowledgeSourceType = "pdf" | "docx" | "text" | "markdown" | "url" | "faq";
export type KnowledgeStatus = "pending" | "processing" | "ready" | "failed";

export interface KnowledgeDocument {
  id: string;
  agent_id: string | null;
  title: string;
  source_type: KnowledgeSourceType;
  source_url: string | null;
  status: KnowledgeStatus;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export type Platform =
  | "telegram"
  | "whatsapp"
  | "discord"
  | "instagram"
  | "messenger"
  | "slack"
  | "web_widget"
  | "voice";

export type IntegrationStatus = "active" | "disabled" | "error";

export interface Integration {
  id: string;
  platform: Platform;
  external_bot_id: string | null;
  external_bot_username: string | null;
  status: IntegrationStatus;
  error_message: string | null;
  settings: IntegrationSettings;
  created_at: string;
}

export interface IntegrationSettings {
  auto_reply?: boolean;
  typing_indicator?: boolean;
  read_receipts?: boolean;
  human_takeover?: boolean;
  default_agent_id?: string | null;
  business_hours?: {
    enabled?: boolean;
    timezone?: string;
    hours?: Record<string, [string, string]>;
    message?: string;
  } | null;
}

export interface WhatsAppProfile {
  id: string;
  whatsapp_business_account_id: string;
  phone_number_id: string;
  business_name: string | null;
  display_name: string | null;
  display_phone_number: string | null;
  quality_rating: string | null;
  messaging_tier: string | null;
  last_synced_at: string | null;
  created_at: string;
  updated_at: string;
}

export type ConversationStatus = "open" | "closed";

export interface Conversation {
  id: string;
  agent_id: string | null;
  platform: Platform;
  external_conversation_id: string;
  external_user_id: string | null;
  external_user_name: string | null;
  status: ConversationStatus;
  last_message_at: string | null;
  created_at: string;
}

export type MessageRole = "user" | "agent" | "system";
export type MessageType = "text" | "image" | "document" | "voice" | "location" | "video" | "contact" | "other";

export interface Message {
  id: string;
  role: MessageRole;
  message_type: MessageType;
  content: string | null;
  agent_id: string | null;
  media_file_id?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  platform_metadata?: Record<string, any> | null;
  created_at: string;
}

export type BillingInterval = "monthly" | "yearly";
export type SubscriptionStatus = "incomplete" | "active" | "past_due" | "canceled";

export interface BillingPlan {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  price_amount: number;
  currency: string;
  interval: BillingInterval;
  max_agents: number | null;
  max_messages_per_month: number | null;
  max_knowledge_documents: number | null;
  max_integrations: number | null;
  is_active: boolean;
  sort_order: number;
  created_at: string;
}

export interface Subscription {
  id: string;
  plan_id: string | null;
  status: SubscriptionStatus;
  current_period_end: string | null;
  canceled_at: string | null;
  created_at: string;
}

export type OrderStatus = "pending" | "confirmed" | "preparing" | "ready" | "delivered" | "cancelled" | "refunded";
export type OrderPaymentStatus =
  | "unpaid"
  | "awaiting_confirmation"
  | "awaiting_delivery_payment"
  | "awaiting_cash_payment"
  | "paid"
  | "refunded";
export type OrderDeliveryStatus = "not_started" | "in_progress" | "delivered" | "not_applicable";

export interface OrderLineItem {
  product_id: string;
  name: string;
  quantity: number;
  unit_price: string;
  subtotal: string;
}

export interface Order {
  id: string;
  customer_id: string;
  conversation_id: string | null;
  payment_method_id: string | null;
  items: OrderLineItem[];
  total_amount: number;
  currency: string;
  status: OrderStatus;
  payment_status: OrderPaymentStatus;
  delivery_status: OrderDeliveryStatus;
  notes: string | null;
  receipt_file_id: string | null;
  recipient_name: string | null;
  recipient_phone: string | null;
  shipping_address: string | null;
  created_at: string;
  updated_at: string;
}

export interface OrderEvent {
  id: string;
  event_type: string;
  note: string | null;
  created_at: string;
}

export type PaymentMethodType = "bank_transfer" | "cash" | "pay_on_delivery";

export interface PaymentMethod {
  id: string;
  method_type: PaymentMethodType;
  label: string;
  is_enabled: boolean;
  details: Record<string, string>;
  created_at: string;
}

export interface Customer {
  id: string;
  platform: string;
  external_user_id: string;
  display_name: string | null;
  lifetime_spend: number;
  order_count: number;
  last_interaction_at: string | null;
  preferred_language: string | null;
  preferred_payment_method: string | null;
  interests: string[];
  created_at: string;
}

export type ProductType = "physical" | "digital" | "service";
export type ProductStatus = "active" | "draft" | "archived";

export interface ProductVariant {
  name: string;
  price_delta: number;
  sku: string | null;
}

export interface Product {
  id: string;
  name: string;
  description: string | null;
  product_type: ProductType;
  price: string;
  currency: string;
  discount_percent: number;
  inventory: number | null;
  category: string | null;
  variants: ProductVariant[];
  images: string[];
  status: ProductStatus;
  created_at: string;
  updated_at: string;
}

export interface MessagesPerDay {
  date: string;
  count: number;
}

export interface MessagesByAgent {
  agent_id: string;
  agent_name: string;
  message_count: number;
}

export interface AnalyticsSummary {
  total_conversations: number;
  total_messages: number;
  active_agents: number;
  knowledge_documents_ready: number;
  active_products: number;
  messages_per_day: MessagesPerDay[];
  messages_by_agent: MessagesByAgent[];
}

export type NotificationType =
  | "new_conversation"
  | "knowledge_ingestion_failed"
  | "integration_error"
  | "new_order"
  | "receipt_uploaded"
  | "payment_confirmed";

export interface Notification {
  id: string;
  type: NotificationType;
  title: string;
  body: string | null;
  is_read: boolean;
  context: Record<string, unknown>;
  created_at: string;
}
