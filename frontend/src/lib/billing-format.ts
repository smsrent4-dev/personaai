export function formatLimit(value: number | null, unit: string): string {
  if (value === null) return `Unlimited ${unit}`;
  return `${value.toLocaleString()} ${unit}`;
}

export function formatPrice(amount: number, currency: string, interval: "monthly" | "yearly"): string {
  let formatted: string;
  try {
    formatted = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      currencyDisplay: "narrowSymbol",
      minimumFractionDigits: amount % 1 === 0 ? 0 : 2,
    }).format(amount);
  } catch {
    formatted = `${currency} ${amount.toLocaleString()}`;
  }
  return `${formatted}/${interval === "monthly" ? "mo" : "yr"}`;
}
