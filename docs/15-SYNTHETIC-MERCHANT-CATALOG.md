# 15 — Synthetic Merchant & 15-Product Catalog Specification

| Document ID | `DOC-15-SYNTHETIC-MERCHANT-CATALOG` |
| :--- | :--- |
| **System** | IntentLock — Approval-Aware Purchasing Agent |
| **Merchant Entity** | Acme Workspace Supplies (`MERCH-ACME-001`) |
| **Currency Invariant** | `USD` Only (ISO 4217) |
| **Catalog Scope** | P0 Fixed 15-SKU Synthetic Catalog (`SKU-001` – `SKU-015`) |
| **Status** | Production-Grade Specification (Normative) |

---

## 1. Merchant Profile & Single-Merchant Policy

IntentLock operates under a strict **Single-Merchant P0 Policy** to enforce deterministic cart hashing, uniform settlement currency, and unambiguous PayPal Orders v2 reconciliation. Every cart version, cryptographic approval hash (`intent_hash`), and PayPal purchase unit created by IntentLock is bound exclusively to **Acme Workspace Supplies**.

### 1.1 Authoritative Merchant Metadata

| Field | Value | Enforcement Rule |
| :--- | :--- | :--- |
| **Merchant ID** | `MERCH-ACME-001` | Hardcoded invariant across SQLite `carts`, `intent_hash` canonical payload, and PayPal `purchase_units[0].custom_id`. |
| **Legal / Display Name** | `Acme Workspace Supplies` | Displayed on all Coordinator cart views, Approver sign-off modals, and PayPal Sandbox order descriptions. |
| **Settlement Currency** | `USD` | All catalog prices are stored as integer cents (`unit_price_cents`) and formatted to exact 2-decimal `USD` strings (`"XX.YY"`) for PayPal Orders v2. Non-USD currencies are rejected at Guardrail G-07. |
| **Fulfillment Model** | Standard B2B Commercial Supply | Tax-inclusive / flat-rate commercial catalog pricing for P0 sandbox determinism (`item_total == amount.value`). |
| **PayPal Integration Mode** | Single Order / Single Purchase Unit / Full Capture | 1 approved cart version maps to at most 1 PayPal Order (`intent: "CAPTURE"`), containing exactly 1 `purchase_unit` with itemized `items[]` matching catalog SKUs and prices. |

---

## 2. Deterministic Headcount & Pack-Size Math Rules

A core pain point identified in Coordinator discovery interviews is **pack-size miscalculation**—translating informal team requests (e.g., *"We're onboarding 6 engineers next Monday and need coffee, notebooks, pens, and chargers"*) into exact multi-pack SKU quantities without under-ordering or wasting budget.

Each of the 15 catalog items includes an authoritative **`recommended_per_person_rule`** injected directly into the Agent Harness context (`07-AGENT-HARNESS.md`). The LLM proposer uses these rules to perform transparent, auditable ceiling division:

$$\text{Recommended Quantity} = \left\lceil \frac{\text{Headcount} \times \text{Units Needed Per Person}}{\text{Units Per Pack}} \right\rceil$$

---

## 3. Master 15-Product Synthetic Catalog (`SKU-001` through `SKU-015`)

All prices are authoritative only in the SQLite `products` table. The AI agent **never** dictates unit prices during cart construction; the backend resolves `sku` $\rightarrow$ `unit_price_cents` deterministically (Guardrail G-01).

### 3.1 Category 1: Breakroom & Coffee (`SKU-001` – `SKU-004`)

| SKU | Product Name | Pack Size Description (`pack_size_desc`) | Unit Price (Cents) | Unit Price (USD) | Initial Stock | Recommended Per-Person Rule (`recommended_per_person_rule`) | Search & Intent Keywords (`keywords`) |
| :--- | :--- | :--- | :---: | :---: | :---: | :--- | :--- |
| **`SKU-001`** | **Organic Dark Roast Whole Bean Coffee (2lb Bag)** | `2 lb bag (~32 oz, yields ~45 cups)` | `2850` | `$28.50` | `25` | `1 bag per 10 people per week (or min 1 bag for any coffee request)` | `coffee, beans, espresso, caffeine, dark roast, breakroom, morning, brew` |
| **`SKU-002`** | **Oat Milk Barista Edition (6-Pack, 32oz Cartons)** | `Case of 6 x 32oz shelf-stable cartons` | `2400` | `$24.00` | `18` | `1 case (6 cartons) per 12 people per week; pairs 1:1 with SKU-001 coffee bags` | `oat milk, creamer, dairy-free, vegan, milk, barista, latte, coffee` |
| **`SKU-003`** | **Compostable Insulated Hot Cups with Lids (12oz, 100-Pack)** | `Sleeve of 100 cups + 100 compostable lids` | `1950` | `$19.50` | `30` | `1 pack (100 cups) per 20 people per week (assumes 5 cups/person/week)` | `cups, paper cups, hot cups, lids, disposable, coffee cups, breakroom, kitchen` |
| **`SKU-004`** | **Assorted Healthy Office Snack Box (40-Count)** | `Variety box of 40 individually wrapped bars, nuts & jerky` | `4200` | `$42.00` | `12` | `1 box (40 snacks) per 10 people per week (or 1 box per 15 workshop attendees)` | `snacks, food, granola bars, nuts, breakroom, treats, pantry, catering, workshop` |

### 3.2 Category 2: Desk & Stationery (`SKU-005` – `SKU-008`)

| SKU | Product Name | Pack Size Description (`pack_size_desc`) | Unit Price (Cents) | Unit Price (USD) | Initial Stock | Recommended Per-Person Rule (`recommended_per_person_rule`) | Search & Intent Keywords (`keywords`) |
| :--- | :--- | :--- | :---: | :---: | :---: | :--- | :--- |
| **`SKU-005`** | **Hardcover Dot-Grid Engineering Notebook (A5, 192 Pages)** | `Single hardcover notebook (1 unit)` | `1600` | `$16.00` | `40` | `1 notebook per new hire, engineer, or workshop participant (1:1 ratio)` | `notebook, journal, pad, paper, dot-grid, writing, onboarding, stationery, notes` |
| **`SKU-006`** | **Smooth Gel Rollerball Pens — Black (12-Pack)** | `Box of 12 retractable 0.7mm black gel pens` | `1450` | `$14.50` | `35` | `1 box (12 pens) per 6 people (provides 2 pens per person; ceiling division)` | `pens, gel pens, black pens, writing, rollerball, stationery, onboarding, office` |
| **`SKU-007`** | **Low-Odor Dry Erase Whiteboard Markers — Chisel Tip (8-Pack)** | `Pack of 8 assorted color whiteboard markers` | `1200` | `$12.00` | `22` | `1 pack per conference room / whiteboard session, or 1 pack per 8 workshop attendees` | `markers, dry erase, whiteboard, expo, chisel tip, meeting room, brainstorming, workshop` |
| **`SKU-008`** | **100% Recycled Super-Sticky Notes 3x3" (12-Pad Pack)** | `Pack of 12 pads (90 sheets per pad, 1,080 sheets total)` | `1500` | `$15.00` | `28` | `1 pack (12 pads) per 6 people (provides 2 pads per person) or 1 pack per design sprint` | `sticky notes, post-its, pads, yellow notes, agile, sprint, brainstorming, stationery` |

### 3.3 Category 3: IT & Onboarding Peripherals (`SKU-009` – `SKU-012`)

| SKU | Product Name | Pack Size Description (`pack_size_desc`) | Unit Price (Cents) | Unit Price (USD) | Initial Stock | Recommended Per-Person Rule (`recommended_per_person_rule`) | Search & Intent Keywords (`keywords`) |
| :--- | :--- | :--- | :---: | :---: | :---: | :--- | :--- |
| **`SKU-009`** | **Braided USB-C to USB-C 100W PD Cable (6ft)** | `Single heavy-duty braided 6ft cable (1 unit)` | `1800` | `$18.00` | `50` | `1 cable per new hire/person (or 2 per person if dual-charger/desk+travel setup requested)` | `cable, usb-c, charging cord, 100w, power cable, laptop cord, onboarding, IT, tech` |
| **`SKU-010`** | **7-in-1 USB-C Multiport Hub (4K HDMI, 100W PD, USB-A, SD)** | `Single aluminum USB-C docking dongle (1 unit)` | `4500` | `$45.00` | `15` | `1 hub per new hire or laptop workstation (1:1 ratio)` | `hub, dongle, adapter, usb-c hub, hdmi, dock, docking station, monitor adapter, onboarding, IT` |
| **`SKU-011`** | **Silent Wireless Ergonomic Mouse (Bluetooth + 2.4GHz USB)** | `Single dual-mode wireless mouse with AA battery (1 unit)` | `3200` | `$32.00` | `20` | `1 mouse per new hire or workstation (1:1 ratio)` | `mouse, wireless mouse, bluetooth mouse, ergonomic, peripheral, onboarding, desk, IT` |
| **`SKU-012`** | **65W GaN Compact USB-C Fast Wall Charger** | `Single 65W GaN foldable-prong power adapter (1 unit)` | `3800` | `$38.00` | `16` | `1 charger per new hire/person; recommend pairing 1:1 with SKU-009 USB-C cable` | `charger, wall adapter, power brick, 65w, gan charger, laptop charger, usb-c, onboarding, IT` |

### 3.4 Category 4: Facility & Safety Supplies (`SKU-013` – `SKU-015`)

| SKU | Product Name | Pack Size Description (`pack_size_desc`) | Unit Price (Cents) | Unit Price (USD) | Initial Stock | Recommended Per-Person Rule (`recommended_per_person_rule`) | Search & Intent Keywords (`keywords`) |
| :--- | :--- | :--- | :---: | :---: | :---: | :--- | :--- |
| **`SKU-013`** | **Microfiber Screen & Whiteboard Cleaning Kit (16oz Spray + 6 Cloths)** | `Kit with 16oz alcohol-free spray + 6 microfiber cloths` | `2100` | `$21.00` | `20` | `1 kit per conference room / lab zone, or 1 kit per 10 workstations` | `cleaner, screen cleaner, whiteboard cleaner, microfiber, spray, wipes, facility, maintenance` |
| **`SKU-014`** | **Disinfecting Surface Wipes Canister (3-Pack, 75 Wipes/Canister)** | `Bundle of 3 canisters (225 disinfecting wipes total)` | `1750` | `$17.50` | `24` | `1 bundle (3 canisters) per 15 people or 1 canister per shared room/kitchen/lab` | `wipes, disinfecting, sanitizing, cleaning, bleach-free, canisters, kitchen, facility, hygiene` |
| **`SKU-015`** | **OSHA-Compliant Small Office First Aid Kit (50-Person, 200 Pieces)** | `Hard-case wall-mountable 200-piece medical kit (1 unit)` | `5400` | `$54.00` | `5` | `1 kit per office floor, lab, or event space (covers up to 50 people; intentionally low stock = 5)` | `first aid, safety, osha, medical kit, bandages, emergency, compliance, facility, lab` |

---

## 4. Authoritative Seed Data Specification (SQL & JSON)

### 4.1 SQLite Seed Script (`src/db/seed_catalog.sql`)

The following deterministic seed statement initializes the `products` table at application startup:

```sql
INSERT INTO products (
    sku,
    merchant_id,
    name,
    category,
    pack_size_desc,
    unit_price_cents,
    currency,
    available_stock,
    recommended_per_person_rule,
    keywords,
    is_active
) VALUES
('SKU-001', 'MERCH-ACME-001', 'Organic Dark Roast Whole Bean Coffee (2lb Bag)', 'Breakroom & Coffee', '2 lb bag (~32 oz, yields ~45 cups)', 2850, 'USD', 25, '1 bag per 10 people per week (or min 1 bag for any coffee request)', 'coffee, beans, espresso, caffeine, dark roast, breakroom, morning, brew', 1),
('SKU-002', 'MERCH-ACME-001', 'Oat Milk Barista Edition (6-Pack, 32oz Cartons)', 'Breakroom & Coffee', 'Case of 6 x 32oz shelf-stable cartons', 2400, 'USD', 18, '1 case (6 cartons) per 12 people per week; pairs 1:1 with SKU-001 coffee bags', 'oat milk, creamer, dairy-free, vegan, milk, barista, latte, coffee', 1),
('SKU-003', 'MERCH-ACME-001', 'Compostable Insulated Hot Cups with Lids (12oz, 100-Pack)', 'Breakroom & Coffee', 'Sleeve of 100 cups + 100 compostable lids', 1950, 'USD', 30, '1 pack (100 cups) per 20 people per week (assumes 5 cups/person/week)', 'cups, paper cups, hot cups, lids, disposable, coffee cups, breakroom, kitchen', 1),
('SKU-004', 'MERCH-ACME-001', 'Assorted Healthy Office Snack Box (40-Count)', 'Breakroom & Coffee', 'Variety box of 40 individually wrapped bars, nuts & jerky', 4200, 'USD', 12, '1 box (40 snacks) per 10 people per week (or 1 box per 15 workshop attendees)', 'snacks, food, granola bars, nuts, breakroom, treats, pantry, catering, workshop', 1),
('SKU-005', 'MERCH-ACME-001', 'Hardcover Dot-Grid Engineering Notebook (A5, 192 Pages)', 'Desk & Stationery', 'Single hardcover notebook (1 unit)', 1600, 'USD', 40, '1 notebook per new hire, engineer, or workshop participant (1:1 ratio)', 'notebook, journal, pad, paper, dot-grid, writing, onboarding, stationery, notes', 1),
('SKU-006', 'MERCH-ACME-001', 'Smooth Gel Rollerball Pens — Black (12-Pack)', 'Desk & Stationery', 'Box of 12 retractable 0.7mm black gel pens', 1450, 'USD', 35, '1 box (12 pens) per 6 people (provides 2 pens per person; ceiling division)', 'pens, gel pens, black pens, writing, rollerball, stationery, onboarding, office', 1),
('SKU-007', 'MERCH-ACME-001', 'Low-Odor Dry Erase Whiteboard Markers — Chisel Tip (8-Pack)', 'Desk & Stationery', 'Pack of 8 assorted color whiteboard markers', 1200, 'USD', 22, '1 pack per conference room / whiteboard session, or 1 pack per 8 workshop attendees', 'markers, dry erase, whiteboard, expo, chisel tip, meeting room, brainstorming, workshop', 1),
('SKU-008', 'MERCH-ACME-001', '100% Recycled Super-Sticky Notes 3x3" (12-Pad Pack)', 'Desk & Stationery', 'Pack of 12 pads (90 sheets per pad, 1,080 sheets total)', 1500, 'USD', 28, '1 pack (12 pads) per 6 people (provides 2 pads per person) or 1 pack per design sprint', 'sticky notes, post-its, pads, yellow notes, agile, sprint, brainstorming, stationery', 1),
('SKU-009', 'MERCH-ACME-001', 'Braided USB-C to USB-C 100W PD Cable (6ft)', 'IT & Onboarding Peripherals', 'Single heavy-duty braided 6ft cable (1 unit)', 1800, 'USD', 50, '1 cable per new hire/person (or 2 per person if dual-charger/desk+travel setup requested)', 'cable, usb-c, charging cord, 100w, power cable, laptop cord, onboarding, IT, tech', 1),
('SKU-010', 'MERCH-ACME-001', '7-in-1 USB-C Multiport Hub (4K HDMI, 100W PD, USB-A, SD)', 'IT & Onboarding Peripherals', 'Single aluminum USB-C docking dongle (1 unit)', 4500, 'USD', 15, '1 hub per new hire or laptop workstation (1:1 ratio)', 'hub, dongle, adapter, usb-c hub, hdmi, dock, docking station, monitor adapter, onboarding, IT', 1),
('SKU-011', 'MERCH-ACME-001', 'Silent Wireless Ergonomic Mouse (Bluetooth + 2.4GHz USB)', 'IT & Onboarding Peripherals', 'Single dual-mode wireless mouse with AA battery (1 unit)', 3200, 'USD', 20, '1 mouse per new hire or workstation (1:1 ratio)', 'mouse, wireless mouse, bluetooth mouse, ergonomic, peripheral, onboarding, desk, IT', 1),
('SKU-012', 'MERCH-ACME-001', '65W GaN Compact USB-C Fast Wall Charger', 'IT & Onboarding Peripherals', 'Single 65W GaN foldable-prong power adapter (1 unit)', 3800, 'USD', 16, '1 charger per new hire/person; recommend pairing 1:1 with SKU-009 USB-C cable', 'charger, wall adapter, power brick, 65w, gan charger, laptop charger, usb-c, onboarding, IT', 1),
('SKU-013', 'MERCH-ACME-001', 'Microfiber Screen & Whiteboard Cleaning Kit (16oz Spray + 6 Cloths)', 'Facility & Safety Supplies', 'Kit with 16oz alcohol-free spray + 6 microfiber cloths', 2100, 'USD', 20, '1 kit per conference room / lab zone, or 1 kit per 10 workstations', 'cleaner, screen cleaner, whiteboard cleaner, microfiber, spray, wipes, facility, maintenance', 1),
('SKU-014', 'MERCH-ACME-001', 'Disinfecting Surface Wipes Canister (3-Pack, 75 Wipes/Canister)', 'Facility & Safety Supplies', 'Bundle of 3 canisters (225 disinfecting wipes total)', 1750, 'USD', 24, '1 bundle (3 canisters) per 15 people or 1 canister per shared room/kitchen/lab', 'wipes, disinfecting, sanitizing, cleaning, bleach-free, canisters, kitchen, facility, hygiene', 1),
('SKU-015', 'MERCH-ACME-001', 'OSHA-Compliant Small Office First Aid Kit (50-Person, 200 Pieces)', 'Facility & Safety Supplies', 'Hard-case wall-mountable 200-piece medical kit (1 unit)', 5400, 'USD', 5, '1 kit per office floor, lab, or event space (covers up to 50 people; intentionally low stock = 5)', 'first aid, safety, osha, medical kit, bandages, emergency, compliance, facility, lab', 1);
```

---

## 5. Catalog Design Rationale for Testing & Evaluation

The 15 SKUs and their parameters were specifically engineered to exercise all P0 product, agent, guardrail, and payment invariants:

1. **Multi-Pack vs. Single-Unit Headcount Arithmetic (`SKU-005` vs. `SKU-006`/`SKU-008`):**
   - When a Coordinator asks for *"onboarding supplies for 4 new engineers: notebooks, pens, and sticky notes"*, the agent must select `4 x SKU-005` (single unit, `$16.00` each) alongside `1 x SKU-006` (12-pack of pens, `$14.50`) and `1 x SKU-008` (12-pad pack of sticky notes, `$15.00`)—and explicitly explain why 1 pack of 12 pens covers 4 engineers with 8 spare pens.
2. **Complementary Item Pairing (`SKU-001` + `SKU-002`, `SKU-009` + `SKU-012`):**
   - Enables evaluating whether the agent proactively recommends pairings (e.g., pairing a `65W GaN USB-C Wall Charger` (`SKU-012`) with a `6ft 100W USB-C Cable` (`SKU-009`) because standalone GaN wall bricks do not include cords).
3. **Intentional Low-Stock Boundary Testing (`SKU-015` Initial Stock = `5`, `SKU-004` Initial Stock = `12`):**
   - Requesting *"8 First Aid Kits for all regional floors"* deterministically triggers **Guardrail G-02 (Inventory & Quantity Bound Guardrail)**, capping the proposed quantity to `5` (`available_stock`) and generating an explicit `unfulfilled_or_out_of_stock_warnings` notice.
4. **Non-Trivial Cents Arithmetic (`$28.50`, `$19.50`, `$14.50`, `$17.50`):**
   - Half-dollar prices (`50` cents) verify that integer-cent storage (`unit_price_cents`) and exact 2-decimal string serialization (`"28.50"`) never suffer IEEE-754 floating-point drift across the SQLite DB, canonical SHA-256 `intent_hash`, and PayPal Orders v2 `amount.breakdown.item_total`.
