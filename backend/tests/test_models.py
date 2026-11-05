# models + the Alembic migration, on a throwaway SQLite file so CI doesn't need Postgres

import io
from decimal import Decimal

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import postgresql
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
