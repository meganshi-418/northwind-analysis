# Northwind Traders: Business Analysis (15.561 HW3)

Five business questions about the Northwind dataset, answered with reproducible Python code.
The webpage is in `docs/index.html` and is published with GitHub Pages.

**Webpage:** https://meganshi-418.github.io/northwind-analysis/

| # | Question | Figure | Tables |
|---|----------|--------|--------|
| 1 | Which country markets are growing or shrinking? | `docs/figures/q1_market_momentum.png` | `outputs/q1_country_momentum.csv` |
| 2 | How concentrated is revenue, and which valuable customers are drifting away? | `docs/figures/q2_customer_concentration.png` | `outputs/q2_top20_customers.csv` |
| 3 | Do discounts lead to larger orders? | `docs/figures/q3_discount_effect.png` | `outputs/q3_discount_levels.csv` |
| 4 | Where do late shipments come from? | `docs/figures/q4_fulfilment.png` | `outputs/q4_by_promised_window.csv`, `q4_by_shipper.csv`, `q4_by_employee.csv` |
| 5 | Which products will run out, and do the reorder rules catch them? | `docs/figures/q5_inventory_risk.png` | `outputs/q5_stockout_risk.csv`, `outputs/q5_overstock.csv` |

## Reproduce the results

Requires Python 3.10 or newer.

```bash
git clone https://github.com/meganshi-418/northwind-analysis.git
cd northwind-analysis
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python analysis.py
```

`analysis.py` reads `data/Northwind Database.xlsx` and writes:

- `docs/figures/*.png`: the five charts shown on the webpage
- `outputs/*.csv`: the tables behind each chart
- `outputs/results.json`: every headline number quoted on the webpage, plus the data checks

Running it again overwrites these files with identical results. No step is random.

## Definitions and assumptions

- **Net revenue** per order line = `UnitPrice × Quantity × (1 − Discount)`, using the price on the order line (not the current list price in the Product sheet).
- **Analysis date** = 1998-05-06, the last order date in the data.
- **Q1:** compares Jan–Apr 1997 with Jan–Apr 1998 because 1998 is incomplete; country = customer country.
- **Q2:** "at risk" = no order in more than 90 days (the median gap between a customer's orders is 35 days).
- **Q3:** discount values are rounded to 2 decimals. Each discount level is compared with the same product's average units at 0% discount. Odd discounts of 1–6% (8 lines) are excluded from the chart. The "cap at 5%" estimate assumes the same quantities.
- **Q4:** late = `ShippedDate > RequiredDate`. The 21 unshipped orders are excluded. The promised window = `RequiredDate − OrderDate` (always 14, 28 or 42 days).
- **Q5:** demand = units sold in the last 13 weeks ÷ 13. Weeks of cover = (UnitsInStock + UnitsOnOrder) ÷ weekly demand. Discontinued products are excluded. Stock levels are treated as a snapshot taken at the analysis date.

## Repository layout

```
analysis.py          all analysis code (one function per question)
data/                Northwind Database.xlsx (course-provided)
docs/index.html      the webpage (GitHub Pages source)
docs/figures/        generated charts
outputs/             generated tables and results.json
requirements.txt     pinned Python dependencies
```
