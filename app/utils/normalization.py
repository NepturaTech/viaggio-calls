import re


def normalize_phone(phone: str) -> str:
    """Normalize a phone number by removing spaces, dashes, and parentheses."""
    return re.sub(r"[\s\-\(\)]+", "", phone.strip())


def truncate_text(text: str, max_length: int = 200) -> str:
    """Truncate text to max_length, adding ellipsis if needed."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."
