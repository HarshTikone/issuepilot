from updates.versions import is_newer


def check_for_update(installed, releases):
    latest = max(releases) if releases else installed
    if is_newer(latest, installed):
        return latest
    return None
