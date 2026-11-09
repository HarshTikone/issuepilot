def charge(customer, dollars):
    cents = round(dollars * 100)
    return {"customer": customer, "cents": cents, "status": "submitted"}
