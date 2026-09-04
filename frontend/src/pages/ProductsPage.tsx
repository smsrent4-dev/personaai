import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Package,
  Plus,
  Loader2,
  X,
  ImagePlus,
  Trash2,
  Pencil,
} from "lucide-react";
import { toast } from "sonner";
import { api, apiErrorMessage } from "@/lib/api";
import type { Product, ProductStatus, ProductType } from "@/types";

const STATUS_STYLES: Record<ProductStatus, string> = {
  active: "bg-accent-green/15 text-accent-green",
  draft: "bg-accent-amber/15 text-accent-amber",
  archived: "bg-ink-faint/15 text-ink-faint",
};

const TYPE_OPTIONS: { value: ProductType; label: string }[] = [
  { value: "physical", label: "Physical" },
  { value: "digital", label: "Digital" },
  { value: "service", label: "Service" },
];

export default function ProductsPage() {
  const queryClient = useQueryClient();
  const gridRef = useRef<HTMLDivElement>(null);

  const [formOpen, setFormOpen] = useState(false);
  const [editingProduct, setEditingProduct] = useState<Product | null>(null);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [productType, setProductType] = useState<ProductType>("physical");
  const [price, setPrice] = useState("");
  const [category, setCategory] = useState("");
  const [inventory, setInventory] = useState("");
  const [variantsText, setVariantsText] = useState("");

  const { data: products = [], isLoading } = useQuery({
    queryKey: ["products"],
    queryFn: async () => (await api.get<Product[]>("/products")).data,
  });

  const resetForm = () => {
    setName("");
    setDescription("");
    setProductType("physical");
    setPrice("");
    setCategory("");
    setInventory("");
    setVariantsText("");
    setEditingProduct(null);
  };

  const closeForm = () => {
    resetForm();
    setFormOpen(false);
  };

  const openCreateForm = () => {
    resetForm();
    setFormOpen(true);
  };

  const openEditForm = (product: Product) => {
    setEditingProduct(product);

    setName(product.name);
    setDescription(product.description ?? "");
    setProductType(product.product_type);
    setPrice(String(product.price));
    setCategory(product.category ?? "");
    setInventory(
      product.inventory === null ? "" : String(product.inventory),
    );
    setVariantsText(
      product.variants
        .map((variant) => variant.name)
        .filter(Boolean)
        .join(", "),
    );

    setFormOpen(true);

    setTimeout(() => {
      gridRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    }, 100);
  };

  const create = useMutation({
    mutationFn: async () =>
      api.post<Product>("/products", {
        name,
        description: description || null,
        product_type: productType,
        price: Number(price),
        category: category || null,
        inventory: inventory === "" ? null : Number(inventory),
        variants: variantsText
          .split(",")
          .map((v) => v.trim())
          .filter(Boolean)
          .map((name) => ({
            name,
            price_delta: 0,
          })),
      }),

    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["products"] });

      toast.success("Product added");

      closeForm();

      setTimeout(() => {
        gridRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      }, 100);
    },

    onError: (err) =>
      toast.error(
        apiErrorMessage(err, "Couldn't add that product"),
      ),
  });

  const update = useMutation({
    mutationFn: async () => {
      if (!editingProduct) {
        throw new Error("No product selected");
      }

      return api.patch<Product>(
        `/products/${editingProduct.id}`,
        {
          name,
          description: description || null,
          price: Number(price),
          category: category || null,
          inventory: inventory === "" ? null : Number(inventory),
          variants: variantsText
            .split(",")
            .map((v) => v.trim())
            .filter(Boolean)
            .map((name) => ({
              name,
              price_delta: 0,
            })),
        },
      );
    },

    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["products"] });

      toast.success("Product updated");

      closeForm();
    },

    onError: (err) =>
      toast.error(
        apiErrorMessage(err, "Couldn't update that product"),
      ),
  });

  const deleteProduct = useMutation({
    mutationFn: async (productId: string) => {
      await api.delete(`/products/${productId}`);
    },

    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["products"] });
      toast.success("Product deleted");
    },

    onError: (err) =>
      toast.error(
        apiErrorMessage(err, "Couldn't delete that product"),
      ),
  });

  const uploadImage = useMutation({
    mutationFn: async ({
      productId,
      file,
    }: {
      productId: string;
      file: File;
    }) => {
      const formData = new FormData();
      formData.append("file", file);

      return api.post(
        `/products/${productId}/images`,
        formData,
        {
          headers: {
            "Content-Type": "multipart/form-data",
          },
        },
      );
    },

    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["products"],
      });

      toast.success("Photo added");
    },

    onError: (err) =>
      toast.error(
        apiErrorMessage(err, "Couldn't upload that photo"),
      ),
  });

  const removeImage = useMutation({
    mutationFn: async ({
      productId,
      imageUrl,
    }: {
      productId: string;
      imageUrl: string;
    }) =>
      api.delete(`/products/${productId}/images`, {
        params: {
          image_url: imageUrl,
        },
      }),

    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["products"],
      });

      toast.success("Photo removed");
    },

    onError: (err) =>
      toast.error(
        apiErrorMessage(err, "Couldn't remove that photo"),
      ),
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    if (!name.trim() || price === "") {
      return;
    }

    if (editingProduct) {
      update.mutate();
    } else {
      create.mutate();
    }
  };

  const formPending = create.isPending || update.isPending;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-xl font-semibold text-ink">
            Products
          </h1>

          <p className="text-sm text-ink-muted">
            What your agents can search, recommend, and sell. Add
            photos and sizes/colors so customers get useful product
            information.
          </p>
        </div>

        <button
          onClick={formOpen ? closeForm : openCreateForm}
          className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-accent-violet to-accent-blue px-4 py-2 text-sm font-medium text-white hover:opacity-90"
        >
          {formOpen ? (
            <X className="h-4 w-4" />
          ) : (
            <Plus className="h-4 w-4" />
          )}

          {formOpen
            ? "Cancel"
            : "Add Product"}
        </button>
      </div>

      {formOpen && (
        <form
          onSubmit={handleSubmit}
          className="panel space-y-3 p-4"
        >
          <div className="flex items-center justify-between">
            <h2 className="font-display text-base font-semibold text-ink">
              {editingProduct
                ? "Edit Product"
                : "Add Product"}
            </h2>

            {editingProduct && (
              <button
                type="button"
                onClick={closeForm}
                className="text-xs text-ink-muted hover:text-ink"
              >
                Cancel edit
              </button>
            )}
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <input
              value={name}
              onChange={(e) =>
                setName(e.target.value)
              }
              placeholder="Product name"
              className="rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:outline-none"
              required
            />

            <select
              value={productType}
              onChange={(e) =>
                setProductType(
                  e.target.value as ProductType,
                )
              }
              disabled={!!editingProduct}
              className="rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-sm text-ink focus:outline-none disabled:opacity-60"
            >
              {TYPE_OPTIONS.map((t) => (
                <option
                  key={t.value}
                  value={t.value}
                >
                  {t.label}
                </option>
              ))}
            </select>

            <input
              value={price}
              onChange={(e) =>
                setPrice(e.target.value)
              }
              type="number"
              min="0"
              step="0.01"
              placeholder="Price"
              className="rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:outline-none"
              required
            />

            <input
              value={category}
              onChange={(e) =>
                setCategory(e.target.value)
              }
              placeholder="Category (optional)"
              className="rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:outline-none"
            />

            <input
              value={inventory}
              onChange={(e) =>
                setInventory(e.target.value)
              }
              type="number"
              min="0"
              placeholder="Inventory (blank = unlimited)"
              className="rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:outline-none"
            />

            <input
              value={variantsText}
              onChange={(e) =>
                setVariantsText(e.target.value)
              }
              placeholder="Sizes/colors, comma-separated"
              className="rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:outline-none"
            />

            <textarea
              value={description}
              onChange={(e) =>
                setDescription(e.target.value)
              }
              placeholder="Description — this is what the AI searches against"
              rows={2}
              className="rounded-lg border border-base-border bg-base-panel-2 px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:outline-none sm:col-span-2"
            />
          </div>

          <button
            type="submit"
            disabled={formPending}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-accent-violet to-accent-blue px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60 sm:w-auto"
          >
            {formPending && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}

            {editingProduct
              ? "Save changes"
              : "Save product"}
          </button>

          {!editingProduct && (
            <p className="text-xs text-ink-faint">
              Currency follows your business default
              (NGN).
            </p>
          )}
        </form>
      )}

      <div
        ref={gridRef}
        className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
      >
        {isLoading && (
          <p className="text-sm text-ink-faint">
            Loading…
          </p>
        )}

        {!isLoading && products.length === 0 && (
          <div className="panel col-span-full flex flex-col items-center gap-2 p-10 text-center">
            <Package className="h-6 w-6 text-ink-faint" />

            <p className="text-sm text-ink-muted">
              No products yet — add one, or teach your agents
              about them directly.
            </p>
          </div>
        )}

        {products.map((p) => (
          <ProductCard
            key={p.id}
            product={p}
            onEdit={() => openEditForm(p)}
            onDelete={() => {
              if (
                window.confirm(
                  `Delete "${p.name}"? This cannot be undone.`,
                )
              ) {
                deleteProduct.mutate(p.id);
              }
            }}
            onUpload={(file) =>
              uploadImage.mutate({
                productId: p.id,
                file,
              })
            }
            onRemoveImage={(url) =>
              removeImage.mutate({
                productId: p.id,
                imageUrl: url,
              })
            }
            uploading={uploadImage.isPending}
          />
        ))}
      </div>
    </div>
  );
}

function ProductCard({
  product: p,
  onEdit,
  onDelete,
  onUpload,
  onRemoveImage,
  uploading,
}: {
  product: Product;
  onEdit: () => void;
  onDelete: () => void;
  onUpload: (file: File) => void;
  onRemoveImage: (url: string) => void;
  uploading: boolean;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const outOfStock =
    p.inventory !== null && p.inventory === 0;

  return (
    <div className="panel flex flex-col overflow-hidden p-4">
      <div className="mb-3 -mx-4 -mt-4">
        {p.images.length > 0 ? (
          <div className="group relative">
            <img
              src={p.images[0]}
              alt={p.name}
              className={`h-40 w-full object-cover ${
                outOfStock ? "opacity-60" : ""
              }`}
            />

            {outOfStock && (
              <span className="absolute bottom-2 left-2 rounded-full bg-black/70 px-2 py-1 text-[10px] font-medium text-white">
                Out of stock
              </span>
            )}

            <button
              onClick={() =>
                onRemoveImage(p.images[0])
              }
              title="Remove photo"
              className="absolute right-2 top-2 flex h-7 w-7 items-center justify-center rounded-full bg-black/50 text-white opacity-0 transition-opacity group-hover:opacity-100"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() =>
              fileInputRef.current?.click()
            }
            disabled={uploading}
            className="flex h-40 w-full flex-col items-center justify-center gap-1.5 bg-base-panel-2 text-ink-faint transition-colors hover:text-accent-violet"
          >
            {uploading ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : (
              <ImagePlus className="h-5 w-5" />
            )}

            <span className="text-xs">
              Add photo
            </span>
          </button>
        )}

        <input
          ref={fileInputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp,image/gif"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];

            if (file) {
              onUpload(file);
            }

            e.target.value = "";
          }}
        />
      </div>

      <div className="mb-2 flex items-start justify-between gap-2">
        <p className="truncate text-sm font-semibold text-ink">
          {p.name}
        </p>

        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium capitalize ${STATUS_STYLES[p.status]}`}
        >
          {p.status}
        </span>
      </div>

      {p.description && (
        <p className="mb-2 line-clamp-2 text-xs text-ink-muted">
          {p.description}
        </p>
      )}

      {p.variants.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1">
          {p.variants.map((v, i) => (
            <span
              key={i}
              className="rounded-full bg-base-panel-2 px-2 py-0.5 text-[10px] text-ink-muted"
            >
              {v.name}
            </span>
          ))}
        </div>
      )}

      <div className="mt-auto flex items-center justify-between text-xs">
        <span className="font-display text-base font-semibold text-ink">
          {new Intl.NumberFormat(undefined, {
            style: "currency",
            currency: p.currency,
          }).format(Number(p.price))}
        </span>

        <span
          className={
            outOfStock
              ? "font-medium text-accent-red"
              : "text-ink-faint"
          }
        >
          {p.inventory === null
            ? "Unlimited"
            : outOfStock
              ? "Out of stock"
              : `${p.inventory} in stock`}
        </span>
      </div>

      {p.category && (
        <p className="mt-2 text-[11px] text-ink-faint">
          {p.category}
        </p>
      )}

      <div className="mt-3 flex gap-2 border-t border-base-border pt-3">
        <button
          type="button"
          onClick={onEdit}
          className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-base-panel-2 px-3 py-2 text-xs font-medium text-ink transition-colors hover:bg-base-border"
        >
          <Pencil className="h-3.5 w-3.5" />
          Edit
        </button>

        <button
          type="button"
          onClick={() =>
            fileInputRef.current?.click()
          }
          disabled={uploading}
          className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-base-panel-2 px-3 py-2 text-xs font-medium text-ink transition-colors hover:bg-base-border disabled:opacity-60"
        >
          <ImagePlus className="h-3.5 w-3.5" />
          {p.images.length > 0
            ? "Change photo"
            : "Add photo"}
        </button>

        <button
          type="button"
          onClick={onDelete}
          className="flex items-center justify-center rounded-lg bg-red-500/10 px-3 py-2 text-xs font-medium text-red-500 transition-colors hover:bg-red-500/20"
          title="Delete product"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}