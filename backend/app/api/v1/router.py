from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin,
    admin_billing,
    agents,
    ai,
    analytics,
    audit_logs,
    auth,
    billing,
    conversations,
    customers,
    integrations,
    knowledge,
    memory,
    notifications,
    orders,
    payment_methods,
    products,
    routing,
    teach,
    telegram_webhook,
    users,
    whatsapp_webhook,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(ai.router)
api_router.include_router(agents.router)
api_router.include_router(routing.router)
api_router.include_router(knowledge.router)
api_router.include_router(memory.router)
api_router.include_router(teach.router)
api_router.include_router(integrations.router)
api_router.include_router(telegram_webhook.router)
api_router.include_router(whatsapp_webhook.router)
api_router.include_router(conversations.router)
api_router.include_router(products.router)
api_router.include_router(analytics.router)
api_router.include_router(notifications.router)
api_router.include_router(audit_logs.router)
api_router.include_router(admin.router)
api_router.include_router(billing.router)
api_router.include_router(admin_billing.router)
api_router.include_router(orders.router)
api_router.include_router(payment_methods.router)
api_router.include_router(customers.router)
