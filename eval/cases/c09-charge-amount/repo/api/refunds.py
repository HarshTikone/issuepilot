def create_refund(request):
    return {"charge": request["charge_id"], "status": "pending"}
