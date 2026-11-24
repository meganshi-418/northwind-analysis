"""Northwind business analysis: reproduces every number, table and figure on the webpage.

Usage:
    python analysis.py

Inputs:  data/Northwind Database.xlsx
Outputs: docs/figures/*.png  (charts used on the webpage)
         outputs/*.csv       (tables behind each chart)
         outputs/results.json (headline numbers quoted on the webpage)
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "Northwind Database.xlsx"
FIG = ROOT / "docs" / "figures"
OUT = ROOT / "outputs"

BLUE, ORANGE, GREY, RED, GREEN = "#2a6fb0", "#e08a2c", "#9aa3ad", "#c0392b", "#2e8b57"

plt.rcParams.update({
    "figure.dpi": 150,
    "savefig.bbox": "tight",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.titleweight": "bold",
    "font.size": 10,
})

money = mtick.FuncFormatter(lambda v, _: f"${v/1000:,.0f}k")


def load_data(path=DATA):
    """Load the Northwind workbook and return a dict of DataFrames plus an order-line fact table.

    Revenue per line = UnitPrice * Quantity * (1 - Discount), using the price actually
    charged on the order (not the current list price in the Product sheet).
    """
    x = pd.read_excel(path, sheet_name=None)
    orders = x["Orders"]
    lines = x["Orders Details"].copy()
    products = x["Product"]
    customers = x["Customers"]

    lines["gross"] = lines.UnitPrice * lines.Quantity
    lines["revenue"] = lines.gross * (1 - lines.Discount)
    lines["discount_amt"] = lines.gross - lines.revenue

    fact = (
        lines.merge(orders, on="OrderID", how="left")
        .merge(products[["ProductID", "ProductName", "CategoryID"]], on="ProductID", how="left")
        .merge(x["Categories"][["CategoryID", "CategoryName"]], on="CategoryID", how="left")
        .merge(customers[["CustomerID", "CompanyName", "Country"]], on="CustomerID", how="left")
    )
    return x, fact


def check_data(x, fact):
    """Sanity checks so the reader knows the joins are complete and the period is understood."""
    o = x["Orders"]
    checks = {
        "orders": int(len(o)),
        "order_lines": int(len(x["Orders Details"])),
        "customers_in_master": int(len(x["Customers"])),
        "customers_with_orders": int(o.CustomerID.nunique()),
        "first_order": str(o.OrderDate.min().date()),
        "last_order": str(o.OrderDate.max().date()),
        "unshipped_orders": int(o.ShippedDate.isna().sum()),
        "lines_missing_product_or_order": int(fact[["ProductName", "OrderDate"]].isna().any(axis=1).sum()),
        "total_revenue": round(float(fact.revenue.sum()), 2),
    }
    assert checks["lines_missing_product_or_order"] == 0, "Join dropped rows"
    return checks


# ---------------------------------------------------------------- Q1 markets
def q1_market_momentum(fact):
    """Which country markets are growing or shrinking?

    The data ends on 1998-05-06, so calendar 1998 is partial. To compare like with like we
    use Jan 1 - Apr 30 of 1997 vs the same four months of 1998 (May 1998 is excluded because
    it has only six days).
    """
    f = fact.copy()
    f["month"] = f.OrderDate.dt.to_period("M")
    monthly = f[f.OrderDate < "1998-05-01"].groupby("month").revenue.sum()

    win = f[f.OrderDate.dt.month.between(1, 4)]
    p97 = win[win.OrderDate.dt.year == 1997].groupby("Country").revenue.sum()
    p98 = win[win.OrderDate.dt.year == 1998].groupby("Country").revenue.sum()
    total = f.groupby("Country").revenue.sum()
    tbl = pd.DataFrame({"total_revenue": total, "jan_apr_1997": p97, "jan_apr_1998": p98}).fillna(0)
    tbl["change"] = tbl.jan_apr_1998 - tbl.jan_apr_1997
    tbl["growth_pct"] = (tbl.change / tbl.jan_apr_1997.replace(0, float("nan")) * 100).astype(float)
    tbl = tbl.sort_values("change")
    tbl.round(1).to_csv(OUT / "q1_country_momentum.csv")

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 5.2), gridspec_kw={"width_ratios": [1, 1.1]})
    a1.plot(monthly.index.to_timestamp(), monthly.values, color=BLUE, marker="o", ms=3)
    a1.yaxis.set_major_formatter(money)
    a1.set_title("Monthly revenue, Jul 1996 - Apr 1998")
    a1.set_ylabel("Revenue (USD, net of discount)")
    a1.set_xlabel("Order month")
    a1.grid(axis="y", alpha=0.3)

    colors = [GREEN if v >= 0 else RED for v in tbl.change]
    a2.barh(tbl.index, tbl.change, color=colors)
    a2.xaxis.set_major_formatter(money)
    a2.axvline(0, color="black", lw=0.8)
    a2.set_title("Change in revenue by country\n(Jan-Apr 1998 vs Jan-Apr 1997)")
    a2.set_xlabel("Change in revenue (USD)")
    a2.tick_params(axis="y", labelsize=8)
    fig.tight_layout()
    fig.savefig(FIG / "q1_market_momentum.png")
    plt.close(fig)

    tot97, tot98 = p97.sum(), p98.sum()
    top3 = tbl.sort_values("change", ascending=False).head(3)
    return {
        "jan_apr_1997": round(tot97),
        "jan_apr_1998": round(tot98),
        "growth_pct": round((tot98 / tot97 - 1) * 100, 1),
        "top_gainers": {k: round(v) for k, v in top3.change.items()},
        "top3_share_of_growth_pct": round(top3.change.sum() / (tot98 - tot97) * 100, 1),
        "decliners": {k: round(v) for k, v in tbl[tbl.change < 0].change.items()},
    }


# ---------------------------------------------------------------- Q2 customers
def q2_customer_concentration(fact, as_of="1998-05-06"):
    """How dependent is revenue on a few customers, and which big accounts look at risk?

    'At risk' = a top-20 customer (by lifetime revenue) whose last order is more than 90 days
    before the last date in the data. Median gap between orders is reported for context.
    """
    as_of = pd.Timestamp(as_of)
    cust = fact.groupby(["CustomerID", "CompanyName", "Country"]).agg(
        revenue=("revenue", "sum"),
        orders=("OrderID", "nunique"),
        last_order=("OrderDate", "max"),
    ).reset_index().sort_values("revenue", ascending=False)
    cust["cum_share"] = cust.revenue.cumsum() / cust.revenue.sum()
    cust["rank"] = range(1, len(cust) + 1)
    cust["days_since_last"] = (as_of - cust.last_order).dt.days

    gaps = (
        fact.drop_duplicates("OrderID").sort_values("OrderDate")
        .groupby("CustomerID").OrderDate.diff().dt.days.dropna()
    )
    median_gap = float(gaps.median())

    top20 = cust.head(20).copy()
    top20["status"] = top20.days_since_last.apply(lambda d: "At risk (>90 days)" if d > 90 else "Active")
    lapsed = cust[cust.days_since_last > 90]
    top20[["rank", "CompanyName", "Country", "revenue", "orders", "last_order", "days_since_last", "status"]] \
        .round({"revenue": 0}).to_csv(OUT / "q2_top20_customers.csv", index=False)

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 5.2))
    share_pct = cust.cum_share.values * 100
    a1.plot(cust["rank"], share_pct, color=BLUE)
    a1.fill_between(cust["rank"], share_pct, alpha=0.1, color=BLUE)
    for k in (10, 20):
        y = share_pct[k - 1]
        a1.scatter([k], [y], color=ORANGE, zorder=3)
        a1.annotate(f"Top {k}: {y:.0f}%", (k, y), xytext=(k + 4, y - 8), fontsize=9)
    a1.set_ylim(0, 102)
    a1.yaxis.set_major_formatter(mtick.PercentFormatter())
    a1.set_title(f"Cumulative share of revenue ({len(cust)} customers)")
    a1.set_xlabel("Customers ranked by lifetime revenue")
    a1.set_ylabel("Cumulative % of total revenue")
    a1.grid(alpha=0.3)

    t = top20.iloc[::-1]
    col = [RED if s.startswith("At risk") else BLUE for s in t.status]
    a2.barh(t.CompanyName, t.days_since_last, color=col)
    a2.axvline(90, color="black", ls="--", lw=0.8)
    a2.text(92, 0, "90-day line", fontsize=8, va="bottom")
    a2.set_title("Top 20 customers: days since last order\n(red = no order in 90+ days)")
    a2.set_xlabel(f"Days since last order (as of {as_of.date()})")
    a2.tick_params(axis="y", labelsize=8)
    fig.tight_layout()
    fig.savefig(FIG / "q2_customer_concentration.png")
    plt.close(fig)

    risk = top20[top20.status.str.startswith("At risk")]
    return {
        "n_customers": int(len(cust)),
        "top10_share_pct": round(share_pct[9], 1),
        "top20_share_pct": round(share_pct[19], 1),
        "median_days_between_orders": median_gap,
        "at_risk": [
            {"company": r.CompanyName, "country": r.Country, "revenue": round(r.revenue),
             "days_since_last": int(r.days_since_last)} for r in risk.itertuples()
        ],
        "at_risk_revenue": round(risk.revenue.sum()),
        "at_risk_share_pct": round(risk.revenue.sum() / cust.revenue.sum() * 100, 1),
        "lapsed_all_count": int(len(lapsed)),
        "lapsed_all_revenue": round(float(lapsed.revenue.sum())),
        "lapsed_all_share_pct": round(lapsed.revenue.sum() / cust.revenue.sum() * 100, 1),
    }


# ---------------------------------------------------------------- Q3 discounts
def q3_discount_effect(fact):
    """Do discounts buy larger orders, or just give money away?

    Discounted lines are compared with undiscounted lines of the SAME product, so the
    comparison is not distorted by product mix: for each product we compute the ratio
    (mean quantity at discount level d) / (mean quantity at 0% discount).
    Discount levels 1-6% (8 lines total) are grouped as 'other' and excluded from the chart.
    """
    f = fact.copy()
    f["level"] = f.Discount.round(2).map({0: "0%", .05: "5%", .10: "10%", .15: "15%", .20: "20%", .25: "25%"})
    f = f.dropna(subset=["level"])
    order = ["0%", "5%", "10%", "15%", "20%", "25%"]

    base = f[f.level == "0%"].groupby("ProductID").Quantity.mean().rename("base_qty")
    rel = f.merge(base, on="ProductID")
    rel["qty_index"] = rel.Quantity / rel.base_qty
    by_level = rel.groupby("level").agg(
        lines=("Quantity", "size"),
        avg_qty=("Quantity", "mean"),
        qty_vs_same_product_undiscounted=("qty_index", "mean"),
        discount_given=("discount_amt", "sum"),
    ).reindex(order)
    by_level.round(3).to_csv(OUT / "q3_discount_levels.csv")

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.8))
    data = [f[f.level == l].Quantity for l in order]
    a1.boxplot(data, tick_labels=order, showfliers=False, patch_artist=True,
               boxprops=dict(facecolor="#d7e6f5", color=BLUE), medianprops=dict(color=ORANGE, lw=2))
    a1.plot(range(1, 7), by_level.avg_qty, "D", color=BLUE, label="Mean")
    a1.set_title("Units per order line by discount level")
    a1.set_xlabel("Discount on the order line")
    a1.set_ylabel("Units ordered per line")
    a1.legend(loc="upper left")

    idx = by_level.qty_vs_same_product_undiscounted
    a2.bar(order, (idx - 1) * 100, color=[GREY] + [BLUE] * 5)
    for i, v in enumerate((idx - 1) * 100):
        a2.text(i, v + (1 if v >= 0 else -3), f"{v:+.0f}%", ha="center", fontsize=9)
    a2.axhline(0, color="black", lw=0.8)
    a2.set_title("Units vs. the same product sold at 0% discount")
    a2.set_xlabel("Discount on the order line")
    a2.set_ylabel("Difference in units per line (%)")
    a2.yaxis.set_major_formatter(mtick.PercentFormatter())
    fig.tight_layout()
    fig.savefig(FIG / "q3_discount_effect.png")
    plt.close(fig)

    disc = rel[rel.level != "0%"]
    lift = disc.qty_index.mean() - 1
    lift_by = ((idx - 1) * 100).round(1)
    return {
        "share_lines_discounted_pct": round((fact.Discount > 0).mean() * 100, 1),
        "total_discount_given": round(float(fact.discount_amt.sum())),
        "discount_pct_of_gross": round(fact.discount_amt.sum() / fact.gross.sum() * 100, 1),
        "avg_qty_lift_any_discount_pct": round(lift * 100, 1),
        "lift_by_level_pct": lift_by.drop("0%").to_dict(),
        # What-if: lines discounted above 5% get 5% instead, holding quantities fixed.
        "savings_if_capped_at_5pct": round(float(
            (fact.gross * (fact.Discount.round(2) - 0.05)).where(fact.Discount.round(2) > 0.05, 0).sum())),
    }


# ---------------------------------------------------------------- Q4 fulfilment
def q4_fulfilment(x, fact):
    """Where does fulfilment break down: late shipments by shipper and by sales employee.

    Late = ShippedDate after RequiredDate. Unshipped orders (no ShippedDate) are reported
    separately and excluded from the late rate.
    """
    o = x["Orders"].merge(x["Shippers"], left_on="ShipVia", right_on="ShipperID")
    e = x["Employees"].assign(Employee=lambda d: d.FirstName + " " + d.LastName)
    o = o.merge(e[["EmployeeID", "Employee"]], on="EmployeeID")
    shipped = o.dropna(subset=["ShippedDate"]).copy()
    shipped["days_to_ship"] = (shipped.ShippedDate - shipped.OrderDate).dt.days
    shipped["late"] = shipped.ShippedDate > shipped.RequiredDate

    val = fact.groupby("OrderID").revenue.sum()
    shipped["order_value"] = shipped.OrderID.map(val)

    def summarise(col):
        return shipped.groupby(col).agg(
            orders=("OrderID", "size"),
            late_rate=("late", "mean"),
            median_days_to_ship=("days_to_ship", "median"),
            avg_freight=("Freight", "mean"),
            late_value=("order_value", lambda s: s[shipped.loc[s.index, "late"]].sum()),
        ).sort_values("late_rate", ascending=False)

    by_ship = summarise("CompanyName")
    by_emp = summarise("Employee")
    by_ship.round(3).to_csv(OUT / "q4_by_shipper.csv")
    by_emp.round(3).to_csv(OUT / "q4_by_employee.csv")

    shipped["promised_days"] = (shipped.RequiredDate - shipped.OrderDate).dt.days
    by_win = shipped.groupby("promised_days").agg(
        orders=("OrderID", "size"), late_orders=("late", "sum"), late_rate=("late", "mean"),
        median_days_to_ship=("days_to_ship", "median"))
    by_win.round(3).to_csv(OUT / "q4_by_promised_window.csv")
    # Share of each employee's orders that were 14-day rush orders (helps explain differences).
    by_emp["rush_share"] = shipped.groupby("Employee").promised_days.apply(lambda s: (s == 14).mean())
    by_emp["late_orders"] = shipped.groupby("Employee").late.sum()
    by_emp.round(3).to_csv(OUT / "q4_by_employee.csv")

    overall = shipped.late.mean()
    fig, (a0, a1, a2) = plt.subplots(1, 3, figsize=(14, 4.8), gridspec_kw={"width_ratios": [1, 1, 1.5]})
    labels = [f"{d} days" for d in by_win.index]
    a0.bar(labels, by_win.late_rate * 100, color=[RED, BLUE, BLUE])
    for i, (r, n) in enumerate(zip(by_win.late_rate, by_win.orders)):
        a0.text(i, r * 100 + 0.3, f"{r*100:.1f}%\n(n={n})", ha="center", fontsize=8)
    a0.set_title("Late rate by promised delivery window")
    a0.set_xlabel("Days between order and required date")
    a0.set_ylabel("% of shipped orders shipped after required date")
    a0.yaxis.set_major_formatter(mtick.PercentFormatter())
    a0.set_ylim(0, by_win.late_rate.max() * 100 + 4)

    a1.bar([n.replace(" ", "\n") for n in by_ship.index], by_ship.late_rate * 100, color=BLUE)
    for i, (r, n) in enumerate(zip(by_ship.late_rate, by_ship.orders)):
        a1.text(i, r * 100 + 0.3, f"{r*100:.1f}%\n(n={n})", ha="center", fontsize=8)
    a1.set_title("Late rate by shipper")
    a1.set_xlabel("Shipping company")
    a1.yaxis.set_major_formatter(mtick.PercentFormatter())
    a1.set_ylim(0, by_win.late_rate.max() * 100 + 4)
    a1.tick_params(axis="x", labelsize=8)

    t = by_emp.iloc[::-1]
    col = [RED if r > overall * 1.5 else BLUE for r in t.late_rate]
    a2.barh(t.index, t.late_rate * 100, color=col)
    a2.axvline(overall * 100, color="black", ls="--", lw=0.8)
    a2.text(overall * 100 + 0.2, -0.6, f"company avg {overall*100:.1f}%", fontsize=8)
    for i, (k, n) in enumerate(zip(t.late_orders, t.orders)):
        a2.text(t.late_rate.iloc[i] * 100 + 0.2, i, f"{int(k)} of {n}", va="center", fontsize=8)
    a2.set_title("Late rate by sales employee\n(red = more than 1.5x company average)")
    a2.set_xlabel("% of orders shipped late (labels: late / total orders)")
    a2.xaxis.set_major_formatter(mtick.PercentFormatter())
    a2.set_xlim(0, by_emp.late_rate.max() * 100 + 4)
    fig.tight_layout()
    fig.savefig(FIG / "q4_fulfilment.png")
    plt.close(fig)

    worst = by_emp.iloc[0]
    return {
        "shipped_orders": int(len(shipped)),
        "unshipped_orders": int(o.ShippedDate.isna().sum()),
        "overall_late_rate_pct": round(overall * 100, 1),
        "late_by_shipper_pct": (by_ship.late_rate * 100).round(1).to_dict(),
        "late_by_window_pct": {int(k): round(v * 100, 1) for k, v in by_win.late_rate.items()},
        "rush_orders": int(by_win.loc[14, "orders"]),
        "rush_share_of_late_pct": round(by_win.loc[14, "late_orders"] / by_win.late_orders.sum() * 100, 1),
        "worst_employee_late_count": int(worst.late_orders),
        "worst_employee_rush_share_pct": round(worst.rush_share * 100, 1),
        "company_rush_share_pct": round((shipped.promised_days == 14).mean() * 100, 1),
        "worst_employee": worst.name,
        "worst_employee_late_pct": round(worst.late_rate * 100, 1),
        "worst_employee_orders": int(worst.orders),
        "late_order_value": round(float(shipped.loc[shipped.late, "order_value"].sum())),
        "median_days_to_ship_late": float(shipped.loc[shipped.late, "days_to_ship"].median()),
        "median_days_to_ship_ontime": float(shipped.loc[~shipped.late, "days_to_ship"].median()),
    }


# ---------------------------------------------------------------- Q5 inventory
def q5_inventory_risk(x, fact, as_of="1998-05-06"):
    """Which active products will stock out soon, and which tie up cash?

    Demand = average units sold per week over the last 13 weeks of data (Feb 4 - May 6 1998).
    Weeks of cover = (UnitsInStock + UnitsOnOrder) / weekly demand. Discontinued products are excluded.
    """
    as_of = pd.Timestamp(as_of)
    start = as_of - pd.Timedelta(weeks=13)
    p = x["Product"][~x["Product"].Discontinued.astype(bool)].copy()
    recent = fact[fact.OrderDate > start].groupby("ProductID").Quantity.sum() / 13
    rev12 = fact[fact.OrderDate > start].groupby("ProductID").revenue.sum()
    p["weekly_demand"] = p.ProductID.map(recent).fillna(0)
    p["recent_13wk_revenue"] = p.ProductID.map(rev12).fillna(0)
    p["cover_on_hand_wks"] = p.UnitsInStock / p.weekly_demand.replace(0, float("nan"))
    p["cover_incl_onorder_wks"] = (p.UnitsInStock + p.UnitsOnOrder) / p.weekly_demand.replace(0, float("nan"))
    p["stock_value"] = p.UnitsInStock * p.Price
    p["cover_on_hand_wks"] = p.cover_on_hand_wks.astype(float)
    p["cover_incl_onorder_wks"] = p.cover_incl_onorder_wks.astype(float)

    cols = ["ProductName", "UnitsInStock", "UnitsOnOrder", "ReorderLevel", "weekly_demand",
            "cover_on_hand_wks", "cover_incl_onorder_wks", "recent_13wk_revenue", "stock_value"]
    urgent = p[p.cover_incl_onorder_wks < 4].sort_values("recent_13wk_revenue", ascending=False)[cols]
    overstock = p[p.cover_on_hand_wks > 26].sort_values("stock_value", ascending=False)[cols]
    urgent.round(1).to_csv(OUT / "q5_stockout_risk.csv", index=False)
    overstock.round(1).to_csv(OUT / "q5_overstock.csv", index=False)

    top = urgent.head(15).iloc[::-1]
    silent_mask = top.UnitsInStock > top.ReorderLevel
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 5.6), sharey=True, gridspec_kw={"width_ratios": [1, 1]})
    a1.barh(top.ProductName, top.recent_13wk_revenue, color=GREY)
    a1.xaxis.set_major_formatter(money)
    a1.set_title("Revenue at stake\n(last 13 weeks of sales)")
    a1.set_xlabel("Revenue, Feb 4 - May 6 1998 (USD)")
    a2.barh(top.ProductName, top.cover_incl_onorder_wks, color=[RED if m else ORANGE for m in silent_mask])
    a2.axvline(4, color="black", ls="--", lw=0.8)
    a2.set_xlim(0, 5)
    for i, v in enumerate(top.cover_incl_onorder_wks):
        a2.text(v + 0.05, i, f"{v:.1f} wk", va="center", fontsize=8)
    a2.set_title("Weeks of cover left (stock + on order)\nred = still above reorder level, so no reorder is triggered")
    a2.set_xlabel("Weeks of cover at recent demand")
    a1.tick_params(axis="y", labelsize=8)
    fig.suptitle("15 highest-revenue active products with < 4 weeks of cover", fontweight="bold")
    fig.tight_layout()
    fig.savefig(FIG / "q5_inventory_risk.png")
    plt.close(fig)

    # Reorder policy check: items still ABOVE their reorder level (so no reorder is triggered)
    # even though they have less than 4 weeks of cover.
    silent = urgent[urgent.UnitsInStock > urgent.ReorderLevel]
    return {
        "silent_stockout_count": int(len(silent)),
        "zero_reorder_level_in_risk": int((urgent.ReorderLevel == 0).sum()),
        "median_cover_risk_wks": round(float(urgent.cover_incl_onorder_wks.median()), 1),
        "active_products": int(len(p)),
        "stockout_risk_count": int(len(urgent)),
        "stockout_risk_recent_revenue": round(float(urgent.recent_13wk_revenue.sum())),
        "stockout_out_of_stock_now": int((urgent.UnitsInStock == 0).sum()),
        "stockout_products": urgent.ProductName.tolist(),
        "overstock_count": int(len(overstock)),
        "overstock_value_at_list": round(float(overstock.stock_value.sum())),
        "overstock_top": overstock.head(5).ProductName.tolist(),
        "urgent_table": urgent.round(1).to_dict(orient="records"),
    }


def main():
    """Run all five analyses and write figures, tables and results.json."""
    FIG.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    x, fact = load_data()
    results = {
        "data_checks": check_data(x, fact),
        "q1_markets": q1_market_momentum(fact),
        "q2_customers": q2_customer_concentration(fact),
        "q3_discounts": q3_discount_effect(fact),
        "q4_fulfilment": q4_fulfilment(x, fact),
        "q5_inventory": q5_inventory_risk(x, fact),
    }
    (OUT / "results.json").write_text(json.dumps(results, indent=2, default=str))
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
