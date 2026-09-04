"""OrderService.

create_order takes a snapshot of each product's current price into
`items` - see Order model's docstring for why. The payment workflow
here follows the spec directly:

  bank_transfer  -> AWAITING_CONFIRMATION once a receipt is attached,
                     owner calls confirm_payment() -> PAID
  pay_on_delivery -> AWAITING_DELIVERY_PAYMENT immediately
  cash            -> AWAITING_CASH_PAYMENT immediately

Every status change writes an OrderEvent - that's the "Timeline".

Inventory: stock is decremented with a single atomic
`UPDATE ... WHERE inventory >= :qty` per line item (see
_decrement_stock), not a read-then-write in Python — two concurrent
orders for the last unit of a product can't both succeed, because the
second UPDATE's WHERE clause simply matches zero rows. Cancelling or
refunding an order restocks it (_restock_items), once, guarded against
double-restock if an order is cancelled from an already-terminal state.
"""
import uuid
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import Customer
from app.models.notification import NotificationType
from app.models.order import DeliveryStatus, Order, OrderStatus, PaymentStatus
from app.models.order_event import OrderEvent
from app.models.payment_method import PaymentMethod, PaymentMethodType
from app.models.product import Product, ProductType
from app.services.customer_service import CustomerService
from app.services.notification_service import NotificationService

_RESTOCK_ON_STATUSES = {OrderStatus.CANCELLED, OrderStatus.REFUNDED}


class OrderService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _add_event(self, order: Order, event_type: str, note: str | None = None) -> None:
        self.db.add(OrderEvent(order_id=order.id, event_type=event_type, note=note))
        await self.db.flush()

    async def _decrement_stock(self, product: Product, quantity: int) -> None:
        """Single atomic UPDATE guarded by `inventory >= quantity` — this
        is what actually prevents overselling under concurrency. Two
        requests racing for the last unit can't both succeed: whichever
        UPDATE commits first drops inventory below `quantity`, so the
        second UPDATE's WHERE clause matches zero rows and we raise 409
        instead of silently overselling."""
        stmt = (
            update(Product)
            .where(Product.id == product.id, Product.inventory >= quantity)
            .values(inventory=Product.inventory - quantity)
        )
        result = await self.db.execute(stmt)
        if result.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Not enough stock for '{product.name}' (requested {quantity}).",
            )

    async def _restock_items(self, order: Order) -> None:
        """Returns each line item's quantity to inventory — only affects
        products still tracking finite stock (inventory IS NOT NULL);
        harmlessly no-ops for anything switched to unlimited since."""
        for item in order.items:
            await self.db.execute(
                update(Product)
                .where(Product.id == uuid.UUID(item["product_id"]), Product.inventory.is_not(None))
                .values(inventory=Product.inventory + item["quantity"])
            )
        total_units = sum(item["quantity"] for item in order.items)
        await self._add_event(order, "stock_restocked", f"{total_units} unit(s) returned to inventory")

    async def create_order(
        self,
        owner_id: uuid.UUID,
        customer: Customer,
        line_items: list[dict],
        conversation_id: uuid.UUID | None = None,
        payment_method_id: uuid.UUID | None = None,
        notes: str | None = None,
        recipient_name: str | None = None,
        recipient_phone: str | None = None,
        shipping_address: str | None = None,
    ) -> Order:
        if not line_items:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="An order needs at least one item")

        # Pass 1: look everything up and validate — including the
        # physical-item delivery-details check below — WITHOUT mutating
        # any stock yet. Getting this order wrong (decrement first,
        # validate after) would mean a rejected order — e.g. missing a
        # shipping address — could still have silently taken units out
        # of inventory for an order that was never actually created.
        products: list[tuple[Product, int]] = []
        has_physical_item = False
        for line in line_items:
            result = await self.db.execute(
                select(Product).where(Product.id == line["product_id"], Product.owner_id == owner_id)
            )
            product = result.scalar_one_or_none()
            if product is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail=f"Product {line['product_id']} not found"
                )
            quantity = int(line["quantity"])
            if quantity <= 0:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quantity must be positive")

            if product.product_type == ProductType.PHYSICAL:
                has_physical_item = True
            products.append((product, quantity))

        # An order with at least one physical item needs somewhere to
        # actually send it. Enforced here rather than only in the AI's
        # create_order tool, so a manually-created order from the
        # dashboard is held to the same standard — one rule either way,
        # not two that can drift apart. See Order model's docstring.
        if has_physical_item and not (recipient_name and shipping_address):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "This order includes a physical product and needs a recipient name and "
                    "shipping address before it can be created."
                ),
            )

        # Pass 2: now that everything's validated, actually build the
        # order — this is where stock gets decremented.
        items_snapshot = []
        total = Decimal("0")
        currency = "USD"
        for product, quantity in products:
            unit_price = product.price * (Decimal(1) - Decimal(product.discount_percent) / Decimal(100))
            subtotal = unit_price * quantity
            total += subtotal
            currency = product.currency
            items_snapshot.append(
                {
                    "product_id": str(product.id),
                    "name": product.name,
                    "quantity": quantity,
                    "unit_price": str(unit_price.quantize(Decimal("0.01"))),
                    "subtotal": str(subtotal.quantize(Decimal("0.01"))),
                }
            )

            if product.inventory is not None:
                await self._decrement_stock(product, quantity)

        payment_status = PaymentStatus.UNPAID
        payment_method = None
        if payment_method_id is not None:
            result = await self.db.execute(
                select(PaymentMethod).where(
                    PaymentMethod.id == payment_method_id, PaymentMethod.owner_id == owner_id
                )
            )
            payment_method = result.scalar_one_or_none()
            if payment_method is not None:
                payment_status = {
                    PaymentMethodType.BANK_TRANSFER: PaymentStatus.UNPAID,
                    PaymentMethodType.PAY_ON_DELIVERY: PaymentStatus.AWAITING_DELIVERY_PAYMENT,
                    PaymentMethodType.CASH: PaymentStatus.AWAITING_CASH_PAYMENT,
                }[payment_method.method_type]

        order = Order(
            owner_id=owner_id,
            customer_id=customer.id,
            conversation_id=conversation_id,
            payment_method_id=payment_method.id if payment_method else None,
            items=items_snapshot,
            total_amount=total.quantize(Decimal("0.01")),
            currency=currency,
            payment_status=payment_status,
            notes=notes,
            recipient_name=recipient_name,
            recipient_phone=recipient_phone,
            shipping_address=shipping_address,
        )
        self.db.add(order)
        await self.db.flush()
        await self._add_event(
            order, "order_created", f"{len(items_snapshot)} item(s), total {order.total_amount} {currency}"
        )

        await NotificationService(self.db).create(
            owner_id=owner_id,
            type_=NotificationType.NEW_ORDER,
            title="New order",
            body=f"New order for {order.total_amount} {currency} from {customer.display_name or 'a customer'}.",
            context={"order_id": str(order.id)},
        )

        await self.db.commit()
        await self.db.refresh(order)
        return order

    async def list_orders(
        self, owner_id: uuid.UUID, status_filter: OrderStatus | None = None, customer_id: uuid.UUID | None = None
    ) -> list[Order]:
        stmt = select(Order).where(Order.owner_id == owner_id)
        if status_filter is not None:
            stmt = stmt.where(Order.status == status_filter)
        if customer_id is not None:
            stmt = stmt.where(Order.customer_id == customer_id)
        stmt = stmt.order_by(Order.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_order(self, owner_id: uuid.UUID, order_id: uuid.UUID) -> Order:
        result = await self.db.execute(select(Order).where(Order.id == order_id, Order.owner_id == owner_id))
        order = result.scalar_one_or_none()
        if order is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        return order

    async def get_timeline(self, order_id: uuid.UUID) -> list[OrderEvent]:
        result = await self.db.execute(
            select(OrderEvent).where(OrderEvent.order_id == order_id).order_by(OrderEvent.created_at)
        )
        return list(result.scalars().all())

    async def update_status(self, owner_id: uuid.UUID, order_id: uuid.UUID, new_status: OrderStatus) -> Order:
        order = await self.get_order(owner_id, order_id)
        old_status = order.status
        order.status = new_status
        if new_status == OrderStatus.DELIVERED:
            order.delivery_status = DeliveryStatus.DELIVERED
        await self._add_event(order, "status_changed", f"{old_status.value} -> {new_status.value}")

        if new_status in _RESTOCK_ON_STATUSES and old_status not in _RESTOCK_ON_STATUSES:
            await self._restock_items(order)

        await self.db.commit()
        await self.db.refresh(order)
        return order

    async def attach_receipt(self, owner_id: uuid.UUID, order_id: uuid.UUID, file_id: str) -> Order:
        order = await self.get_order(owner_id, order_id)
        order.receipt_file_id = file_id
        order.payment_status = PaymentStatus.AWAITING_CONFIRMATION
        await self._add_event(order, "receipt_uploaded")
        await self.db.commit()

        await NotificationService(self.db).create(
            owner_id=owner_id,
            type_=NotificationType.PAYMENT_RECEIPT_UPLOADED,
            title="Payment receipt uploaded",
            body=f"A receipt was uploaded for order {order.id}. Review and confirm to mark it paid.",
            context={"order_id": str(order.id)},
        )
        await self.db.refresh(order)
        return order

    async def confirm_payment(self, owner_id: uuid.UUID, order_id: uuid.UUID) -> Order:
        order = await self.get_order(owner_id, order_id)
        order.payment_status = PaymentStatus.PAID
        if order.status == OrderStatus.PENDING:
            order.status = OrderStatus.CONFIRMED
        await self._add_event(order, "payment_confirmed")

        customer_result = await self.db.execute(select(Customer).where(Customer.id == order.customer_id))
        customer = customer_result.scalar_one_or_none()
        if customer is not None:
            await CustomerService(self.db).record_purchase(customer, order.total_amount)

        await self.db.commit()

        await NotificationService(self.db).create(
            owner_id=owner_id,
            type_=NotificationType.ORDER_PAYMENT_CONFIRMED,
            title="Payment confirmed",
            body=f"Order {order.id} is now marked as paid.",
            context={"order_id": str(order.id)},
        )
        await self.db.refresh(order)
        return order
