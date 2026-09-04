from app.services.product_service import ProductService
from app.services.tools.base import Tool, ToolContext


class SearchProductTool(Tool):
    name = "search_product"
    description = (
        "Search this business's product catalog by name, category, or description. "
        "Use this whenever a customer asks about a product, its price, or availability - "
        "never guess product details from memory."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What the customer is asking about, in their words"}
        },
        "required": ["query"],
    }

    async def execute(self, arguments: dict, context: ToolContext) -> dict:
        results = await ProductService(context.db).search(context.owner_id, arguments["query"], top_k=5)
        return {
            "products": [
                {
                    "id": str(product.id),
                    "name": product.name,
                    "description": product.description,
                    "price": str(product.price),
                    "currency": product.currency,
                    "in_stock": product.inventory is None or product.inventory > 0,
                    "inventory": product.inventory,
                }
                for product, _score in results
            ]
        }
