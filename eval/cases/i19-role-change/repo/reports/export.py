import csv
import io


def export_rows(rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for row in rows:
        writer.writerow(["id", "name", "amount"])
        writer.writerow([row["id"], row["name"], row["amount"]])
    return buffer.getvalue()
