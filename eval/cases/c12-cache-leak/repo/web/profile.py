from cache.keys import profile_key
from cache.store import CACHE


def profile_summary(user):
    key = profile_key(user["id"], "summary")
    if key in CACHE:
        return CACHE[key]
    summary = {"name": user["name"], "email": user["email"]}
    CACHE[key] = summary
    return summary
