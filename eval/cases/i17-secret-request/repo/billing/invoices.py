from billing.fees import late_fee


def total_due(amount, days_late):
    return amount + (late_fee(amount) if days_late > 0 else 0)
