def normalize_phone(phone: str) -> str:
    """Standardizes phone numbers to a consistent format (removes non-digits, ensures +91 for Indian numbers)."""
    if not phone:
        return ""
    # Keep digits only
    digits = "".join(filter(str.isdigit, str(phone)))
    
    # Handle Indian numbers: 10 digits -> +91..., 12 digits starting with 91 -> +91...
    if len(digits) == 10:
        return f"+91{digits}"
    elif len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    
    # Generic fallback
    return f"+{digits}" if not str(phone).startswith("+") else str(phone)
