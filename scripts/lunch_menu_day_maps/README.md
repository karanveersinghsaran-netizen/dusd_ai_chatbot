Hand-maintained day->dish-name maps for `scripts/parse_lunch_menu.py`, one
per district+grade-band+month. Re-create the relevant file by reading that
month's calendar PDF (schoolnutritionandfitness.com) when the district
publishes a new one — a few minutes of work, same shape as
`scripts/parse_course_catalog.py`'s `DEPARTMENT_HEADINGS`.

**Not committed** (`.gitignore`'d) — everything durable from a given
month's day-map already lives in the parser's output
(`data/lunch_menus/<district_id>/<grade_band>/<YYYY_MM>.json`), including
the day->dish structure itself. The one thing a day-map captures that
isn't reconstructable from that output — *why* a manual override was
needed — is written up below instead, so nothing is lost by not keeping
the day-map file itself around past the run that used it.

## September 2026 manual overrides

Both files' `"overrides"` keys correct the same underlying issue: at a page
break in the source nutrition PDF, pymupdf's table extraction occasionally
drops both the "Day" marker and the dish name from a dish's first
ingredient row, with nothing left to signal where a new dish starts. See
`_extract_dish_allergens`'s docstring in `parse_lunch_menu.py` for the full
mechanism — most instances of this ARE auto-recovered (the parser looks
ahead within the row-run for a later row that does carry the name), but two
cases in this month's source PDFs had no recoverable name anywhere in their
segment:

- **6-8 (Wells), "Tortellini Pasta with Beef Bolognese"**: extracted with
  an empty allergen set. Verified by hand against
  `6-8_Sept_2026_Nutrition.pdf.pdf` page 2 — its ingredients (WG Cheese
  Tortellini: wheat/milk/egg; Beef Crumble: soy; Spaghetti Sauce: none;
  Shredded Mozzarella: milk) union to `egg, milk, soy, wheat`.
- **9-12 (DHS), "Teriyaki Rice Bowl with Chicken"**: extracted with an
  empty allergen set, and its real ingredients (Brown Rice: none; Teriyaki
  Sauce: soy; Fajita Chicken Strips: none) had instead bled into the
  preceding dish, **"Cheesy Breaded Ravioli with Marinara Sauce"** (shows
  up there as a spurious `soy`). Verified by hand against
  `9-12_Sept_2026_Nutrition.pdf` (DHS HS Nutrition PDF) pages 2-3 — Ravioli's
  real ingredients (Cheesy Breaded Ravioli: wheat/milk; Mozzarella Cheese:
  milk; Marinara Cup: none) union to `milk, wheat` only, and Teriyaki Rice
  Bowl's real set is `soy`.

Re-verify both overrides (or discover new ones) whenever these day-maps are
regenerated for a new month — the underlying PDFs change every month, so
this isn't a one-time fix.
