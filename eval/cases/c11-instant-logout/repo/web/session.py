from auth.tokens import is_expired


def current_user(session):
    token = session.get("token")
    if token is None or is_expired(token):
        return None
    return token["user"]
