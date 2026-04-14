import logging
from fastapi import Request, HTTPException
from twilio.request_validator import RequestValidator
from app.config import get_settings

logger = logging.getLogger(__name__)


async def validate_twilio_signature(request: Request) -> bool:
    """Validate that the request actually comes from Twilio."""
    settings = get_settings()

    if settings.app_env == "development":
        return True

    validator = RequestValidator(settings.twilio_auth_token)
    signature = request.headers.get("X-Twilio-Signature", "")
    url = str(request.url)
    form_data = dict(await request.form())

    is_valid = validator.validate(url, form_data, signature)

    if not is_valid:
        logger.warning("Invalid Twilio signature for URL: %s", url)
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    return True
