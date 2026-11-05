import urllib.request

from config.settings import REQUEST_TIMEOUT


def fetch(url):
    with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT) as response:
        return response.read()
