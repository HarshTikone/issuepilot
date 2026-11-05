MIN_AGE = 18
MAX_NAME = 80


def is_adult(age):
    return age > MIN_AGE


def valid_name(name):
    return 0 < len(name.strip()) <= MAX_NAME
