import { Link } from "react-router-dom";
import Icon from "../Icon";
import { Badge, Button, Card, SearchInput, Select, Tabs, cn } from "../ui";
import { money } from "../../lib/format";

function productInitials(name = "") {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

export default function ProductPicker({
  products,
  totalCount,
  categories,
  loading,
  loadingMore,
  onLoadMore,
  search,
  onSearchChange,
  onSearchSubmit,
  category,
  onCategoryChange,
  lowOnly,
  onLowOnlyChange,
  onAdd,
  cartQuantities,
  branchName,
}) {
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-2">
          <SearchInput
            value={search}
            onChange={onSearchChange}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                onSearchSubmit(search);
              }
            }}
            placeholder="Search name or scan a barcode..."
            className="min-w-0 flex-1"
            autoFocus
            aria-label="Search products or scan a barcode"
          />
          <Select
            value={category}
            onChange={(event) => onCategoryChange(event.target.value)}
            className="w-full sm:w-44"
            aria-label="Filter by category"
          >
            <option value="">All categories</option>
            {categories.map((item) => (
              <option key={item.category} value={item.category}>
                {item.category}
              </option>
            ))}
          </Select>
          <Tabs
            value={lowOnly ? "low" : "all"}
            onChange={(value) => onLowOnlyChange(value === "low")}
            items={[
              { id: "all", label: "All" },
              { id: "low", label: "Low stock" },
            ]}
          />
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-ink-400">
          <span className="flex items-center gap-1">
            <Icon name="scan" size={12} />
            Scan or type an exact SKU and press Enter to add it fast.
          </span>
          <span className="ml-auto">
            {loading ? "Searching..." : `${products.length} of ${totalCount} products`}
            {branchName ? ` · ${branchName}` : ""}
          </span>
        </div>
      </Card>

      {loading ? (
        <Card className="p-6">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {Array.from({ length: 6 }).map((_, index) => (
              <div key={index} className="h-32 animate-pulse rounded-xl bg-ink-100" />
            ))}
          </div>
        </Card>
      ) : products.length === 0 ? (
        <Card className="p-8 text-center">
          <p className="text-sm font-semibold text-ink-800">No products match this view.</p>
          <p className="mt-1 text-sm text-ink-500">
            {totalCount === 0
              ? "Add products in Inventory first, or import your price list."
              : "Try another search, category or switch back to All."}
          </p>
          {totalCount === 0 && (
            <Link to="/inventory" className="mt-4 inline-block">
              <Button variant="secondary" icon="package">
                Open inventory
              </Button>
            </Link>
          )}
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {products.map((product) => {
              const quantity = cartQuantities.get(product.id) || 0;
              const disabled = product.stock_quantity < 1;
              return (
                <button
                  key={product.id}
                  type="button"
                  onClick={() => onAdd(product)}
                  disabled={disabled}
                  className={cn(
                    "group relative flex flex-col rounded-2xl border bg-white p-3 text-left shadow-card transition",
                    disabled
                      ? "cursor-not-allowed border-ink-100 opacity-60"
                      : "border-ink-200/70 hover:-translate-y-0.5 hover:border-brand-300 hover:shadow-lg",
                  )}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex h-12 w-12 items-center justify-center overflow-hidden rounded-xl bg-ink-100 text-sm font-bold text-ink-400">
                      {product.image ? (
                        <img
                          src={product.image}
                          alt=""
                          className="h-full w-full object-cover"
                          loading="lazy"
                        />
                      ) : (
                        productInitials(product.name)
                      )}
                    </div>
                    {product.needs_restock ? (
                      <Badge tone="danger">{product.stock_quantity} left</Badge>
                    ) : (
                      <span className="text-[11px] font-semibold text-ink-400">
                        {product.stock_quantity} in stock
                      </span>
                    )}
                  </div>
                  <p className="mt-2 line-clamp-2 min-h-9 text-sm font-semibold leading-tight text-ink-900">
                    {product.name}
                  </p>
                  <p className="mt-1 font-display text-base font-semibold text-ink-950">
                    KES {money(product.selling_price)}
                  </p>
                  <div className="mt-2 flex items-center justify-between text-[11px] text-ink-400">
                    <span className="truncate">{product.category || "Uncategorised"}</span>
                    {quantity ? (
                      <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-brand-600 px-1.5 font-bold text-white">
                        {quantity}
                      </span>
                    ) : (
                      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-ink-100 text-ink-500 group-hover:bg-brand-100 group-hover:text-brand-700">
                        <Icon name="plus" size={12} strokeWidth={2.5} />
                      </span>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
          {loadingMore ? (
            <p className="py-2 text-center text-xs text-ink-400">Loading more products...</p>
          ) : (
            onLoadMore && (
              <div className="text-center">
                <Button variant="secondary" onClick={onLoadMore}>
                  Load more products
                </Button>
              </div>
            )
          )}
        </>
      )}
    </div>
  );
}
