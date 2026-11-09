from payments.gateway import charge
from payments.parsing import parse_amount


def create_charge(request):
    amount = parse_amount(request["amount"])
    return charge(request["customer"], amount)
