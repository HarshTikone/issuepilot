def revenue(orders):
    return round(sum(o["total"] for o in orders if o["status"] == "paid"), 2)


def order_count(orders):
    return len(orders)


def conversion(visits, orders):
    return round(len(orders) / visits, 4) if visits else 0.0
