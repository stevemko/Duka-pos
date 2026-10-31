import { describe, expect, it } from "vitest";

import {
  cleanMoney,
  cleanWholeNumber,
  currentMonth,
  fromCents,
  money,
  monthBounds,
  toCents,
} from "./format";

describe("cleanMoney", () => {
  it("strips letters and extra decimal points", () => {
    expect(cleanMoney("12a.3.4")).toBe("12.34");
  });

  it("keeps at most two decimal places", () => {
    expect(cleanMoney("10.999")).toBe("10.99");
    expect(cleanMoney("0.5")).toBe("0.5");
  });

  it("handles an empty value", () => {
    expect(cleanMoney("")).toBe("");
  });
});

describe("cleanWholeNumber", () => {
  it("keeps digits only", () => {
    expect(cleanWholeNumber("1 2a3")).toBe("123");
  });
});

describe("money", () => {
  it("formats numbers with two decimals", () => {
    expect(money("1250.5")).toBe("1,250.50");
    expect(money(null)).toBe("0.00");
  });
});

describe("monthBounds", () => {
  it("finds the end of a 31-day month", () => {
    expect(monthBounds("2026-10")).toEqual({ start: "2026-10-01", end: "2026-10-31" });
  });

  it("handles February in a leap year", () => {
    expect(monthBounds("2028-02")).toEqual({ start: "2028-02-01", end: "2028-02-29" });
  });
});

describe("toCents", () => {
  it("converts a plain amount", () => {
    expect(toCents("125.00")).toBe(12500);
    expect(toCents(1250)).toBe(125000);
  });

  it("accepts a pasted amount with thousands separators", () => {
    expect(toCents("1,250.00")).toBe(125000);
  });

  it("does not lose a cent to binary float error", () => {
    expect(toCents("1.005")).toBe(101);
    expect(toCents("8.57")).toBe(857);
    expect(toCents("0.07")).toBe(7);
  });

  it("treats blank and unusable input as zero", () => {
    expect(toCents("")).toBe(0);
    expect(toCents(null)).toBe(0);
    expect(toCents(undefined)).toBe(0);
    expect(toCents("abc")).toBe(0);
  });

  it("round-trips with fromCents", () => {
    expect(fromCents(toCents("1,980.45"))).toBe("1980.45");
  });
});

describe("currentMonth", () => {
  it("returns a YYYY-MM value", () => {
    expect(currentMonth()).toMatch(/^\d{4}-\d{2}$/);
  });
});
