import hashlib
import json
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, SessionLocal, engine
from .models import (
    ApprovalLock,
    AuditEvent,
    CartLineItem,
    CartVersion,
    CoordinatorInterview,
    PayPalOrderRecord,
    Product,
    PurchaseRequest,
    ReconciliationRecord,
    User,
)
from .services.audit_service import record_audit_event
from .services.cart_hash_service import (
    build_canonical_cart_dict,
    compute_approval_signature,
    compute_intent_hash,
    format_utc_iso,
    serialize_canonical_json,
)


DEFAULT_PERSONAS = [
    {
        "id": "user-coord-alice",
        "name": "Alice Chen",
        "email": "alice.chen@acme-team.io",
        "role": "COORDINATOR",
        "department": "Operations Coordinator",
        "avatar_badge": "AC",
    },
    {
        "id": "user-approver-bob",
        "name": "Bob Martinez",
        "email": "bob.martinez@acme-team.io",
        "role": "APPROVER",
        "department": "VP of Operations & Budget Approver",
        "avatar_badge": "BM",
    },
    {
        "id": "user-buyer-charlie",
        "name": "Charlie Davis",
        "email": "charlie.davis@acme-team.io",
        "role": "BUYER",
        "department": "Procurement Buyer & Reconciliation Operator",
        "avatar_badge": "CD",
    },
]

SYNTHETIC_PRODUCTS = [
    {
        "sku": "SKU-001",
        "merchant_id": "MERCH-ACME-001",
        "name": "Organic Dark Roast Whole Bean Coffee (2lb Bag)",
        "category": "Breakroom & Coffee",
        "pack_size_desc": "2 lb bag (~32 oz, yields ~45 cups)",
        "unit_price_cents": 2850,
        "stock_available": 25,
        "recommended_rule": "1 bag per 10 people per week (or min 1 bag for any coffee request)",
        "keywords": ["coffee", "beans", "espresso", "caffeine", "dark roast", "breakroom", "morning", "brew"],
        "is_active": True,
    },
    {
        "sku": "SKU-002",
        "merchant_id": "MERCH-ACME-001",
        "name": "Oat Milk Barista Edition (6-Pack, 32oz Cartons)",
        "category": "Breakroom & Coffee",
        "pack_size_desc": "Case of 6 x 32oz shelf-stable cartons",
        "unit_price_cents": 2400,
        "stock_available": 18,
        "recommended_rule": "1 case (6 cartons) per 12 people per week; pairs 1:1 with SKU-001 coffee bags",
        "keywords": ["oat milk", "creamer", "dairy-free", "vegan", "milk", "barista", "latte", "coffee"],
        "is_active": True,
    },
    {
        "sku": "SKU-003",
        "merchant_id": "MERCH-ACME-001",
        "name": "Compostable Insulated Hot Cups with Lids (12oz, 100-Pack)",
        "category": "Breakroom & Coffee",
        "pack_size_desc": "Sleeve of 100 cups + 100 compostable lids",
        "unit_price_cents": 1950,
        "stock_available": 30,
        "recommended_rule": "1 pack (100 cups) per 20 people per week (assumes 5 cups/person/week)",
        "keywords": ["cups", "paper cups", "hot cups", "lids", "disposable", "coffee cups", "breakroom", "kitchen"],
        "is_active": True,
    },
    {
        "sku": "SKU-004",
        "merchant_id": "MERCH-ACME-001",
        "name": "Assorted Healthy Office Snack Box (40-Count)",
        "category": "Breakroom & Coffee",
        "pack_size_desc": "Variety box of 40 individually wrapped bars, nuts & jerky",
        "unit_price_cents": 4200,
        "stock_available": 12,
        "recommended_rule": "1 box (40 snacks) per 10 people per week (or 1 box per 15 workshop attendees)",
        "keywords": ["snacks", "food", "granola bars", "nuts", "breakroom", "treats", "pantry", "catering", "workshop"],
        "is_active": True,
    },
    {
        "sku": "SKU-005",
        "merchant_id": "MERCH-ACME-001",
        "name": "Hardcover Dot-Grid Engineering Notebook (A5, 192 Pages)",
        "category": "Desk & Stationery",
        "pack_size_desc": "Single hardcover notebook (1 unit)",
        "unit_price_cents": 1600,
        "stock_available": 40,
        "recommended_rule": "1 notebook per new hire, engineer, or workshop participant (1:1 ratio)",
        "keywords": ["notebook", "journal", "pad", "paper", "dot-grid", "writing", "onboarding", "stationery", "notes"],
        "is_active": True,
    },
    {
        "sku": "SKU-006",
        "merchant_id": "MERCH-ACME-001",
        "name": "Smooth Gel Rollerball Pens — Black (12-Pack)",
        "category": "Desk & Stationery",
        "pack_size_desc": "Box of 12 retractable 0.7mm black gel pens",
        "unit_price_cents": 1450,
        "stock_available": 35,
        "recommended_rule": "1 box (12 pens) per 6 people (provides 2 pens per person; ceiling division)",
        "keywords": ["pens", "gel pens", "black pens", "writing", "rollerball", "stationery", "onboarding", "office"],
        "is_active": True,
    },
    {
        "sku": "SKU-007",
        "merchant_id": "MERCH-ACME-001",
        "name": "Low-Odor Dry Erase Whiteboard Markers — Chisel Tip (8-Pack)",
        "category": "Desk & Stationery",
        "pack_size_desc": "Pack of 8 assorted color whiteboard markers",
        "unit_price_cents": 1200,
        "stock_available": 22,
        "recommended_rule": "1 pack per conference room / whiteboard session, or 1 pack per 8 workshop attendees",
        "keywords": ["markers", "dry erase", "whiteboard", "expo", "chisel tip", "meeting room", "brainstorming", "workshop"],
        "is_active": True,
    },
    {
        "sku": "SKU-008",
        "merchant_id": "MERCH-ACME-001",
        "name": "100% Recycled Super-Sticky Notes 3x3\" (12-Pad Pack)",
        "category": "Desk & Stationery",
        "pack_size_desc": "Pack of 12 pads (90 sheets per pad, 1,080 sheets total)",
        "unit_price_cents": 1500,
        "stock_available": 28,
        "recommended_rule": "1 pack (12 pads) per 6 people (provides 2 pads per person) or 1 pack per design sprint",
        "keywords": ["sticky notes", "post-its", "pads", "yellow notes", "agile", "sprint", "brainstorming", "stationery"],
        "is_active": True,
    },
    {
        "sku": "SKU-009",
        "merchant_id": "MERCH-ACME-001",
        "name": "Braided USB-C to USB-C 100W PD Cable (6ft)",
        "category": "IT & Onboarding Peripherals",
        "pack_size_desc": "Single heavy-duty braided 6ft cable (1 unit)",
        "unit_price_cents": 1800,
        "stock_available": 50,
        "recommended_rule": "1 cable per new hire/person (or 2 per person if dual-charger/desk+travel setup requested)",
        "keywords": ["cable", "usb-c", "charging cord", "100w", "power cable", "laptop cord", "onboarding", "IT", "tech"],
        "is_active": True,
    },
    {
        "sku": "SKU-010",
        "merchant_id": "MERCH-ACME-001",
        "name": "7-in-1 USB-C Multiport Hub (4K HDMI, 100W PD, USB-A, SD)",
        "category": "IT & Onboarding Peripherals",
        "pack_size_desc": "Single aluminum USB-C docking dongle (1 unit)",
        "unit_price_cents": 4500,
        "stock_available": 15,
        "recommended_rule": "1 hub per new hire or laptop workstation (1:1 ratio)",
        "keywords": ["hub", "dongle", "adapter", "usb-c hub", "hdmi", "dock", "docking station", "monitor adapter", "onboarding", "IT"],
        "is_active": True,
    },
    {
        "sku": "SKU-011",
        "merchant_id": "MERCH-ACME-001",
        "name": "Silent Wireless Ergonomic Mouse (Bluetooth + 2.4GHz USB)",
        "category": "IT & Onboarding Peripherals",
        "pack_size_desc": "Single dual-mode wireless mouse with AA battery (1 unit)",
        "unit_price_cents": 3200,
        "stock_available": 20,
        "recommended_rule": "1 mouse per new hire or workstation (1:1 ratio)",
        "keywords": ["mouse", "wireless mouse", "bluetooth mouse", "ergonomic", "peripheral", "onboarding", "desk", "IT"],
        "is_active": True,
    },
    {
        "sku": "SKU-012",
        "merchant_id": "MERCH-ACME-001",
        "name": "65W GaN Compact USB-C Fast Wall Charger",
        "category": "IT & Onboarding Peripherals",
        "pack_size_desc": "Single 65W GaN foldable-prong power adapter (1 unit)",
        "unit_price_cents": 3800,
        "stock_available": 16,
        "recommended_rule": "1 charger per new hire/person; recommend pairing 1:1 with SKU-009 USB-C cable",
        "keywords": ["charger", "wall adapter", "power brick", "65w", "gan charger", "laptop charger", "usb-c", "onboarding", "IT"],
        "is_active": True,
    },
    {
        "sku": "SKU-013",
        "merchant_id": "MERCH-ACME-001",
        "name": "Microfiber Screen & Whiteboard Cleaning Kit (16oz Spray + 6 Cloths)",
        "category": "Facility & Safety Supplies",
        "pack_size_desc": "Kit with 16oz alcohol-free spray + 6 microfiber cloths",
        "unit_price_cents": 2100,
        "stock_available": 20,
        "recommended_rule": "1 kit per conference room / lab zone, or 1 kit per 10 workstations",
        "keywords": ["cleaner", "screen cleaner", "whiteboard cleaner", "microfiber", "spray", "wipes", "facility", "maintenance"],
        "is_active": True,
    },
    {
        "sku": "SKU-014",
        "merchant_id": "MERCH-ACME-001",
        "name": "Disinfecting Surface Wipes Canister (3-Pack, 75 Wipes/Canister)",
        "category": "Facility & Safety Supplies",
        "pack_size_desc": "Bundle of 3 canisters (225 disinfecting wipes total)",
        "unit_price_cents": 1750,
        "stock_available": 24,
        "recommended_rule": "1 bundle (3 canisters) per 15 people or 1 canister per shared room/kitchen/lab",
        "keywords": ["wipes", "disinfecting", "sanitizing", "cleaning", "bleach-free", "canisters", "kitchen", "facility", "hygiene"],
        "is_active": True,
    },
    {
        "sku": "SKU-015",
        "merchant_id": "MERCH-ACME-001",
        "name": "OSHA-Compliant Small Office First Aid Kit (50-Person, 200 Pieces)",
        "category": "Facility & Safety Supplies",
        "pack_size_desc": "Hard-case wall-mountable 200-piece medical kit (1 unit)",
        "unit_price_cents": 5400,
        "stock_available": 5,
        "recommended_rule": "1 kit per office floor, lab, or event space (covers up to 50 people; intentionally low stock = 5)",
        "keywords": ["first aid", "safety", "osha", "medical kit", "bandages", "emergency", "compliance", "facility", "lab"],
        "is_active": True,
    },
]

COORDINATOR_INTERVIEWS_SEED = [
    {
        "id": "COORD-INT-01",
        "coordinator_name": "Maya Lin",
        "role_title": "People & Office Coordinator (SaaS Startup)",
        "team_size": 35,
        "recent_purchase_scenario": (
            "Bi-weekly engineering onboarding kits (USB-C cables, hubs, mice, GaN chargers, dot-grid notebooks, "
            "and 12-pack gel pens) plus weekly breakroom restocks."
        ),
        "baseline_completion_minutes": 14.5,
        "baseline_corrections_count": 3,
        "baseline_drift_incident": (
            "Took a screenshot of a $312.00 cart for Slack thumbs-up approval; 2 hours later added 2 packs of "
            "whiteboard markers and checked out at $336.00 under the original approval ($24.00 unapproved drift)."
        ),
        "intentlock_completion_seconds": 36.2,
        "intentlock_corrections_count": 0,
        "key_quote": (
            "I used to accidentally order 5 boxes of 12-pack pens for 5 new hires, or edit the cart after Slack "
            "approval when someone asked for one extra item. Having the pack math explained and the cart hash-locked "
            "saves our month-end reconciliation."
        ),
        "pain_points": [
            "Headcount-to-multi-pack arithmetic errors (12-pack pens vs single notebooks)",
            "Post-approval Slack screenshot cart drift before payment execution",
            "Re-calculating totals manually whenever an item is low on stock",
        ],
    },
    {
        "id": "COORD-INT-02",
        "coordinator_name": "Jordan Vance",
        "role_title": "Lab & Studio Operations Coordinator (Hardware R&D)",
        "team_size": 18,
        "recent_purchase_scenario": (
            "Shared bench and conference room supplies: disinfecting wipes, microfiber screen cleaning kits, "
            "OSHA first aid kits, and 100W USB-C power delivery cables."
        ),
        "baseline_completion_minutes": 12.8,
        "baseline_corrections_count": 2,
        "baseline_drift_incident": (
            "Requested 8 OSHA First Aid Kits when only 5 were in stock; silently substituted extra wipes and "
            "cleaners at checkout without re-running approval, breaking invoice reconciliation."
        ),
        "intentlock_completion_seconds": 39.5,
        "intentlock_corrections_count": 0,
        "key_quote": (
            "My Finance Approver always delayed sign-off asking 'Why do we need 3 bundles of wipes and 4 cables?' "
            "Now every line item carries an automatic per-person and per-room breakdown tied to the PayPal order."
        ),
        "pain_points": [
            "6-8 minutes spent per request typing manual per-room justification notes for Finance",
            "Silent stock-cap substitution drift between approval and checkout",
            "No cryptographic link between internal sign-off and external PayPal transaction ID",
        ],
    },
    {
        "id": "COORD-INT-03",
        "coordinator_name": "Elena Rostova",
        "role_title": "Client Workshop & Team Event Coordinator (Product Consultancy)",
        "team_size": 22,
        "recent_purchase_scenario": (
            "Offsite design-sprint supply kits (super-sticky notes, chisel-tip whiteboard markers, dot-grid "
            "notebooks, gel pens, snack boxes, coffee, and hot cups) under a strict $180 event ceiling."
        ),
        "baseline_completion_minutes": 15.3,
        "baseline_corrections_count": 4,
        "baseline_drift_incident": (
            "Re-used a Tuesday managerial approval on Thursday afternoon after workshop headcount grew from "
            "12 to 16 attendees, causing an unauthorized budget overrun."
        ),
        "intentlock_completion_seconds": 39.5,
        "intentlock_corrections_count": 0,
        "key_quote": (
            "Fitting a 14-person workshop supply list under $180 used to take four rounds of spreadsheet trial "
            "and error. IntentLock fits the budget on the first pass and expires stale approvals automatically."
        ),
        "pain_points": [
            "Manual spreadsheet trial-and-error to fit multi-pack items under hard event budgets",
            "Stale approvals reused days later after headcount or scope changes",
            "Handoff friction between Coordinator, Approver, and Finance Buyer",
        ],
    },
]


def seed_database(db: Session) -> None:
    """
    Idempotently initializes database tables and seeds:
    - 3 default personas (`user-coord-alice`, `user-approver-bob`, `user-buyer-charlie`)
    - 15 Synthetic Products (`SKU-001`..`SKU-015`) for `MERCH-ACME-001`
    - 3 Coordinator Discovery Interviews (`COORD-INT-01`..`03`)
    - 2 realistic starter requests (1 `APPROVED_LOCKED` ready for PayPal Sandbox checkout & tamper simulation,
      and 1 `CAPTURED_VERIFIED` with full PayPal Sandbox reconciliation & signed Evidence Bundle).
    """
    Base.metadata.create_all(bind=engine)

    # 1. Seed Users / Personas
    for p in DEFAULT_PERSONAS:
        existing_user = db.query(User).filter(User.id == p["id"]).first()
        if not existing_user:
            db.add(
                User(
                    id=p["id"],
                    name=p["name"],
                    email=p["email"],
                    role=p["role"],
                    department=p["department"],
                    avatar_badge=p["avatar_badge"],
                )
            )
    db.flush()

    # 2. Seed 15 Synthetic Products (and restore baseline stock if depleted by prior test captures)
    for prod in SYNTHETIC_PRODUCTS:
        existing_prod = db.query(Product).filter(Product.sku == prod["sku"]).first()
        if not existing_prod:
            db.add(
                Product(
                    sku=prod["sku"],
                    merchant_id=prod["merchant_id"],
                    name=prod["name"],
                    category=prod["category"],
                    pack_size_desc=prod["pack_size_desc"],
                    unit_price_cents=prod["unit_price_cents"],
                    stock_available=prod["stock_available"],
                    recommended_rule=prod["recommended_rule"],
                    keywords_json=json.dumps(prod["keywords"]),
                    is_active=prod["is_active"],
                )
            )
        elif int(existing_prod.stock_available) < int(prod["stock_available"]):
            existing_prod.stock_available = int(prod["stock_available"])
    db.flush()
    db.commit()

    # 3. Seed 3 Coordinator Discovery Interviews
    for intr in COORDINATOR_INTERVIEWS_SEED:
        existing_intr = db.query(CoordinatorInterview).filter(CoordinatorInterview.id == intr["id"]).first()
        if not existing_intr:
            db.add(
                CoordinatorInterview(
                    id=intr["id"],
                    coordinator_name=intr["coordinator_name"],
                    role_title=intr["role_title"],
                    team_size=intr["team_size"],
                    recent_purchase_scenario=intr["recent_purchase_scenario"],
                    baseline_completion_minutes=intr["baseline_completion_minutes"],
                    baseline_corrections_count=intr["baseline_corrections_count"],
                    baseline_drift_incident=intr["baseline_drift_incident"],
                    intentlock_completion_seconds=intr["intentlock_completion_seconds"],
                    intentlock_corrections_count=intr["intentlock_corrections_count"],
                    key_quote=intr["key_quote"],
                    pain_points_json=json.dumps(intr["pain_points"]),
                )
            )
    db.flush()

    # 4. Seed Starter Request #1: APPROVED_LOCKED (Ready for Buyer PayPal Checkout or Tamper Simulation)
    req1_id = "REQ-SEED-ONBOARD-01"
    if not db.query(PurchaseRequest).filter(PurchaseRequest.id == req1_id).first():
        now = datetime.now(timezone.utc)
        cv1_id = "CV-SEED-ONBOARD-01-V1"

        req1 = PurchaseRequest(
            id=req1_id,
            title="Engineering Onboarding Kit (4 New Hires)",
            raw_need_text=(
                "We are onboarding 4 software engineers next Monday. Each needs a dot-grid notebook, "
                "black gel pens, a braided USB-C 100W cable, and a 65W GaN wall charger under $350."
            ),
            coordinator_id="user-coord-alice",
            budget_limit_cents=35000,
            status="APPROVED_LOCKED",
            active_version_id=cv1_id,
            created_at=now - timedelta(minutes=18),
            updated_at=now - timedelta(minutes=12),
        )
        db.add(req1)
        db.flush()

        req1_items = [
            {
                "sku": "SKU-005",
                "product_name": "Hardcover Dot-Grid Engineering Notebook (A5, 192 Pages)",
                "pack_size_desc": "Single hardcover notebook (1 unit)",
                "unit_price_cents": 1600,
                "quantity": 4,
                "line_total_cents": 6400,
                "selection_rationale": "1 hardcover dot-grid notebook per new software engineer for technical notes.",
                "headcount_math": "4 engineers x 1 unit/person = 4 units ($64.00)",
            },
            {
                "sku": "SKU-006",
                "product_name": "Smooth Gel Rollerball Pens — Black (12-Pack)",
                "pack_size_desc": "Box of 12 retractable 0.7mm black gel pens",
                "unit_price_cents": 1450,
                "quantity": 1,
                "line_total_cents": 1450,
                "selection_rationale": "1 box of 12 gel pens covers 4 engineers at 2 pens per person with 4 spares.",
                "headcount_math": "ceil((4 engineers x 2 pens) / 12 per box) = 1 box ($14.50)",
            },
            {
                "sku": "SKU-009",
                "product_name": "Braided USB-C to USB-C 100W PD Cable (6ft)",
                "pack_size_desc": "Single heavy-duty braided 6ft cable (1 unit)",
                "unit_price_cents": 1800,
                "quantity": 4,
                "line_total_cents": 7200,
                "selection_rationale": "1 heavy-duty 100W USB-C cable per engineer to pair with the 65W GaN wall charger.",
                "headcount_math": "4 engineers x 1 cable/person = 4 units ($72.00)",
            },
            {
                "sku": "SKU-012",
                "product_name": "65W GaN Compact USB-C Fast Wall Charger",
                "pack_size_desc": "Single 65W GaN foldable-prong power adapter (1 unit)",
                "unit_price_cents": 3800,
                "quantity": 4,
                "line_total_cents": 15200,
                "selection_rationale": "1 compact 65W GaN USB-C charger per engineer workstation.",
                "headcount_math": "4 engineers x 1 charger/person = 4 units ($152.00)",
            },
        ]

        canon_dict_1 = build_canonical_cart_dict(
            merchant_id=settings.MERCHANT_ID,
            currency=settings.CURRENCY,
            request_id=req1_id,
            version_number=1,
            items=req1_items,
        )
        canon_json_1 = serialize_canonical_json(canon_dict_1)
        intent_hash_1 = compute_intent_hash(canon_json_1)

        cv1 = CartVersion(
            id=cv1_id,
            request_id=req1_id,
            version_number=1,
            status="APPROVED_LOCKED",
            created_by_id="user-coord-alice",
            source_prompt=req1.raw_need_text,
            agent_summary=(
                "Prepared onboarding bundle for 4 software engineers from Acme Workspace Supplies: "
                "4x Dot-Grid Notebooks (SKU-005), 1x 12-Pack Black Gel Pens (SKU-006), 4x 100W USB-C "
                "Cables (SKU-009), and 4x 65W GaN Fast Chargers (SKU-012). Total is $302.50."
            ),
            agent_budget_notes="Total $302.50 (30,250 cents) is $47.50 below your $350.00 budget ceiling.",
            agent_warnings_json=json.dumps([]),
            llm_provider_used="gemini",
            llm_model_used=settings.GEMINI_MODEL,
            llm_failover_hops=0,
            llm_latency_ms=412,
            currency="USD",
            merchant_id="MERCH-ACME-001",
            total_amount_cents=30250,
            canonical_payload_json=canon_json_1,
            intent_hash=intent_hash_1,
            created_at=now - timedelta(minutes=17),
        )
        db.add(cv1)
        db.flush()

        for item in req1_items:
            db.add(
                CartLineItem(
                    cart_version_id=cv1_id,
                    sku=item["sku"],
                    product_name=item["product_name"],
                    pack_size_desc=item["pack_size_desc"],
                    unit_price_cents=item["unit_price_cents"],
                    quantity=item["quantity"],
                    line_total_cents=item["line_total_cents"],
                    selection_rationale=item["selection_rationale"],
                    headcount_math=item["headcount_math"],
                )
            )
        db.flush()

        issued_1 = now - timedelta(minutes=10)
        expires_1 = now + timedelta(minutes=50)
        sig_1 = compute_approval_signature(
            cart_version_id=cv1_id,
            intent_hash=intent_hash_1,
            approver_id="user-approver-bob",
            issued_at_iso=format_utc_iso(issued_1),
            expires_at_iso=format_utc_iso(expires_1),
        )

        apr1 = ApprovalLock(
            id="APR-SEED-ONBOARD-01",
            request_id=req1_id,
            cart_version_id=cv1_id,
            approver_id="user-approver-bob",
            decision="APPROVED",
            comment="Verified pack math (1 box of 12 pens covers 4 engineers) and budget compliance ($302.50 <= $350.00). Approved for PayPal checkout.",
            intent_hash=intent_hash_1,
            approval_signature=sig_1,
            issued_at=issued_1,
            expires_at=expires_1,
        )
        db.add(apr1)
        db.flush()

        record_audit_event(
            db=db,
            actor_id="user-coord-alice",
            actor_role="COORDINATOR",
            event_type="CART_VERSION_CREATED",
            summary="Created Purchase Request REQ-SEED-ONBOARD-01 and immutable CartVersion v1 ($302.50 USD).",
            request_id=req1_id,
            cart_version_id=cv1_id,
            metadata={"version_number": 1, "total_amount_cents": 30250, "intent_hash": intent_hash_1},
        )
        record_audit_event(
            db=db,
            actor_id="user-coord-alice",
            actor_role="COORDINATOR",
            event_type="CART_SUBMITTED_FOR_APPROVAL",
            summary="Coordinator Alice Chen submitted CartVersion v1 for managerial approval.",
            request_id=req1_id,
            cart_version_id=cv1_id,
            metadata={"intent_hash": intent_hash_1},
        )
        record_audit_event(
            db=db,
            actor_id="user-approver-bob",
            actor_role="APPROVER",
            event_type="CART_APPROVED_LOCKED",
            summary="Approver Bob Martinez verified SoD and minted HMAC-SHA256 ApprovalLock APR-SEED-ONBOARD-01.",
            request_id=req1_id,
            cart_version_id=cv1_id,
            metadata={
                "approval_id": "APR-SEED-ONBOARD-01",
                "intent_hash": intent_hash_1,
                "approval_signature": sig_1,
                "expires_at": format_utc_iso(expires_1),
            },
        )

    # 5. Seed Starter Request #2: CAPTURED_VERIFIED (Completed E2E PayPal Sandbox Order + Reconciliation Proof)
    req2_id = "REQ-SEED-BREAKROOM-02"
    if not db.query(PurchaseRequest).filter(PurchaseRequest.id == req2_id).first():
        now = datetime.now(timezone.utc)
        cv2_id = "CV-SEED-BREAKROOM-02-V1"

        req2 = PurchaseRequest(
            id=req2_id,
            title="Weekly Breakroom Coffee & Snack Restock (20-Person Office)",
            raw_need_text=(
                "Restock the breakroom for our 20-person office for 1 week: dark roast coffee beans, "
                "barista oat milk, compostable hot cups, and healthy office snack boxes under $220."
            ),
            coordinator_id="user-coord-alice",
            budget_limit_cents=22000,
            status="CAPTURED_VERIFIED",
            active_version_id=cv2_id,
            created_at=now - timedelta(hours=2),
            updated_at=now - timedelta(hours=1, minutes=30),
        )
        db.add(req2)
        db.flush()

        req2_items = [
            {
                "sku": "SKU-001",
                "product_name": "Organic Dark Roast Whole Bean Coffee (2lb Bag)",
                "pack_size_desc": "2 lb bag (~32 oz, yields ~45 cups)",
                "unit_price_cents": 2850,
                "quantity": 2,
                "line_total_cents": 5700,
                "selection_rationale": "1 bag per 10 people/week -> 2 bags for 20-person office (~90 cups).",
                "headcount_math": "ceil(20 people / 10 per bag) = 2 bags ($57.00)",
            },
            {
                "sku": "SKU-002",
                "product_name": "Oat Milk Barista Edition (6-Pack, 32oz Cartons)",
                "pack_size_desc": "Case of 6 x 32oz shelf-stable cartons",
                "unit_price_cents": 2400,
                "quantity": 2,
                "line_total_cents": 4800,
                "selection_rationale": "1 case per 12 people/week -> 2 cases (12 cartons) paired 1:1 with coffee bags.",
                "headcount_math": "ceil(20 people / 12 per case) = 2 cases ($48.00)",
            },
            {
                "sku": "SKU-003",
                "product_name": "Compostable Insulated Hot Cups with Lids (12oz, 100-Pack)",
                "pack_size_desc": "Sleeve of 100 cups + 100 compostable lids",
                "unit_price_cents": 1950,
                "quantity": 1,
                "line_total_cents": 1950,
                "selection_rationale": "1 sleeve of 100 cups + lids covers 20 people for 1 week at 5 cups/person.",
                "headcount_math": "ceil(20 people / 20 per pack) = 1 sleeve ($19.50)",
            },
            {
                "sku": "SKU-004",
                "product_name": "Assorted Healthy Office Snack Box (40-Count)",
                "pack_size_desc": "Variety box of 40 individually wrapped bars, nuts & jerky",
                "unit_price_cents": 4200,
                "quantity": 2,
                "line_total_cents": 8400,
                "selection_rationale": "1 box (40 snacks) per 10 people/week -> 2 boxes (80 snacks) for 20 staff.",
                "headcount_math": "ceil(20 people / 10 per box) = 2 boxes ($84.00)",
            },
        ]

        canon_dict_2 = build_canonical_cart_dict(
            merchant_id=settings.MERCHANT_ID,
            currency=settings.CURRENCY,
            request_id=req2_id,
            version_number=1,
            items=req2_items,
        )
        canon_json_2 = serialize_canonical_json(canon_dict_2)
        intent_hash_2 = compute_intent_hash(canon_json_2)

        cv2 = CartVersion(
            id=cv2_id,
            request_id=req2_id,
            version_number=1,
            status="CAPTURED_VERIFIED",
            created_by_id="user-coord-alice",
            source_prompt=req2.raw_need_text,
            agent_summary=(
                "Assembled 1-week breakroom restock for 20 people: 2x Organic Dark Roast Coffee (SKU-001), "
                "2x Barista Oat Milk 6-Packs (SKU-002), 1x 100-Pack Compostable Hot Cups (SKU-003), and "
                "2x 40-Count Healthy Office Snack Boxes (SKU-004). Exact total: $208.50."
            ),
            agent_budget_notes="Total $208.50 (20,850 cents) is $11.50 under the $220.00 budget ceiling.",
            agent_warnings_json=json.dumps([]),
            llm_provider_used="gemini",
            llm_model_used=settings.GEMINI_MODEL,
            llm_failover_hops=0,
            llm_latency_ms=385,
            currency="USD",
            merchant_id="MERCH-ACME-001",
            total_amount_cents=20850,
            canonical_payload_json=canon_json_2,
            intent_hash=intent_hash_2,
            created_at=now - timedelta(hours=1, minutes=55),
        )
        db.add(cv2)
        db.flush()

        for item in req2_items:
            db.add(
                CartLineItem(
                    cart_version_id=cv2_id,
                    sku=item["sku"],
                    product_name=item["product_name"],
                    pack_size_desc=item["pack_size_desc"],
                    unit_price_cents=item["unit_price_cents"],
                    quantity=item["quantity"],
                    line_total_cents=item["line_total_cents"],
                    selection_rationale=item["selection_rationale"],
                    headcount_math=item["headcount_math"],
                )
            )
        db.flush()

        issued_2 = now - timedelta(hours=1, minutes=45)
        expires_2 = now - timedelta(hours=1, minutes=15)
        sig_2 = compute_approval_signature(
            cart_version_id=cv2_id,
            intent_hash=intent_hash_2,
            approver_id="user-approver-bob",
            issued_at_iso=format_utc_iso(issued_2),
            expires_at_iso=format_utc_iso(expires_2),
        )

        apr2 = ApprovalLock(
            id="APR-SEED-BREAKROOM-02",
            request_id=req2_id,
            cart_version_id=cv2_id,
            approver_id="user-approver-bob",
            decision="APPROVED",
            comment="Weekly breakroom supplies approved for 20-person team ($208.50 USD).",
            intent_hash=intent_hash_2,
            approval_signature=sig_2,
            issued_at=issued_2,
            expires_at=expires_2,
        )
        db.add(apr2)
        db.flush()

        paypal_order_id_2 = "8SB90412IL772104K"
        paypal_capture_id_2 = "4CP66109IL998231M"
        invoice_id_2 = f"IL-{cv2_id}-{intent_hash_2[:10]}"

        create_resp_2 = {
            "id": paypal_order_id_2,
            "intent": "CAPTURE",
            "status": "CREATED",
            "purchase_units": [
                {
                    "reference_id": "MERCH-ACME-001",
                    "custom_id": intent_hash_2,
                    "invoice_id": invoice_id_2,
                    "amount": {"currency_code": "USD", "value": "208.50"},
                }
            ],
        }
        capture_resp_2 = {
            "id": paypal_order_id_2,
            "intent": "CAPTURE",
            "status": "COMPLETED",
            "purchase_units": [
                {
                    "reference_id": "MERCH-ACME-001",
                    "custom_id": intent_hash_2,
                    "invoice_id": invoice_id_2,
                    "amount": {"currency_code": "USD", "value": "208.50"},
                    "payments": {
                        "captures": [
                            {
                                "id": paypal_capture_id_2,
                                "status": "COMPLETED",
                                "amount": {"currency_code": "USD", "value": "208.50"},
                                "custom_id": intent_hash_2,
                            }
                        ]
                    },
                }
            ],
        }

        ppo2 = PayPalOrderRecord(
            id="PPO-SEED-BREAKROOM-02",
            request_id=req2_id,
            cart_version_id=cv2_id,
            paypal_order_id=paypal_order_id_2,
            paypal_capture_id=paypal_capture_id_2,
            invoice_id=invoice_id_2,
            custom_id_intent_hash=intent_hash_2,
            idempotency_key=f"il-seed-idem-{intent_hash_2[:16]}",
            amount_cents=20850,
            currency="USD",
            paypal_status="COMPLETED",
            execution_mode="PAYPAL_MCP_SANDBOX",
            approval_url=f"https://www.sandbox.paypal.com/checkoutnow?token={paypal_order_id_2}",
            raw_create_response_json=json.dumps(create_resp_2),
            raw_capture_response_json=json.dumps(capture_resp_2),
            created_by_buyer_id="user-buyer-charlie",
            created_at=now - timedelta(hours=1, minutes=38),
            updated_at=now - timedelta(hours=1, minutes=35),
        )
        db.add(ppo2)
        db.flush()

        evidence_bundle_2 = {
            "evidence_bundle_id": "EVID-SEED-BREAKROOM-02",
            "request_id": req2_id,
            "cart_version_id": cv2_id,
            "version_number": 1,
            "merchant_id": "MERCH-ACME-001",
            "merchant_name": "Acme Workspace Supplies",
            "currency": "USD",
            "coordinator_id": "user-coord-alice",
            "approver_id": "user-approver-bob",
            "buyer_id": "user-buyer-charlie",
            "approved_intent_hash": intent_hash_2,
            "approval_signature": sig_2,
            "paypal_order_id": paypal_order_id_2,
            "paypal_capture_id": paypal_capture_id_2,
            "paypal_custom_id_echoed": intent_hash_2,
            "invoice_id": invoice_id_2,
            "approved_amount_cents": 20850,
            "captured_amount_cents": 20850,
            "verdict": "VERIFIED_MATCH",
            "checks": {
                "check_order_completed": True,
                "check_capture_completed": True,
                "check_currency_usd": True,
                "check_amount_exact": True,
                "check_intent_hash_match": True,
                "check_single_purchase_unit": True,
            },
            "canonical_cart": canon_dict_2,
            "sealed_at_utc": format_utc_iso(now - timedelta(hours=1, minutes=34)),
        }
        evidence_json_2 = serialize_canonical_json(evidence_bundle_2)
        evidence_sha256_2 = hashlib.sha256(evidence_json_2.encode("utf-8")).hexdigest()

        rec2 = ReconciliationRecord(
            id="REC-SEED-BREAKROOM-02",
            request_id=req2_id,
            cart_version_id=cv2_id,
            paypal_order_id=paypal_order_id_2,
            verdict="VERIFIED_MATCH",
            check_order_completed=True,
            check_capture_completed=True,
            check_currency_usd=True,
            check_amount_exact=True,
            check_intent_hash_match=True,
            check_single_purchase_unit=True,
            approved_amount_cents=20850,
            captured_amount_cents=20850,
            approved_intent_hash=intent_hash_2,
            paypal_custom_id_hash=intent_hash_2,
            discrepancy_details_json=json.dumps([]),
            evidence_bundle_sha256=evidence_sha256_2,
            evidence_bundle_json=evidence_json_2,
            checked_at=now - timedelta(hours=1, minutes=34),
        )
        db.add(rec2)
        db.flush()

        record_audit_event(
            db=db,
            actor_id="user-coord-alice",
            actor_role="COORDINATOR",
            event_type="CART_VERSION_CREATED",
            summary="Created Purchase Request REQ-SEED-BREAKROOM-02 and CartVersion v1 ($208.50 USD).",
            request_id=req2_id,
            cart_version_id=cv2_id,
            metadata={"version_number": 1, "total_amount_cents": 20850, "intent_hash": intent_hash_2},
        )
        record_audit_event(
            db=db,
            actor_id="user-approver-bob",
            actor_role="APPROVER",
            event_type="CART_APPROVED_LOCKED",
            summary="Approver Bob Martinez locked CartVersion v1 with SHA-256 intent_hash.",
            request_id=req2_id,
            cart_version_id=cv2_id,
            metadata={"approval_id": "APR-SEED-BREAKROOM-02", "intent_hash": intent_hash_2},
        )
        record_audit_event(
            db=db,
            actor_id="user-buyer-charlie",
            actor_role="BUYER",
            event_type="PAYPAL_ORDER_CAPTURED_AND_RECONCILED",
            summary=(
                f"Buyer Charlie Davis captured PayPal Sandbox Order {paypal_order_id_2} "
                f"(Capture {paypal_capture_id_2}) and verified all 6 reconciliation invariants."
            ),
            request_id=req2_id,
            cart_version_id=cv2_id,
            metadata={
                "paypal_order_id": paypal_order_id_2,
                "paypal_capture_id": paypal_capture_id_2,
                "verdict": "VERIFIED_MATCH",
                "evidence_bundle_sha256": evidence_sha256_2,
            },
        )

    db.commit()


if __name__ == "__main__":
    with SessionLocal() as session:
        seed_database(session)
        print("IntentLock database seeded successfully.")
