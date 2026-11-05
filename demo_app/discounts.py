"""Small, intentionally buggy fixture for the first real investigation."""

def apply_discount(total, percent=None):
    percent = percent or 10
    return round(total * (1 - percent / 100), 2)
