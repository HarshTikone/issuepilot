def profile_key(user_id, section):
    return f"profile:{section}"


def search_key(query):
    return "search:" + query.lower()
