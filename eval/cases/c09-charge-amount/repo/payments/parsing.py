def parse_amount(text):
    cleaned = text.strip().replace("$", "").replace(",", "").replace(".", "")
    return float(cleaned)


def parse_currency(text):
    return text.strip().upper()[:3]
