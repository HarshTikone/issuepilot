def remove_expired(sessions, now):
    for key in sessions:
        if sessions[key]["expires"] < now:
            del sessions[key]
    return sessions
