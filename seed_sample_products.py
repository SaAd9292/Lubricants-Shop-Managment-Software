"""Load 20 sample lubricant/auto-parts products into YOUR Penguix database.

Run once from the project root (with the venv active):

    python seed_sample_products.py

It writes to the same database the app uses (%APPDATA%\\Penguix on Windows),
so the products show up immediately in the Products screen. Safe to re-run:
products are matched by name and skipped if they already exist. A few items
are intentionally low on stock so the Low-Stock alerts have something to show.

Prices below are in whole currency units (e.g. rupees) and are converted to
the database's integer minor units automatically.
"""
from __future__ import annotations

from lubripos.app_context import AppContext
from lubripos.core import money
from lubripos.services.product_service import ProductService
from lubripos.services.taxonomy_service import TaxonomyService

# name, brand, category, unit, purchase, sale, stock, min_stock, barcode
SAMPLE_PRODUCTS = [
    ("ZIC X7 5W-30 4L",            "ZIC",      "Engine Oil",       "Bottle", 2500, 3000, 24,  5, "8801111000017"),
    ("ZIC X5 10W-40 4L",           "ZIC",      "Engine Oil",       "Bottle", 1800, 2200, 30,  5, "8801111000024"),
    ("ZIC Gear Oil 85W-140 1L",    "ZIC",      "Gear Oil",         "Bottle",  720,  980, 18,  4, "8801111000031"),
    ("ZIC ATF Multi 1L",           "ZIC",      "Transmission Oil", "Bottle",  850, 1150,  3,  4, "8801111000048"),
    ("Shell Helix HX7 10W-40 4L",  "Shell",    "Engine Oil",       "Bottle", 2200, 2700, 26,  5, "8802222000014"),
    ("Shell Advance 4T 20W-50 1L", "Shell",    "Bike Oil",         "Bottle",  700,  950, 40,  8, "8802222000021"),
    ("Shell Rimula R4 15W-40 5L",  "Shell",    "Engine Oil",       "Bottle", 3800, 4500, 12,  3, "8802222000038"),
    ("Shell Spirax S3 EP90 1L",    "Shell",    "Gear Oil",         "Bottle",  750, 1000, 20,  4, "8802222000045"),
    ("Shell Tellus S2 46 5L",      "Shell",    "Hydraulic Oil",    "Bottle", 3200, 3900,  6,  3, "8802222000052"),
    ("Total Quartz 7000 10W-40 4L","Total",    "Engine Oil",       "Bottle", 2100, 2600, 22,  5, "8803333000011"),
    ("Total Hi-Perf 4T 20W-50 1L", "Total",    "Bike Oil",         "Bottle",  650,  900, 35,  8, "8803333000028"),
    ("Total Rubia TIR 15W-40 5L",  "Total",    "Engine Oil",       "Bottle", 3600, 4300, 10,  3, "8803333000035"),
    ("Total Multis EP2 Grease 500g","Total",   "Grease",           "Piece",   450,  650, 15,  5, "8803333000042"),
    ("Kixx G1 5W-30 4L",           "Kixx",     "Engine Oil",       "Bottle", 2300, 2800, 19,  5, "8804444000018"),
    ("Kixx GS 4T 20W-50 1L",       "Kixx",     "Bike Oil",         "Bottle",  600,  850,  2,  6, "8804444000025"),
    ("Caltex Delo 400 15W-40 5L",  "Caltex",   "Engine Oil",       "Bottle", 3700, 4400,  9,  3, "8805555000015"),
    ("Caltex Brake Fluid DOT4 500ml","Caltex", "Brake Fluid",      "Bottle",  400,  600, 28,  6, "8805555000022"),
    ("Havoline ProDS 5W-40 4L",    "Havoline", "Engine Oil",       "Bottle", 2600, 3100, 16,  4, "8806666000012"),
    ("Havoline Super 4T 20W-50 1L","Havoline", "Bike Oil",         "Bottle",  680,  920, 33,  8, "8806666000029"),
    ("Havoline Coolant Premix 1L", "Havoline", "Coolant",          "Bottle",  500,  750,  4,  5, "8806666000036"),
]


def main() -> int:
    ctx = AppContext()
    products = ProductService(ctx.db, ctx.audit)
    taxonomy = TaxonomyService(ctx.db, ctx.audit)
    minor_units = ctx.company.get_company().get("currency_minor_units", 100)

    brand_ids = {b["name"]: b["id"] for b in taxonomy.list_brands()}
    cat_ids = {c["name"]: c["id"] for c in taxonomy.list_categories()}

    added = skipped = 0
    for (name, brand, category, unit, purchase, sale,
         stock, min_stock, barcode) in SAMPLE_PRODUCTS:
        # ensure brand/category exist (create if a sample uses a new one)
        if brand not in brand_ids:
            brand_ids[brand] = taxonomy.add_brand(brand)
        if category not in cat_ids:
            cat_ids[category] = taxonomy.add_category(category)

        # idempotency: skip if a product with this name already exists
        exists = ctx.db.query_one(
            "SELECT 1 FROM products WHERE name = ? COLLATE NOCASE", (name,)
        )
        if exists:
            skipped += 1
            continue

        products.create({
            "name": name,
            "barcode": barcode,
            "brand_id": brand_ids[brand],
            "category_id": cat_ids[category],
            "unit_type": unit,
            "purchase_price_minor": money.to_minor(purchase, minor_units),
            "sale_price_minor": money.to_minor(sale, minor_units),
            "stock_qty": stock,
            "min_stock_level": min_stock,
        })
        added += 1

    ctx.shutdown()
    print(f"\nDone. Added {added} product(s); skipped {skipped} already present.")
    print("Open the app and click Products to see them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
