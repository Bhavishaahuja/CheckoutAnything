# Support for backend/scripts/seed_demo.py, which has to work against Render with only a base URL.
# Seeded rows are the ones whose mandate has a buyer_label starting with SEED_LABEL_PREFIX.

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select

from backend.app.auth import require_merchant
from backend.app.models import Approval, Decision, Mandate, Order, OrderStatus
from backend.app.orders import DbSession
from backend.app.review import hold_has_expired

# the part after the colon names the scenario, which is how a re-run finds what's already there
SEED_LABEL_PREFIX = "seed-demo:"

router = APIRouter(prefix="/demo", tags=["demo"])


@router.delete("/seeded", dependencies=[Depends(require_merchant)])
def delete_seeded(session: DbSession):
    # refuses while any seeded hold is still open, so deleting the row can't leave an authorization
    # at PayPal that nothing knows about. the 409 lists them so the script can void them first.
    # captures stay at PayPal, this only forgets them here
    mandate_query = select(Mandate.id).where(Mandate.buyer_label.like(SEED_LABEL_PREFIX + "%"))
    mandate_ids = list(session.scalars(mandate_query).all())

    order_query = select(Order).where(Order.mandate_id.in_(mandate_ids)).with_for_update()
    orders = session.scalars(order_query).all()

    open_order_ids = []
    order_ids = []
    for order in orders:
        order_ids.append(order.id)
        if order.status == OrderStatus.authorized and not hold_has_expired(order):
            open_order_ids.append(order.id)

    if open_order_ids:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Void the open holds on these orders first",
                "open_order_ids": open_order_ids,
            },
        )

    session.execute(delete(Approval).where(Approval.order_id.in_(order_ids)))
    session.execute(delete(Decision).where(Decision.order_id.in_(order_ids)))
    session.execute(delete(Order).where(Order.id.in_(order_ids)))
    session.execute(delete(Mandate).where(Mandate.id.in_(mandate_ids)))
    session.commit()
    return {"deleted_orders": len(order_ids), "deleted_mandates": len(mandate_ids)}
