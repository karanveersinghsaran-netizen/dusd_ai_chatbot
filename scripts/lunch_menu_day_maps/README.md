Hand-maintained day->dish-name maps for `scripts/parse_lunch_menu.py`, one
per district+grade-band+**menu cycle**. Re-create the relevant file by
reading that cycle's calendar PDF (schoolnutritionandfitness.com) when the
district publishes a new one — a few minutes of work, same shape as
`scripts/parse_course_catalog.py`'s `DEPARTMENT_HEADINGS`.

**Not committed** (`.gitignore`'d) — everything durable from a given
cycle's day-map already lives in the parser's output
(`data/lunch_menus/<district_id>/<grade_band>/<cycle start YYYY_MM_DD>.json`),
including the day->dish structure itself. The one thing a day-map captures
that isn't reconstructable from that output — *why* a manual override was
needed — is written up below instead, so nothing is lost by not keeping
the day-map file itself around past the run that used it.

## Cycles, not months

Take `--start-date`/`--end-date` from the **nutrition PDF's own title
line**, e.g. `26-27 SY C2 MENU (AUG 31 - OCT 9) DUSD` or `C3 MENU (OCT 12
- NOV 20)`. The district publishes on multi-week cycles that straddle month
boundaries, and the calendar PDFs are filed per month, so a month is the
wrong unit: the first version of this feature keyed its data by month and
the tool went dark on Oct 1 2026 while the committed "September" file was
still the district's correct menu for eight more school days. The service
selects a file by "which cycle's date range covers today", so the range
inside the file is what matters — not the filename, and not the month on
the calendar PDF.

Record the two PDFs you used as `--menu-url` and `--nutrition-url`. They
go in the cycle JSON, not on the school record, so the SOURCE the chatbot
cites can never drift from the dishes it's quoting.

One calendar month can also contain more than one cycle (October 2026 is
C2 through the 9th, then C3), and a single cycle can be split across
several calendar PDFs when a short week falls inside it (HS October 2026
ships as `Oct 1-9`, `Oct 12-14`, `Oct 19-30` — the last two are the same
C3 pattern, interrupted by the Oct 15-16 no-school days). Put that kind of
mid-cycle gap in the day-map's `"notes"` rather than inventing a cycle
boundary for it.

## Cycle 3 2026 (Oct 12 - Nov 20), 9-12 only

From `9-12_Oct_2026_Nutrition.pdf` (title line `26-27 SY C3 MENU (OCT 12 -
NOV 20) DUSD`) and the `HS_Menu_Oct_19-30,_2026.pdf` calendar. **6-8 has
no C3 file yet** — Wells still serves Cycle 2 only, and its data stops
after Oct 9.

The weekday pattern is corroborated twice over: this nutrition PDF has its
own `Day` column, and it agrees with the calendar's columns on every day.
Read the calendar's columns **positionally** (bucket each dish block's x
centre to the nearest weekday header centre) — reading pymupdf's text
order instead puts Wednesday and Thursday the wrong way round, which is
exactly the mistake that produced a phantom "the two documents disagree"
during this cycle's prep.

`end_date` is the district's own `NOV 20`, not the Oct 30 the calendar PDF
covers. Justified because the nutrition PDF spans the whole cycle and its
`Day` column matches October's calendar, so the pattern is the cycle's and
not just October's. If the November calendar turns out to differ, shorten
this file's `end_date` rather than editing the days in place — the service
will then flag dates past it instead of serving the wrong week.

Three overrides, all verified by hand against the PDF's ingredient rows:

- **"Spicy Buffalo Chicken Pizza"**: the two documents genuinely disagree
  on the NAME. The calendar advertises *Spicy Buffalo Chicken Pizza*; the
  nutrition table calls the same Monday slot *BBQ Chicken Pizza* and lists
  `BBQ Sauce` among its ingredients. Allergens are identical either way
  (`Cheese Pizza Slice WG` wheat/soy/milk; chicken strips, sauce and green
  onions add none), so the dish name carries both spellings and the
  override supplies that set. **Worth asking the district which is
  actually served** — this is the one unresolved conflict in the file.
- **"Cheese Baked Pasta"**: extracted with a spurious `soy`. Its segment
  swallowed the trailing `Brown Rice` and `Pulled Pork` rows of the next
  dish at a page break. Its real ingredients (Cellentani wheat; Alfredo
  milk; Cheddar milk; Texas Toast Garlic Bread milk/wheat) union to
  `milk, wheat`.
- **"Pork Carnitas Burrito Bowl"**: the other half of that same page
  break — extracted EMPTY, because the `Brown Rice`/`Pulled Pork` rows
  that belong to it landed in the preceding segment. `Pulled Pork` carries
  `soy`; everything else (corn, black beans, red onion, vinegar, sugar,
  limes) is clean, so its real set is `soy`.

An empty allergen set is the tell for this failure, and nothing in the
committed file has one. Note that an override is a COMPLETE replacement,
so correcting the bleed means fixing both dishes, not just the empty one.

## Cycle 2 2026 (Aug 31 - Oct 9) manual overrides

Both files' `"overrides"` keys correct the same underlying issue: at a page
break in the source nutrition PDF, pymupdf's table extraction occasionally
drops both the "Day" marker and the dish name from a dish's first
ingredient row, with nothing left to signal where a new dish starts. See
`_extract_dish_allergens`'s docstring in `parse_lunch_menu.py` for the full
mechanism — most instances of this ARE auto-recovered (the parser looks
ahead within the row-run for a later row that does carry the name), but two
cases in this cycle's source PDFs had no recoverable name anywhere in their
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
