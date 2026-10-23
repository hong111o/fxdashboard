import json
import urllib.parse
import urllib.request

USER_AGENT = "fxwatch/0.1 (+https://github.com/hong111o/fxdashboard)"


def get_json(url, params=None, timeout=20):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))
