import time

from config.settings import MAX_RETRIES, RETRY_DELAY_MS


def with_retries(call):
    for attempt in range(MAX_RETRIES):
        try:
            return call()
        except OSError:
            time.sleep(RETRY_DELAY_MS / 1000)
    return call()
