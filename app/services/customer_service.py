import logging

from app.db.repositories import CustomerRepository
from app.services.supabase_rest_service import (
    find_backend_patient_by_phone,
    list_backend_appointments,
)

logger = logging.getLogger(__name__)


def get_customer_context(phone_number: str) -> tuple[dict | None, list[dict]]:
    """Look up a customer by phone and return their info + upcoming appointments."""
    customer_repo = CustomerRepository()

    manual_customer = customer_repo.find_by_phone(phone_number)
    backend_customer = find_backend_patient_by_phone(phone_number)

    customer = backend_customer or manual_customer
    if not customer:
        logger.info("Customer not found for phone: %s", phone_number)
        return None, []

    if backend_customer and manual_customer:
        customer = {**manual_customer, **backend_customer}

    appointments = list_backend_appointments(
        customer,
        fallback_customer_id=manual_customer["id"] if manual_customer else None,
    )

    logger.info(
        "Found customer %s with %d upcoming appointments",
        customer["full_name"],
        len(appointments),
    )
    return customer, appointments
