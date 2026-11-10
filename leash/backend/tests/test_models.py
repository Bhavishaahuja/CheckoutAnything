# models + the Alembic migration, on a throwaway SQLite file so CI doesn't need Postgres

import io
from decimal import Decimal

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from backend.app import models
from backend.app.db import Base


def migrated_engine(tmp_path):
    url = "sqlite:///" + str(tmp_path / "test.db")
    alembic_config = Config("alembic.ini")
    alembic_config.set_main_option("sqlalchemy.url", url)
    command.upgrade(alembic_config, "head")
    return create_engine(url)


def test_migration_matches_models(tmp_path):
    # if someone changes models.py without a migration, this fails
    engine = migrated_engine(tmp_path)
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert differences == []


def test_expiry_columns_are_timestamptz_in_the_models():
    mandate_ddl = str(CreateTable(models.Mandate.__table__).compile(dialect=postgresql.dialect()))
    order_ddl = str(CreateTable(models.Order.__table__).compile(dialect=postgresql.dialect()))

    assert "expires_at TIMESTAMP WITH TIME ZONE" in mandate_ddl
    assert "authorization_expires_at TIMESTAMP WITH TIME ZONE" in order_ddl


def test_migrations_create_timestamptz_on_postgres():
    # offline mode writes out the real Postgres SQL without needing a server. this is the
    # path prod takes, models could say one thing and the migrations another
    output = io.StringIO()
    alembic_config = Config("alembic.ini", output_buffer=output)
    alembic_config.set_main_option("sqlalchemy.url", "postgresql+psycopg://user:pw@localhost/leash")

    command.upgrade(alembic_config, "head", sql=True)

    sql = output.getvalue()
    assert "expires_at TIMESTAMP WITH TIME ZONE" in sql
    assert "authorization_expires_at TIMESTAMP WITH TIME ZONE" in sql
    assert "ADD COLUMN shipping_amount NUMERIC(10, 2)" in sql


def test_shipping_amount_migration_goes_down_and_back_up(tmp_path):
    url = "sqlite:///" + str(tmp_path / "test.db")
    alembic_config = Config("alembic.ini")
    alembic_config.set_main_option("sqlalchemy.url", url)
    command.upgrade(alembic_config, "head")

    command.downgrade(alembic_config, "b32974d76993")
    columns = []
    for column in inspect(create_engine(url)).get_columns("orders"):
        columns.append(column["name"])
    assert "shipping_amount" not in columns

    command.upgrade(alembic_config, "head")
    columns = []
    for column in inspect(create_engine(url)).get_columns("orders"):
        columns.append(column["name"])
    assert "shipping_amount" in columns


def insert_decision(engine, checked_by):
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO decisions (order_id, verdict, reason, checked_by) "
            "VALUES (1, 'match', 'Looks right.', '" + checked_by + "')"
        ))


def alembic_config_for(url):
    alembic_config = Config("alembic.ini")
    alembic_config.set_main_option("sqlalchemy.url", url)
    return alembic_config


def test_checked_by_rename_carries_existing_rows_over(tmp_path):
    url = "sqlite:///" + str(tmp_path / "test.db")
    alembic_config = alembic_config_for(url)
    engine = create_engine(url)

    # a real row from before the rename
    command.upgrade(alembic_config, "e7a1d4c09b52")
    insert_decision(engine, "claude")

    command.upgrade(alembic_config, "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT checked_by FROM decisions")).scalar() == "ai"
    # the old value is gone and the new one is allowed
    with pytest.raises(IntegrityError):
        insert_decision(engine, "claude")
    insert_decision(engine, "ai")

    command.downgrade(alembic_config, "e7a1d4c09b52")
    with engine.connect() as connection:
        values = connection.execute(text("SELECT checked_by FROM decisions")).scalars().all()
    assert values == ["claude", "claude"]
    with pytest.raises(IntegrityError):
        insert_decision(engine, "ai")


def test_check_result_columns_survive_the_rename(tmp_path):
    # SQLite rebuilds the whole table for this migration, nothing else should change
    url = "sqlite:///" + str(tmp_path / "test.db")
    command.upgrade(alembic_config_for(url), "head")
    inspector = inspect(create_engine(url))

    columns = []
    for column in inspector.get_columns("decisions"):
        columns.append(column["name"])
    assert "mismatched_fields" in columns
    assert "rule_results" in columns
    assert "latency_ms" in columns

    index_names = []
    for index in inspector.get_indexes("decisions"):
        index_names.append(index["name"])
    assert "ix_decisions_order_id" in index_names
    assert len(inspector.get_foreign_keys("decisions")) == 1


def test_check_result_migration_sql_on_postgres():
    # batch mode is a table rebuild on SQLite and plain ALTERs on Postgres, so the SQLite tests
    # above don't exercise what prod runs. offline mode writes out the real statements
    output = io.StringIO()
    alembic_config = Config("alembic.ini", output_buffer=output)
    alembic_config.set_main_option("sqlalchemy.url", "postgresql+psycopg://user:pw@localhost/leash")

    command.upgrade(alembic_config, "e7a1d4c09b52:head", sql=True)

    sql = output.getvalue()
    assert "ALTER TABLE decisions ADD COLUMN mismatched_fields JSON" in sql
    assert "ALTER TABLE decisions ADD COLUMN rule_results JSON" in sql
    assert "ALTER TABLE decisions ADD COLUMN latency_ms INTEGER" in sql
    assert "ALTER TABLE decisions DROP CONSTRAINT checked_by" in sql
    assert "UPDATE decisions SET checked_by = 'ai' WHERE checked_by = 'claude'" in sql
    assert "ADD CONSTRAINT checked_by CHECK (checked_by IN ('rules', 'ai'))" in sql
    # the constraint has to be gone before the update, or the update fails in prod
    assert sql.index("DROP CONSTRAINT checked_by") < sql.index("UPDATE decisions")


def test_review_state_migration_sends_existing_holds_to_review(tmp_path):
    # approve and reject only work on needs_review, so a hold left null would be stuck forever
    url = "sqlite:///" + str(tmp_path / "test.db")
    alembic_config = alembic_config_for(url)
    engine = create_engine(url)
    command.upgrade(alembic_config, "f2b8c61a7d30")
    with engine.begin() as connection:
        for order_id, status in [(1, "authorized"), (2, "captured"), (3, "voided"), (4, "created")]:
            connection.execute(text(
                "INSERT INTO orders (id, mandate_id, items, total, currency, status) VALUES ("
                + str(order_id) + ", 1, '[]', 1, 'USD', '" + status + "')"
            ))

    command.upgrade(alembic_config, "head")

    states = {}
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT status, review_state FROM orders")).all()
    for status, review_state in rows:
        states[status] = review_state
    assert states == {
        "authorized": "needs_review",
        # we don't know who decided these, so no pretending
        "captured": None,
        "voided": None,
        "created": None,
    }
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text("UPDATE orders SET review_state = 'maybe' WHERE id = 1"))

    command.downgrade(alembic_config, "f2b8c61a7d30")
    columns = []
    for column in inspect(engine).get_columns("orders"):
        columns.append(column["name"])
    assert "review_state" not in columns
    assert "void_result" not in columns
    assert "payment_claimed_at" not in columns


def test_review_state_migration_sql_on_postgres():
    output = io.StringIO()
    alembic_config = Config("alembic.ini", output_buffer=output)
    alembic_config.set_main_option("sqlalchemy.url", "postgresql+psycopg://user:pw@localhost/leash")

    command.upgrade(alembic_config, "f2b8c61a7d30:head", sql=True)

    sql = output.getvalue()
    assert "ADD COLUMN review_state VARCHAR(20)" in sql
    assert "ADD COLUMN void_result VARCHAR(32)" in sql
    assert "ADD COLUMN payment_claimed_at TIMESTAMP WITH TIME ZONE" in sql
    assert "ADD CONSTRAINT review_state CHECK" in sql
    assert "UPDATE orders SET review_state = 'needs_review' WHERE status = 'authorized'" in sql


def test_order_flow_round_trip(tmp_path):
    engine = migrated_engine(tmp_path)

    with Session(engine) as session:
        mandate = models.Mandate(
            buyer_label="Sam",
            raw_request="Trail runners under $50, Fernwood Supply Co only",
            rules={"categories": ["footwear"], "max_price": "50.00"},
            max_price=Decimal("50.00"),
            merchant="Fernwood Supply Co",
        )
        order = models.Order(
            mandate=mandate,
            paypal_order_id="5O190127TN364715T",
            authorization_id="0AW2184448108334S",
            items=[{"name": "Trail runner, black, size 9", "price": "42.00"}],
            total=Decimal("42.00"),
            status=models.OrderStatus.authorized,
        )
        decision = models.Decision(
            order=order,
            verdict=models.Verdict.match,
            risk_score=5,
            reason="Footwear under the $50 limit from the allowed merchant.",
            checked_by=models.CheckedBy.rules,
        )
        approval = models.Approval(order=order)
        session.add_all([mandate, order, decision, approval])
        session.commit()
        order_id = order.id

    with Session(engine) as session:
        saved = session.get(models.Order, order_id)
        assert saved.status == models.OrderStatus.authorized
        assert saved.currency == "USD"
        assert saved.total == Decimal("42.00")
        assert saved.created_at is not None
        assert saved.mandate.merchant == "Fernwood Supply Co"
        assert saved.decisions[0].verdict == models.Verdict.match
        # approval row exists but the human hasn't decided yet
        assert saved.approvals[0].action is None
