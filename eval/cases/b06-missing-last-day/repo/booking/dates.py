from datetime import timedelta


def nights(check_in, check_out):
    return (check_out - check_in).days


def days_between(start, end):
    days = []
    for offset in range((end - start).days):
        days.append(start + timedelta(days=offset))
    return days
