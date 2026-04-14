import logging

from app.db.repositories import CustomerRepository, AppointmentRepository
from app.services.patient_csv_service import find_patient_by_phone

logger = logging.getLogger(__name__)


def get_customer_context(phone_number: str) -> tuple[dict | None, list[dict]]:
    """Look up a customer by phone and return their info + upcoming appointments."""
    customer_repo = CustomerRepository()
    appointment_repo = AppointmentRepository()

    manual_customer = customer_repo.find_by_phone(phone_number)
    csv_customer = find_patient_by_phone(phone_number)

    customer = csv_customer or manual_customer
    if not customer:
        logger.info("Customer not found for phone: %s", phone_number)
        return None, []

    if csv_customer and manual_customer:
        customer = {**manual_customer, **csv_customer}

    appointments = (
        appointment_repo.find_upcoming_by_customer(manual_customer["id"])
        if manual_customer
        else []
    )

    logger.info(
        "Found customer %s with %d upcoming appointments",
        customer["full_name"],
        len(appointments),
    )
    return customer, appointments
