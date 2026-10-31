// Keep digits and a single decimal point, max 2 decimal places.
// Text inputs are used instead of type="number" so the arrow keys, spinner
// buttons and mouse wheel can never change an amount the user typed.
export function cleanMoney(raw) {
  let value = String(raw).replace(/[^\d.]/g, "");
  const firstDot = value.indexOf(".");
  if (firstDot !== -1) {
    value = value.slice(0, firstDot + 1) + value.slice(firstDot + 1).replace(/\./g, "").slice(0, 2);
  }
  return value;
}

export function cleanWholeNumber(raw) {
  return String(raw).replace(/\D/g, "");
}

export function money(value) {
  return Number(value || 0).toLocaleString("en-KE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

// Money is stored in shillings with two decimals. Convert to integer cents
// before adding or subtracting so totals never drift.
export function toCents(value) {
  if (value === null || value === undefined) return 0;
  // Accept "1,250.00" from pasted amounts and round on the decimal string so
  // binary float error can never shave a cent off a half-cent value.
  const cleaned = String(value).replace(/[^\d.-]/g, "");
  const amount = Number(cleaned);
  if (!Number.isFinite(amount)) return 0;
  return Math.round(significant(amount * 100));
}

// Remove the float noise just below the cent boundary (1.005 * 100 = 100.49999).
function significant(value) {
  return Number(value.toFixed(4));
}

export function fromCents(value) {
  return (Number(value || 0) / 100).toFixed(2);
}

export function percent(value, digits = 1) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "0.0";
  return amount.toFixed(digits);
}

export function currentMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

export function monthBounds(month) {
  const [year, monthNumber] = month.split("-").map(Number);
  const lastDay = new Date(year, monthNumber, 0).getDate();
  return { start: `${month}-01`, end: `${month}-${String(lastDay).padStart(2, "0")}` };
}
