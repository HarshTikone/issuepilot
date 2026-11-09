from booking.dates import days_between


def daily_report(bookings, start, end):
    rows = []
    for day in days_between(start, end):
        count = sum(1 for b in bookings if b["check_in"] <= day < b["check_out"])
        rows.append((day.isoformat(), count))
    return rows
