from auth.tokens import make_token


def login(session, user):
    session["token"] = make_token(user)
    return session
