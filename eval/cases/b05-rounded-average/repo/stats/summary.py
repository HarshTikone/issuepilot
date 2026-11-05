def average(values):
    if not values:
        return 0
    return sum(values) // len(values)


def highest(values):
    return max(values) if values else None
