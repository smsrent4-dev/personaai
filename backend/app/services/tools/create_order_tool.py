import uuid

from fastapi import HTTPException

from app.services.order_service import OrderService
from app.services.tools.base import Tool, ToolContext


class CreateOrderTool(Tool):
    name = "create_order"
    description = (
        "Create an order for the customer. Only call this after the customer has clearly "
        "confirmed the specific product(s) and quantities they want to buy - never call this "
        "speculatively or before they've confirmed. Use product IDs returned by a prior "
        "search_product call, never invent one. If ANY item is a physical product, you must "
        "collect the recipient's name and full shipping address from the customer FIRST and "
        "pass them here - calling this without them for a physical item will fail with an "
        "error telling you to go collect them, so ask before calling rather than guessing."
    )
    parameters = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "The products and quantities the customer confirmed",
                "items": {
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "string", "description": "Exact product ID from search_product"},
                        "quantity": {"type": "integer", "description": "How many of this product"},
                    },
                    "required": ["product_id", "quantity"],
                },
            },
            "recipient_name": {
                "type": "string",
                "description": "Who to address the delivery to. Required if any item is a physical product.",
            },
            "recipient_phone": {
                "type": "string",
                "description": "A contact number for delivery, if the customer gave one (optional even for physical items).",
            },
            "shipping_address": {
                "type": "string",
                "description": "Full delivery address. Required if any item is a physical product.",
            },
        },
        "required": ["items"],
    }

    async def execute(self, arguments: dict, context: ToolContext) -> dict:
        try:
            line_items = [
                {"product_id": uuid.UUID(item["product_id"]), "quantity": item["quantity"]}
                for item in arguments["items"]
            ]
        except (KeyError, ValueError) as exc:
            return {"error": f"Invalid order items: {exc}"}

        try:
            order = await OrderService(context.db).create_order(
                owner_id=context.owner_id,
                customer=context.customer,
                line_items=line_items,
                conversation_id=context.conversation_id,
                recipient_name=arguments.get("recipient_name"),
                recipient_phone=arguments.get("recipient_phone"),
                shipping_address=arguments.get("shipping_address"),
            )
        except HTTPException as exc:
            # e.g. "Not enough stock for 'Hoodie' (requested 5)." or the
            # missing-shipping-address error from OrderService.create_order
            # — fed back to the model so it can explain the problem (or,
            # for the address case, just ask for it) rather than the
            # customer seeing a raw exception or a silently-lost order.
            return {"error": exc.detail}

        return {
            "order_id": str(order.id),
            "total_amount": str(order.total_amount),
            "currency": order.currency,
            "status": order.status.value,
            "payment_status": order.payment_status.value,
        }
