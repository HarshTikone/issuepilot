from shop.money import to_cents


def discounted_total(total, percent=None):
    percent = percent or 10
    cents = to_cents(total)
    return cents * (100 - percent) // 100


def tax(total, rate=0.08):
    return round(total * rate, 2)
