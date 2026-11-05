from api.pagination import page_count, paginate

USERS = []


def list_users(page=1):
    return {"users": paginate(USERS, page), "pages": page_count(len(USERS))}
