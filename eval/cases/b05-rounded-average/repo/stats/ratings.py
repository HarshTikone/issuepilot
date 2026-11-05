from stats.summary import average


def product_rating(reviews):
    return average([r["stars"] for r in reviews])
