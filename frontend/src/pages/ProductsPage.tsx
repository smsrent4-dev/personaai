import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Package,
  Plus,
  Loader2,
  X,
  ImagePlus,
  Trash2,
  Pencil,
  Search,
  Sparkles,
  Boxes,
  Layers3,
  ChevronDown,
  SlidersHorizontal,
  Tag,
  CheckCircle2,
  Archive,
  FileEdit,
} from "lucide-react";
import { toast } from "sonner";
import { api, apiErrorMessage } from "@/lib/api";
import type { Product, ProductStatus, ProductType } from "@/types";

const STATUS_STYLES: Record<
  ProductStatus,
  {
    badge: string;
    icon: typeof CheckCircle2;
  }
> = {
  active: {
    badge: "bg-accent-green/10 text-accent-green ring-1 ring-accent-green/20",
    icon: CheckCircle2,
  },
  draft: {
    badge: "bg-accent-amber/10 text-accent-amber ring-1 ring-accent-amber/20",
    icon: FileEdit,
  },
  archived: {
    badge: "bg-ink-faint/10 text-ink-faint ring-1 ring-ink-faint/20",
    icon: Archive,
  },
};

const TYPE_OPTIONS: { value: ProductType; label: string }[] = [
  { value: "physical", label: "Physical" },
  { value: "digital", label: "Digital" },
  { value: "service", label: "Service" },
];

type FilterValue = "all" | ProductStatus;

export default function ProductsPage() {
  const queryClient = useQueryClient();
  const gridRef = useRef<HTMLDivElement>(null);

  const [formOpen, setFormOpen] = useState(false);
  const [editingProduct, setEditingProduct] = useState<Product | null>(null);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [productType, setProductType] =
    useState<ProductType>("physical");
  const [price, setPrice] = useState("");
  const [category, setCategory] = useState("");
  const [inventory, setInventory] = useState("");
  const [variantsText, setVariantsText] = useState("");

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] =
    useState<FilterValue>("all");

  const {
    data: products = [],
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ["products"],
    queryFn: async () =>
      (await api.get<Product[]>("/products")).data,
  });

  const filteredProducts = useMemo(() => {
    const query = search.trim().toLowerCase();

    return products.filter((product) => {
      const matchesSearch =
        !query ||
        product.name.toLowerCase().includes(query) ||
        product.description?.toLowerCase().includes(query) ||
        product.category?.toLowerCase().includes(query) ||
        product.variants.some((variant) =>
          variant.name.toLowerCase().includes(query),
        );

      const matchesStatus =
        statusFilter === "all" ||
        product.status === statusFilter;

      return matchesSearch && matchesStatus;
    });
  }, [products, search, statusFilter]);

  const activeCount = products.filter(
    (product) => product.status === "active",
  ).length;

  const draftCount = products.filter(
    (product) => product.status === "draft",
  ).length;

  const outOfStockCount = products.filter(
    (product) =>
      product.inventory !== null &&
      product.inventory === 0,
  ).length;

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

    window.setTimeout(() => {
      window.scrollTo({
        top: 0,
        behavior: "smooth",
      });
    }, 50);
  };

  const openEditForm = (product: Product) => {
    setEditingProduct(product);

    setName(product.name);
    setDescription(product.description ?? "");
    setProductType(product.product_type);
    setPrice(String(product.price));
    setCategory(product.category ?? "");

    setInventory(
      product.inventory === null
        ? ""
        : String(product.inventory),
    );

    setVariantsText(
      product.variants
        .map((variant) => variant.name)
        .filter(Boolean)
        .join(", "),
    );

    setFormOpen(true);

    window.setTimeout(() => {
      window.scrollTo({
        top: 0,
        behavior: "smooth",
      });
    }, 100);
  };

  const create = useMutation({
    mutationFn: async () =>
      api.post<Product>("/products", {
        name: name.trim(),
        description: description.trim() || null,
        product_type: productType,
        price: Number(price),
        category: category.trim() || null,
        inventory:
          inventory === ""
            ? null
            : Number(inventory),
        variants: variantsText
          .split(",")
          .map((v) => v.trim())
          .filter(Boolean)
          .map((variantName) => ({
            name: variantName,
            price_delta: 0,
          })),
      }),

    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["products"],
      });

      toast.success("Product added successfully");

      closeForm();

      window.setTimeout(() => {
        gridRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      }, 100);
    },

    onError: (err) =>
      toast.error(
        apiErrorMessage(
          err,
          "Couldn't add that product",
        ),
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
          name: name.trim(),
          description: description.trim() || null,
          price: Number(price),
          category: category.trim() || null,
          inventory:
            inventory === ""
              ? null
              : Number(inventory),
          variants: variantsText
            .split(",")
            .map((v) => v.trim())
            .filter(Boolean)
            .map((variantName) => ({
              name: variantName,
              price_delta: 0,
            })),
        },
      );
    },

    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["products"],
      });

      toast.success("Product updated successfully");

      closeForm();
    },

    onError: (err) =>
      toast.error(
        apiErrorMessage(
          err,
          "Couldn't update that product",
        ),
      ),
  });

  const deleteProduct = useMutation({
    mutationFn: async (productId: string) => {
      await api.delete(`/products/${productId}`);
    },

    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["products"],
      });

      toast.success("Product deleted");
    },

    onError: (err) =>
      toast.error(
        apiErrorMessage(
          err,
          "Couldn't delete that product",
        ),
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

      toast.success("Product photo added");
    },

    onError: (err) =>
      toast.error(
        apiErrorMessage(
          err,
          "Couldn't upload that photo",
        ),
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

      toast.success("Product photo removed");
    },

    onError: (err) =>
      toast.error(
        apiErrorMessage(
          err,
          "Couldn't remove that photo",
        ),
      ),
  });

  const handleSubmit = (
    e: React.FormEvent,
  ) => {
    e.preventDefault();

    const numericPrice = Number(price);

    if (!name.trim()) {
      toast.error("Product name is required");
      return;
    }

    if (
      price === "" ||
      !Number.isFinite(numericPrice) ||
      numericPrice < 0
    ) {
      toast.error("Enter a valid product price");
      return;
    }

    if (
      inventory !== "" &&
      (!Number.isFinite(Number(inventory)) ||
        Number(inventory) < 0)
    ) {
      toast.error("Enter a valid inventory value");
      return;
    }

    if (editingProduct) {
      update.mutate();
    } else {
      create.mutate();
    }
  };

  const formPending =
    create.isPending || update.isPending;

  return (
    <div className="relative mx-auto w-full max-w-[1600px] space-y-5 pb-8 sm:space-y-6">
      {/* Ambient background decoration */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -top-20 right-0 -z-10 h-64 w-64 rounded-full bg-accent-violet/10 blur-3xl"
      />

      <div
        aria-hidden="true"
        className="pointer-events-none absolute left-0 top-80 -z-10 h-52 w-52 rounded-full bg-accent-blue/5 blur-3xl"
      />

      {/* Header */}
      <section className="flex flex-col gap-4 sm:gap-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <div className="mb-2 flex items-center gap-2">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-accent-violet/20 to-accent-blue/20 ring-1 ring-white/5">
              <Package className="h-4 w-4 text-accent-violet" />
            </div>

            <span className="text-xs font-medium uppercase tracking-[0.18em] text-ink-faint">
              Catalog
            </span>
          </div>

          <h1 className="font-display text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
            Products
          </h1>

          <p className="mt-1.5 max-w-2xl text-sm leading-6 text-ink-muted">
            Manage what your AI agents can discover,
            recommend, and sell. Add photos, variants,
            pricing, and inventory in one place.
          </p>
        </div>

        <button
          type="button"
          onClick={
            formOpen
              ? closeForm
              : openCreateForm
          }
          className="group inline-flex w-full shrink-0 items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-accent-violet to-accent-blue px-4 py-3 text-sm font-semibold text-white shadow-lg shadow-accent-violet/10 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-xl hover:shadow-accent-violet/20 active:translate-y-0 sm:w-auto"
        >
          {formOpen ? (
            <X className="h-4 w-4 transition-transform duration-300 group-hover:rotate-90" />
          ) : (
            <Plus className="h-4 w-4 transition-transform duration-300 group-hover:rotate-90" />
          )}

          {formOpen
            ? "Close form"
            : "Add product"}
        </button>
      </section>

      {/* Overview cards */}
      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <OverviewCard
          icon={Boxes}
          label="Total products"
          value={products.length}
          accent="violet"
        />

        <OverviewCard
          icon={CheckCircle2}
          label="Active"
          value={activeCount}
          accent="green"
        />

        <OverviewCard
          icon={FileEdit}
          label="Drafts"
          value={draftCount}
          accent="amber"
        />

        <OverviewCard
          icon={Package}
          label="Out of stock"
          value={outOfStockCount}
          accent="red"
        />
      </section>

      {/* Create / edit form */}
      {formOpen && (
        <ProductForm
          editingProduct={editingProduct}
          name={name}
          description={description}
          productType={productType}
          price={price}
          category={category}
          inventory={inventory}
          variantsText={variantsText}
          formPending={formPending}
          onSubmit={handleSubmit}
          onClose={closeForm}
          setName={setName}
          setDescription={setDescription}
          setProductType={setProductType}
          setPrice={setPrice}
          setCategory={setCategory}
          setInventory={setInventory}
          setVariantsText={setVariantsText}
        />
      )}

      {/* Toolbar */}
      <section
        ref={gridRef}
        className="panel overflow-hidden"
      >
        <div className="flex flex-col gap-3 border-b border-base-border p-3 sm:p-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex min-w-0 items-center gap-3">
            <div className="hidden h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-base-panel-2 sm:flex">
              <Layers3 className="h-4 w-4 text-ink-muted" />
            </div>

            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-ink">
                Product catalog
              </h2>

              <p className="text-xs text-ink-faint">
                {filteredProducts.length}{" "}
                {filteredProducts.length === 1
                  ? "product"
                  : "products"}{" "}
                shown
              </p>
            </div>
          </div>

          <div className="flex w-full flex-col gap-2 sm:flex-row lg:w-auto">
            {/* Search */}
            <div className="relative min-w-0 flex-1 sm:min-w-[240px] lg:w-[280px]">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />

              <input
                value={search}
                onChange={(e) =>
                  setSearch(e.target.value)
                }
                placeholder="Search products..."
                className="h-10 w-full rounded-xl border border-base-border bg-base-panel-2 pl-9 pr-3 text-sm text-ink outline-none transition-all placeholder:text-ink-faint focus:border-accent-violet/50 focus:ring-2 focus:ring-accent-violet/10"
              />
            </div>

            {/* Filter */}
            <div className="relative">
              <SlidersHorizontal className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-faint" />

              <select
                value={statusFilter}
                onChange={(e) =>
                  setStatusFilter(
                    e.target.value as FilterValue,
                  )
                }
                className="h-10 w-full appearance-none rounded-xl border border-base-border bg-base-panel-2 pl-9 pr-9 text-sm text-ink outline-none transition-all focus:border-accent-violet/50 focus:ring-2 focus:ring-accent-violet/10 sm:w-[150px]"
              >
                <option value="all">
                  All statuses
                </option>
                <option value="active">
                  Active
                </option>
                <option value="draft">
                  Draft
                </option>
                <option value="archived">
                  Archived
                </option>
              </select>

              <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-faint" />
            </div>
          </div>
        </div>

        {/* Loading */}
        {isLoading && (
          <div className="grid grid-cols-1 gap-4 p-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {Array.from({ length: 6 }).map(
              (_, index) => (
                <ProductSkeleton
                  key={index}
                  delay={index * 70}
                />
              ),
            )}
          </div>
        )}

        {/* Error */}
        {!isLoading && isError && (
          <div className="flex min-h-[320px] flex-col items-center justify-center px-5 py-12 text-center">
            <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-accent-red/10">
              <Package className="h-5 w-5 text-accent-red" />
            </div>

            <h3 className="text-sm font-semibold text-ink">
              Couldn't load your products
            </h3>

            <p className="mt-1 max-w-sm text-xs leading-5 text-ink-muted">
              Something went wrong while loading your
              catalog. Try refreshing the list.
            </p>

            <button
              type="button"
              onClick={() => refetch()}
              className="mt-4 rounded-lg bg-base-panel-2 px-4 py-2 text-xs font-medium text-ink transition-colors hover:bg-base-border"
            >
              Try again
            </button>
          </div>
        )}

        {/* Empty state */}
        {!isLoading &&
          !isError &&
          products.length === 0 && (
            <EmptyProductsState
              onAdd={openCreateForm}
            />
          )}

        {/* No search results */}
        {!isLoading &&
          !isError &&
          products.length > 0 &&
          filteredProducts.length === 0 && (
            <div className="flex min-h-[280px] flex-col items-center justify-center px-5 py-12 text-center">
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-base-panel-2">
                <Search className="h-5 w-5 text-ink-faint" />
              </div>

              <h3 className="text-sm font-semibold text-ink">
                No matching products
              </h3>

              <p className="mt-1 max-w-sm text-xs leading-5 text-ink-muted">
                Try a different product name,
                category, variant, or status.
              </p>

              <button
                type="button"
                onClick={() => {
                  setSearch("");
                  setStatusFilter("all");
                }}
                className="mt-4 rounded-lg bg-base-panel-2 px-4 py-2 text-xs font-medium text-ink transition-colors hover:bg-base-border"
              >
                Clear filters
              </button>
            </div>
          )}

        {/* Products */}
        {!isLoading &&
          !isError &&
          filteredProducts.length > 0 && (
            <div className="grid grid-cols-1 gap-4 p-3 sm:grid-cols-2 sm:p-4 xl:grid-cols-3 2xl:grid-cols-4">
              {filteredProducts.map(
                (product, index) => (
                  <ProductCard
                    key={product.id}
                    product={product}
                    index={index}
                    onEdit={() =>
                      openEditForm(product)
                    }
                    onDelete={() => {
                      const confirmed =
                        window.confirm(
                          `Delete "${product.name}"? This cannot be undone.`,
                        );

                      if (confirmed) {
                        deleteProduct.mutate(
                          product.id,
                        );
                      }
                    }}
                    onUpload={(file) =>
                      uploadImage.mutate({
                        productId: product.id,
                        file,
                      })
                    }
                    onRemoveImage={(url) =>
                      removeImage.mutate({
                        productId: product.id,
                        imageUrl: url,
                      })
                    }
                    uploading={
                      uploadImage.isPending
                    }
                    deleting={
                      deleteProduct.isPending &&
                      deleteProduct.variables ===
                        product.id
                    }
                  />
                ),
              )}
            </div>
          )}
      </section>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Overview Card                                                              */
/* -------------------------------------------------------------------------- */

function OverviewCard({
  icon: Icon,
  label,
  value,
  accent,
}: {
  icon: typeof Boxes;
  label: string;
  value: number;
  accent: "violet" | "green" | "amber" | "red";
}) {
  const accentStyles = {
    violet:
      "bg-accent-violet/10 text-accent-violet ring-accent-violet/20",
    green:
      "bg-accent-green/10 text-accent-green ring-accent-green/20",
    amber:
      "bg-accent-amber/10 text-accent-amber ring-accent-amber/20",
    red:
      "bg-accent-red/10 text-accent-red ring-accent-red/20",
  };

  return (
    <div className="panel group relative overflow-hidden p-3.5 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-lg sm:p-4">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-5 -top-5 h-16 w-16 rounded-full bg-accent-violet/5 blur-2xl transition-transform duration-500 group-hover:scale-150"
      />

      <div className="flex items-center gap-3">
        <div
          className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ring-1 ${accentStyles[accent]}`}
        >
          <Icon className="h-4 w-4" />
        </div>

        <div className="min-w-0">
          <p className="truncate text-[11px] font-medium text-ink-faint">
            {label}
          </p>

          <p className="mt-0.5 font-display text-lg font-semibold text-ink">
            {value}
          </p>
        </div>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Product Form                                                               */
/* -------------------------------------------------------------------------- */

function ProductForm({
  editingProduct,
  name,
  description,
  productType,
  price,
  category,
  inventory,
  variantsText,
  formPending,
  onSubmit,
  onClose,
  setName,
  setDescription,
  setProductType,
  setPrice,
  setCategory,
  setInventory,
  setVariantsText,
}: {
  editingProduct: Product | null;
  name: string;
  description: string;
  productType: ProductType;
  price: string;
  category: string;
  inventory: string;
  variantsText: string;
  formPending: boolean;
  onSubmit: (e: React.FormEvent) => void;
  onClose: () => void;
  setName: (value: string) => void;
  setDescription: (value: string) => void;
  setProductType: (value: ProductType) => void;
  setPrice: (value: string) => void;
  setCategory: (value: string) => void;
  setInventory: (value: string) => void;
  setVariantsText: (value: string) => void;
}) {
  return (
    <form
      onSubmit={onSubmit}
      className="panel relative overflow-hidden p-4 sm:p-5 lg:p-6"
    >
      {/* Form glow */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-20 -top-20 h-48 w-48 rounded-full bg-accent-violet/10 blur-3xl"
      />

      <div className="relative">
        <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-accent-violet/15 to-accent-blue/15 ring-1 ring-white/5">
              {editingProduct ? (
                <Pencil className="h-4 w-4 text-accent-violet" />
              ) : (
                <Sparkles className="h-4 w-4 text-accent-violet" />
              )}
            </div>

            <div>
              <h2 className="font-display text-base font-semibold text-ink sm:text-lg">
                {editingProduct
                  ? "Edit product"
                  : "Add a new product"}
              </h2>

              <p className="mt-0.5 text-xs leading-5 text-ink-muted">
                {editingProduct
                  ? "Update your product information and catalog details."
                  : "Create a product your AI agents can search and recommend."}
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="self-start rounded-lg p-2 text-ink-faint transition-colors hover:bg-base-panel-2 hover:text-ink"
            aria-label="Close product form"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <FormField
            label="Product name"
            required
          >
            <input
              value={name}
              onChange={(e) =>
                setName(e.target.value)
              }
              placeholder="e.g. Premium Black Hoodie"
              className={inputClassName}
              required
              autoComplete="off"
            />
          </FormField>

          <FormField label="Product type">
            <select
              value={productType}
              onChange={(e) =>
                setProductType(
                  e.target.value as ProductType,
                )
              }
              disabled={!!editingProduct}
              className={`${inputClassName} disabled:cursor-not-allowed disabled:opacity-50`}
            >
              {TYPE_OPTIONS.map((type) => (
                <option
                  key={type.value}
                  value={type.value}
                >
                  {type.label}
                </option>
              ))}
            </select>
          </FormField>

          <FormField
            label="Price"
            required
            hint="Currency follows your business default."
          >
            <input
              value={price}
              onChange={(e) =>
                setPrice(e.target.value)
              }
              type="number"
              min="0"
              step="0.01"
              placeholder="0.00"
              className={inputClassName}
              required
              inputMode="decimal"
            />
          </FormField>

          <FormField label="Category">
            <input
              value={category}
              onChange={(e) =>
                setCategory(e.target.value)
              }
              placeholder="e.g. Clothing"
              className={inputClassName}
              autoComplete="off"
            />
          </FormField>

          <FormField
            label="Inventory"
            hint="Leave blank for unlimited inventory."
          >
            <input
              value={inventory}
              onChange={(e) =>
                setInventory(e.target.value)
              }
              type="number"
              min="0"
              step="1"
              placeholder="e.g. 25"
              className={inputClassName}
              inputMode="numeric"
            />
          </FormField>

          <FormField
            label="Variants"
            hint="Separate sizes, colors, or options with commas."
          >
            <input
              value={variantsText}
              onChange={(e) =>
                setVariantsText(e.target.value)
              }
              placeholder="Small, Medium, Large, Black"
              className={inputClassName}
              autoComplete="off"
            />
          </FormField>

          <div className="md:col-span-2">
            <FormField
              label="Description"
              hint="Your AI agents use this information when answering customers."
            >
              <textarea
                value={description}
                onChange={(e) =>
                  setDescription(e.target.value)
                }
                placeholder="Describe the product, key features, materials, use cases, and anything customers should know..."
                rows={5}
                className={`${inputClassName} resize-y py-3`}
              />
            </FormField>
          </div>
        </div>

        {/* Preview information */}
        <div className="mt-5 rounded-xl border border-base-border bg-base-panel-2/60 p-3">
          <div className="flex items-start gap-2.5">
            <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-accent-violet" />

            <div>
              <p className="text-xs font-medium text-ink">
                AI-ready catalog data
              </p>

              <p className="mt-0.5 text-[11px] leading-5 text-ink-muted">
                Clear descriptions, variants, categories,
                pricing, and images give your agents better
                product information when responding to
                customers.
              </p>
            </div>
          </div>
        </div>

        <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-base-border bg-base-panel-2 px-4 py-2.5 text-sm font-medium text-ink transition-all hover:bg-base-border"
          >
            Cancel
          </button>

          <button
            type="submit"
            disabled={formPending}
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-accent-violet to-accent-blue px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-accent-violet/10 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-accent-violet/20 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {formPending && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}

            {editingProduct
              ? "Save changes"
              : "Create product"}
          </button>
        </div>
      </div>
    </form>
  );
}

/* -------------------------------------------------------------------------- */
/* Form Field                                                                 */
/* -------------------------------------------------------------------------- */

const inputClassName =
  "w-full rounded-xl border border-base-border bg-base-panel-2 px-3.5 py-2.5 text-sm text-ink outline-none transition-all duration-200 placeholder:text-ink-faint focus:border-accent-violet/50 focus:ring-2 focus:ring-accent-violet/10";

function FormField({
  label,
  required,
  hint,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-ink">
          {label}
          {required && (
            <span className="ml-1 text-accent-violet">
              *
            </span>
          )}
        </span>
      </div>

      {children}

      {hint && (
        <p className="mt-1.5 text-[10px] leading-4 text-ink-faint">
          {hint}
        </p>
      )}
    </label>
  );
}

/* -------------------------------------------------------------------------- */
/* Product Card                                                               */
/* -------------------------------------------------------------------------- */

function ProductCard({
  product: p,
  index,
  onEdit,
  onDelete,
  onUpload,
  onRemoveImage,
  uploading,
  deleting,
}: {
  product: Product;
  index: number;
  onEdit: () => void;
  onDelete: () => void;
  onUpload: (file: File) => void;
  onRemoveImage: (url: string) => void;
  uploading: boolean;
  deleting: boolean;
}) {
  const fileInputRef =
    useRef<HTMLInputElement>(null);

  const outOfStock =
    p.inventory !== null &&
    p.inventory === 0;

  const status =
    STATUS_STYLES[p.status];

  const StatusIcon = status.icon;

  const formattedPrice =
    new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: p.currency,
      maximumFractionDigits: 2,
    }).format(Number(p.price));

  return (
    <article
      className="group relative flex min-w-0 flex-col overflow-hidden rounded-2xl border border-base-border bg-base-panel transition-all duration-300 ease-out hover:-translate-y-1 hover:border-accent-violet/20 hover:shadow-2xl hover:shadow-black/10 motion-reduce:transition-none motion-reduce:hover:translate-y-0"
      style={{
        animationDelay: `${Math.min(
          index * 45,
          350,
        )}ms`,
      }}
    >
      {/* Product image */}
      <div className="relative aspect-[4/3] w-full overflow-hidden bg-base-panel-2">
        {p.images.length > 0 ? (
          <>
            <img
              src={p.images[0]}
              alt={p.name}
              loading="lazy"
              className={`h-full w-full object-cover transition duration-700 ease-out group-hover:scale-105 ${
                outOfStock
                  ? "opacity-60 grayscale-[15%]"
                  : ""
              }`}
            />

            {/* Image overlay */}
            <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/50 via-transparent to-black/10 opacity-60 transition-opacity duration-300 group-hover:opacity-80" />

            {outOfStock && (
              <span className="absolute bottom-3 left-3 rounded-full bg-black/70 px-2.5 py-1 text-[10px] font-semibold text-white backdrop-blur-md">
                Out of stock
              </span>
            )}

            <button
              type="button"
              onClick={() =>
                onRemoveImage(p.images[0])
              }
              disabled={deleting}
              title="Remove photo"
              aria-label={`Remove photo from ${p.name}`}
              className="absolute right-3 top-3 flex h-8 w-8 items-center justify-center rounded-full border border-white/10 bg-black/50 text-white opacity-100 backdrop-blur-md transition-all duration-200 hover:scale-105 hover:bg-red-500/80 disabled:cursor-not-allowed disabled:opacity-50 sm:opacity-0 sm:group-hover:opacity-100"
            >
              {deleting ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Trash2 className="h-3.5 w-3.5" />
              )}
            </button>

            {p.images.length > 1 && (
              <span className="absolute bottom-3 right-3 rounded-full bg-black/60 px-2 py-1 text-[10px] font-medium text-white backdrop-blur-md">
                +{p.images.length - 1}{" "}
                {p.images.length - 1 === 1
                  ? "photo"
                  : "photos"}
              </span>
            )}
          </>
        ) : (
          <button
            type="button"
            onClick={() =>
              fileInputRef.current?.click()
            }
            disabled={uploading}
            className="flex h-full w-full flex-col items-center justify-center gap-3 text-ink-faint transition-all duration-300 hover:bg-accent-violet/[0.04] hover:text-accent-violet disabled:cursor-not-allowed"
          >
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-dashed border-base-border bg-base-panel">
              {uploading ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : (
                <ImagePlus className="h-5 w-5" />
              )}
            </div>

            <div className="text-center">
              <p className="text-xs font-medium">
                {uploading
                  ? "Uploading..."
                  : "Add product photo"}
              </p>

              <p className="mt-0.5 text-[10px] text-ink-faint">
                JPG, PNG, WEBP or GIF
              </p>
            </div>
          </button>
        )}

        <input
          ref={fileInputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp,image/gif"
          className="hidden"
          onChange={(e) => {
            const file =
              e.target.files?.[0];

            if (file) {
              onUpload(file);
            }

            e.target.value = "";
          }}
        />
      </div>

      {/* Content */}
      <div className="flex flex-1 flex-col p-4">
        {/* Title + status */}
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3
              title={p.name}
              className="truncate text-sm font-semibold text-ink"
            >
              {p.name}
            </h3>

            {p.category && (
              <div className="mt-1 flex items-center gap-1 text-[10px] text-ink-faint">
                <Tag className="h-3 w-3" />
                <span className="truncate">
                  {p.category}
                </span>
              </div>
            )}
          </div>

          <span
            className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-1 text-[9px] font-semibold capitalize ${status.badge}`}
          >
            <StatusIcon className="h-2.5 w-2.5" />
            {p.status}
          </span>
        </div>

        {/* Description */}
        {p.description ? (
          <p className="mt-3 line-clamp-3 text-xs leading-5 text-ink-muted">
            {p.description}
          </p>
        ) : (
          <p className="mt-3 text-xs italic text-ink-faint">
            No product description added.
          </p>
        )}

        {/* Variants */}
        {p.variants.length > 0 && (
          <div className="mt-3">
            <div className="mb-1.5 flex items-center justify-between">
              <span className="text-[10px] font-medium uppercase tracking-wider text-ink-faint">
                Options
              </span>

              <span className="text-[10px] text-ink-faint">
                {p.variants.length}
              </span>
            </div>

            <div className="flex flex-wrap gap-1.5">
              {p.variants
                .slice(0, 5)
                .map((variant, i) => (
                  <span
                    key={`${variant.name}-${i}`}
                    className="rounded-md border border-base-border bg-base-panel-2 px-2 py-1 text-[10px] text-ink-muted transition-colors group-hover:border-accent-violet/15"
                  >
                    {variant.name}
                  </span>
                ))}

              {p.variants.length > 5 && (
                <span className="rounded-md bg-base-panel-2 px-2 py-1 text-[10px] text-ink-faint">
                  +{p.variants.length - 5}
                </span>
              )}
            </div>
          </div>
        )}

        {/* Price / inventory */}
        <div className="mt-5 grid grid-cols-2 gap-2 border-t border-base-border pt-4">
          <div className="min-w-0">
            <p className="text-[10px] uppercase tracking-wider text-ink-faint">
              Price
            </p>

            <p className="mt-1 truncate font-display text-base font-semibold text-ink">
              {formattedPrice}
            </p>
          </div>

          <div className="min-w-0 text-right">
            <p className="text-[10px] uppercase tracking-wider text-ink-faint">
              Inventory
            </p>

            <p
              className={`mt-1 truncate text-xs font-semibold ${
                outOfStock
                  ? "text-accent-red"
                  : "text-ink"
              }`}
            >
              {p.inventory === null
                ? "Unlimited"
                : outOfStock
                  ? "Out of stock"
                  : `${p.inventory} in stock`}
            </p>
          </div>
        </div>

        {/* Actions */}
        <div className="mt-4 grid grid-cols-[1fr_1fr_auto] gap-2">
          <button
            type="button"
            onClick={onEdit}
            className="inline-flex min-w-0 items-center justify-center gap-1.5 rounded-xl bg-base-panel-2 px-2 py-2.5 text-[11px] font-semibold text-ink transition-all duration-200 hover:-translate-y-0.5 hover:bg-base-border active:translate-y-0"
          >
            <Pencil className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">
              Edit
            </span>
          </button>

          <button
            type="button"
            onClick={() =>
              fileInputRef.current?.click()
            }
            disabled={uploading}
            className="inline-flex min-w-0 items-center justify-center gap-1.5 rounded-xl bg-base-panel-2 px-2 py-2.5 text-[11px] font-semibold text-ink transition-all duration-200 hover:-translate-y-0.5 hover:bg-base-border active:translate-y-0 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {uploading ? (
              <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
            ) : (
              <ImagePlus className="h-3.5 w-3.5 shrink-0" />
            )}

            <span className="truncate">
              {p.images.length > 0
                ? "Change"
                : "Photo"}
            </span>
          </button>

          <button
            type="button"
            onClick={onDelete}
            disabled={deleting}
            className="inline-flex h-full min-w-0 items-center justify-center rounded-xl bg-red-500/10 px-3 py-2.5 text-red-500 transition-all duration-200 hover:-translate-y-0.5 hover:bg-red-500/20 active:translate-y-0 disabled:cursor-not-allowed disabled:opacity-50"
            title="Delete product"
            aria-label={`Delete ${p.name}`}
          >
            {deleting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Trash2 className="h-3.5 w-3.5" />
            )}
          </button>
        </div>
      </div>
    </article>
  );
}

/* -------------------------------------------------------------------------- */
/* Empty State                                                                */
/* -------------------------------------------------------------------------- */

function EmptyProductsState({
  onAdd,
}: {
  onAdd: () => void;
}) {
  return (
    <div className="relative flex min-h-[380px] flex-col items-center justify-center overflow-hidden px-5 py-14 text-center">
      {/* 3D-style decorative core */}
      <div className="relative mb-6 h-24 w-24 [perspective:600px]">
        <div className="absolute inset-3 rounded-full bg-gradient-to-br from-accent-violet/20 to-accent-blue/10 blur-xl" />

        <div className="absolute inset-4 rounded-full border border-accent-violet/20 bg-gradient-to-br from-accent-violet/10 to-accent-blue/10 shadow-[0_0_40px_rgba(139,92,246,0.12)] transition-transform duration-700 hover:scale-110">
          <div className="absolute inset-2 rounded-full bg-base-panel-2 shadow-inner">
            <Package className="absolute left-1/2 top-1/2 h-7 w-7 -translate-x-1/2 -translate-y-1/2 text-accent-violet" />
          </div>
        </div>

        <div className="absolute inset-0 rounded-full border border-accent-violet/10 [transform:rotateX(65deg)]">
          <div className="h-full w-full animate-spin rounded-full border border-accent-violet/20 border-l-transparent border-r-transparent motion-reduce:animate-none" />
        </div>

        <div className="absolute inset-0 rounded-full border border-accent-blue/10 [transform:rotateY(65deg)]">
          <div className="h-full w-full animate-[spin_7s_linear_infinite_reverse] rounded-full border border-accent-blue/20 border-t-transparent border-b-transparent motion-reduce:animate-none" />
        </div>
      </div>

      <h3 className="font-display text-base font-semibold text-ink">
        Your catalog is empty
      </h3>

      <p className="mt-1.5 max-w-md text-xs leading-5 text-ink-muted">
        Add your first product so your AI agents can
        search your catalog, answer product questions,
        and make better recommendations.
      </p>

      <button
        type="button"
        onClick={onAdd}
        className="mt-5 inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-accent-violet to-accent-blue px-4 py-2.5 text-xs font-semibold text-white shadow-lg shadow-accent-violet/10 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-xl hover:shadow-accent-violet/20"
      >
        <Plus className="h-3.5 w-3.5" />
        Add your first product
      </button>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Skeleton                                                                   */
/* -------------------------------------------------------------------------- */

function ProductSkeleton({
  delay,
}: {
  delay: number;
}) {
  return (
    <div
      className="overflow-hidden rounded-2xl border border-base-border bg-base-panel"
      style={{
        animationDelay: `${delay}ms`,
      }}
    >
      <div className="aspect-[4/3] animate-pulse bg-base-panel-2" />

      <div className="space-y-3 p-4">
        <div className="flex justify-between gap-3">
          <div className="h-4 w-32 animate-pulse rounded bg-base-panel-2" />
          <div className="h-5 w-14 animate-pulse rounded-full bg-base-panel-2" />
        </div>

        <div className="h-3 w-full animate-pulse rounded bg-base-panel-2" />

        <div className="h-3 w-4/5 animate-pulse rounded bg-base-panel-2" />

        <div className="flex gap-2">
          <div className="h-6 w-14 animate-pulse rounded bg-base-panel-2" />
          <div className="h-6 w-16 animate-pulse rounded bg-base-panel-2" />
        </div>

        <div className="border-t border-base-border pt-4">
          <div className="h-4 w-24 animate-pulse rounded bg-base-panel-2" />
        </div>
      </div>
    </div>
  );
}
