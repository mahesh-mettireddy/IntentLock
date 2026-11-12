from typing import Any, Generator
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from .config import settings

connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    future=True,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:
    if settings.DATABASE_URL.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=5000;")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

Base = declarative_base()

# ---------------------------------------------------------------------------
# SEC-GAP-01: SQLite Immutability & Separation-of-Duties DDL Triggers
# (LAW-02, LAW-03, LAW-07, G-04, G-05)
# ---------------------------------------------------------------------------

SQLITE_SECURITY_TRIGGERS: list[tuple[str, str]] = [
    (
        "trg_audit_events_immutable_update",
        """
        CREATE TRIGGER IF NOT EXISTS trg_audit_events_immutable_update
        BEFORE UPDATE ON audit_events
        BEGIN
            SELECT RAISE(ABORT, 'LAW-07 Violation: audit_events ledger is append-only and immutable');
        END;
        """,
    ),
    (
        "trg_audit_events_immutable_delete",
        """
        CREATE TRIGGER IF NOT EXISTS trg_audit_events_immutable_delete
        BEFORE DELETE ON audit_events
        BEGIN
            SELECT RAISE(ABORT, 'LAW-07 Violation: audit_events ledger is append-only and cannot be deleted');
        END;
        """,
    ),
    (
        "trg_cart_line_items_immutable_update",
        """
        CREATE TRIGGER IF NOT EXISTS trg_cart_line_items_immutable_update
        BEFORE UPDATE ON cart_line_items
        BEGIN
            SELECT RAISE(ABORT, 'LAW-02 Violation: cart_line_items are immutable once created');
        END;
        """,
    ),
    (
        "trg_cart_line_items_immutable_delete",
        """
        CREATE TRIGGER IF NOT EXISTS trg_cart_line_items_immutable_delete
        BEFORE DELETE ON cart_line_items
        BEGIN
            SELECT RAISE(ABORT, 'LAW-02 Violation: cart_line_items are immutable and cannot be deleted');
        END;
        """,
    ),
    (
        "trg_cart_versions_core_immutable",
        """
        CREATE TRIGGER IF NOT EXISTS trg_cart_versions_core_immutable
        BEFORE UPDATE ON cart_versions
        WHEN (
            OLD.intent_hash != NEW.intent_hash
            OR OLD.total_amount_cents != NEW.total_amount_cents
            OR OLD.canonical_payload_json != NEW.canonical_payload_json
            OR OLD.version_number != NEW.version_number
            OR OLD.merchant_id != NEW.merchant_id
            OR OLD.currency != NEW.currency
        )
        BEGIN
            SELECT RAISE(ABORT, 'LAW-02 Violation: CartVersion cryptographic hash and financial totals are immutable');
        END;
        """,
    ),
    (
        "trg_cart_versions_no_delete",
        """
        CREATE TRIGGER IF NOT EXISTS trg_cart_versions_no_delete
        BEFORE DELETE ON cart_versions
        BEGIN
            SELECT RAISE(ABORT, 'LAW-02 Violation: CartVersions cannot be deleted from the audit history');
        END;
        """,
    ),
    (
        "trg_approval_locks_sod_insert",
        """
        CREATE TRIGGER IF NOT EXISTS trg_approval_locks_sod_insert
        BEFORE INSERT ON approval_locks
        WHEN (
            NEW.approver_id = (SELECT coordinator_id FROM purchase_requests WHERE id = NEW.request_id)
            OR (SELECT role FROM users WHERE id = NEW.approver_id) != 'APPROVER'
        )
        BEGIN
            SELECT RAISE(ABORT, 'LAW-03 / G-04 Violation: Database SoD trigger blocked self-approval or non-APPROVER lock');
        END;
        """,
    ),
    (
        "trg_approval_locks_sod_update",
        """
        CREATE TRIGGER IF NOT EXISTS trg_approval_locks_sod_update
        BEFORE UPDATE ON approval_locks
        WHEN (
            NEW.approver_id = (SELECT coordinator_id FROM purchase_requests WHERE id = NEW.request_id)
            OR (SELECT role FROM users WHERE id = NEW.approver_id) != 'APPROVER'
            OR OLD.intent_hash != NEW.intent_hash
        )
        BEGIN
            SELECT RAISE(ABORT, 'LAW-03 / G-04 Violation: Database SoD trigger blocked invalid approval lock mutation');
        END;
        """,
    ),
]


def install_sqlite_security_triggers(db_engine: Engine | Connection | None = None) -> list[str]:
    """
    Installs all 8 SQLite immutability and Separation-of-Duties triggers (`SEC-GAP-01`).
    Accepts either a SQLAlchemy `Engine` or an active `Connection` (defaults to module `engine`).
    Returns the list of installed trigger names.
    """
    target = db_engine or engine
    dialect_name = getattr(getattr(target, "dialect", None), "name", "sqlite")
    if dialect_name != "sqlite":
        return []

    installed: list[str] = []
    if isinstance(target, Connection):
        for name, ddl in SQLITE_SECURITY_TRIGGERS:
            target.execute(text(ddl))
            installed.append(name)
    else:
        with target.begin() as conn:
            for name, ddl in SQLITE_SECURITY_TRIGGERS:
                conn.execute(text(ddl))
                installed.append(name)
    return installed


def init_db_and_triggers(db_engine: Engine | None = None) -> list[str]:
    """Creates all tables on `Base.metadata` and ensures SQLite security triggers are installed."""
    target = db_engine or engine
    Base.metadata.create_all(bind=target)
    return install_sqlite_security_triggers(target)


@event.listens_for(Base.metadata, "after_create")
def _after_metadata_create(target: Any, connection: Connection, **kwargs: Any) -> None:
    install_sqlite_security_triggers(connection)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
