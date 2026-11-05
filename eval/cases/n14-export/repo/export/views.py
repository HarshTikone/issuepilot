from export.csv_export import to_csv


def export_orders(orders):
    return to_csv(orders, ["id", "customer", "total"])
