import time

from sessions.cleanup import remove_expired

SESSIONS = {}


def nightly():
    remove_expired(SESSIONS, time.time())
