import { Navigate, Route, Routes } from "react-router-dom";
import { useAuthStore } from "@/lib/auth-store";
import AppShell from "@/components/layout/AppShell";
import LoginPage from "@/pages/LoginPage";
import RegisterPage from "@/pages/RegisterPage";
import DashboardPage from "@/pages/DashboardPage";
import AgentsPage from "@/pages/AgentsPage";
import ConversationsPage from "@/pages/ConversationsPage";
import ConversationDetailPage from "@/pages/ConversationDetailPage";
import KnowledgePage from "@/pages/KnowledgePage";
import MemoryPage from "@/pages/MemoryPage";
import IntegrationsPage from "@/pages/IntegrationsPage";
import SettingsPage from "@/pages/SettingsPage";
import AdminPage from "@/pages/AdminPage";
import BillingPage from "@/pages/BillingPage";
import BillingCallbackPage from "@/pages/BillingCallbackPage";
import WhatsAppOAuthCallbackPage from "@/pages/WhatsAppOAuthCallbackPage";
import AdminBillingPlansPage from "@/pages/AdminBillingPlansPage";
import OrdersPage from "@/pages/OrdersPage";
import PaymentMethodsPage from "@/pages/PaymentMethodsPage";
import CustomersPage from "@/pages/CustomersPage";
import ProductsPage from "@/pages/ProductsPage";
import AnalyticsPage from "@/pages/AnalyticsPage";
import NotificationsPage from "@/pages/NotificationsPage";
import ComingSoonPage from "@/pages/ComingSoonPage";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const accessToken = useAuthStore((s) => s.accessToken);
  if (!accessToken) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function AdminRoute({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user);
  if (!user?.is_platform_admin) return <Navigate to="/" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route
        path="/billing/callback"
        element={
          <ProtectedRoute>
            <BillingCallbackPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/integrations/whatsapp/callback"
        element={
          <ProtectedRoute>
            <WhatsAppOAuthCallbackPage />
          </ProtectedRoute>
        }
      />

      <Route
        path="/"
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="agents" element={<AgentsPage />} />
        <Route path="conversations" element={<ConversationsPage />} />
        <Route path="conversations/:conversationId" element={<ConversationDetailPage />} />
        <Route path="knowledge" element={<KnowledgePage />} />
        <Route path="memory" element={<MemoryPage />} />
        <Route path="integrations" element={<IntegrationsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="orders" element={<OrdersPage />} />
        <Route path="payment-methods" element={<PaymentMethodsPage />} />
        <Route path="customers" element={<CustomersPage />} />
        <Route path="products" element={<ProductsPage />} />
        <Route path="training" element={<ComingSoonPage title="Workflows" />} />
        <Route path="analytics" element={<AnalyticsPage />} />
        <Route path="notifications" element={<NotificationsPage />} />
        <Route path="billing" element={<BillingPage />} />
        <Route
          path="admin"
          element={
            <AdminRoute>
              <AdminPage />
            </AdminRoute>
          }
        />
        <Route
          path="admin/billing-plans"
          element={
            <AdminRoute>
              <AdminBillingPlansPage />
            </AdminRoute>
          }
        />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
