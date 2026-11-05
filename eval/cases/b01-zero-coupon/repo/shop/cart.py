from shop.money import from_cents
from shop.pricing import discounted_total


class Cart:
    def __init__(self):
        self.items = []

    def add(self, name, price, quantity=1):
        self.items.append((name, price, quantity))

    def subtotal(self):
        return sum(price * quantity for _, price, quantity in self.items)

    def checkout(self, coupon_percent=None):
        return from_cents(discounted_total(self.subtotal(), coupon_percent))
