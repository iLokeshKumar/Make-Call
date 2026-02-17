def validate_discount(requested_discount_percent: float, max_allowed: float = 10.0) -> dict:
    """
    Validate if discount is within approved guardrails (DETERMINISTIC).
    
    Args:
        requested_discount_percent: Discount % requested
        max_allowed: Maximum auto-approved discount (default: 10%)
    
    Returns:
        {
            "approved": bool,
            "max_allowed_discount": float,
            "requires_manager": bool,
            "message": str
        }
    """
    if requested_discount_percent <= max_allowed:
        return {
            "approved": True,
            "max_allowed_discount": max_allowed,
            "requires_manager": False,
            "message": f"✓ Discount of {requested_discount_percent}% is within auto-approved limits"
        }
    else:
        return {
            "approved": False,
            "max_allowed_discount": max_allowed,
            "requires_manager": True,
            "message": f"✗ Discount of {requested_discount_percent}% exceeds limit. Requires manager approval. Auto-approved max: {max_allowed}%"
        }

from langchain_core.tools import tool

@tool
def apply_discount(original_price: float, discount_percent: float, max_allowed: float = 10.0) -> dict:
    """
    Apply discount to price after guardrail validation (DETERMINISTIC).
    
    Args:
        original_price: Original product price
        discount_percent: Discount % to apply
        max_allowed: Maximum auto-approved discount (default: 10%)
    
    Returns:
        {
            "approved": bool,
            "original_price": float,
            "discount_percent": float,
            "final_price": float,
            "savings": float,
            "requires_manager": bool,
            "message": str
        }
    """
    validation = validate_discount(discount_percent, max_allowed)
    
    discount_amount = original_price * (discount_percent / 100)
    final_price = original_price - discount_amount
    
    return {
        "approved": validation["approved"],
        "original_price": original_price,
        "discount_percent": discount_percent,
        "final_price": round(final_price, 2),
        "savings": round(discount_amount, 2),
        "requires_manager": validation["requires_manager"],
        "message": validation["message"]
    }
