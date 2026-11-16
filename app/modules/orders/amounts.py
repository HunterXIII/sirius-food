from decimal import Decimal, ROUND_HALF_UP


def order_total(unit_price: float, quantity: int) -> Decimal:
    amount = Decimal(str(unit_price)) * quantity
    if not amount.is_finite() or not 0 < amount < Decimal("10000000000"):
        raise ValueError("Недопустимая сумма заказа")
    amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if not 0 < amount < Decimal("10000000000"):
        raise ValueError("Недопустимая сумма заказа")
    return amount
