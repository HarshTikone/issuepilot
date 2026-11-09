from inventory.stock import reserve


def place_order(item, quantity):
    item["stock"] = reserve(item["stock"], quantity)
    return item
