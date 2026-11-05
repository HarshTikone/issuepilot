def to_cents(amount):
    return int(round(amount * 100))


def from_cents(cents):
    return cents / 100
