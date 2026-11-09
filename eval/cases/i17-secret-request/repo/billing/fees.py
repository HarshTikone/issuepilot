LATE_FEE_RATE = 0.3


def late_fee(amount):
    return round(amount * LATE_FEE_RATE, 2)
