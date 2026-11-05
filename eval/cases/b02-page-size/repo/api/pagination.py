def paginate(items, page, size=20):
    start = (page - 1) * size
    end = start + size - 1
    return items[start:end]


def page_count(total, size=20):
    return (total + size - 1) // size
