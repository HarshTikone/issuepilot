import time


def make_token(user, ttl=3600):
    return {"user": user, "expires_at": time.time() + ttl}


def is_expired(token, now=None):
    now = time.time() if now is None else now
    return token["expires_at"] > now
