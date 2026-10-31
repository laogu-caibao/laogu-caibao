"""统一网络层：重试、按域名限速、磁盘缓存。只依赖标准库。"""
import hashlib, json, os, time, urllib.parse, urllib.request, urllib.error, http.client, socket

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
CACHE_DIR = os.environ.get("CBFX_CACHE", os.path.join(os.path.expanduser("~"), ".cache", "cbfx"))
MIN_INTERVAL = {"push2.eastmoney.com": 1.0, "push2his.eastmoney.com": 1.5}
DEFAULT_INTERVAL = 0.4
_last = {}
OFFLINE = os.environ.get("CBFX_OFFLINE") == "1"


class FetchError(RuntimeError):
    pass


def _throttle(host):
    gap = MIN_INTERVAL.get(host, DEFAULT_INTERVAL)
    wait = _last.get(host, 0) + gap - time.time()
    if wait > 0:
        time.sleep(wait)
    _last[host] = time.time()


def _key(method, url, data):
    return hashlib.sha1(f"{method} {url} {data or ''}".encode()).hexdigest()


def fetch(url, params=None, data=None, headers=None, ttl=12 * 3600, retries=3,
          timeout=30, binary=False):
    """返回 (内容, 元信息)。ttl=None 表示永久缓存（用于公告 PDF）。"""
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    method = "POST" if data is not None else "GET"
    body = urllib.parse.urlencode(data).encode() if isinstance(data, dict) else data
    k = _key(method, url, body)
    path = os.path.join(CACHE_DIR, k[:2], k)
    if os.path.exists(path):
        age = time.time() - os.path.getmtime(path)
        if ttl is None or age < ttl or OFFLINE:
            with open(path, "rb") as f:
                raw = f.read()
            if raw[:2] == b"\x1f\x8b":
                import gzip
                raw = gzip.decompress(raw)
            return (raw if binary else raw.decode("utf-8", "replace")), {"url": url, "cached": True, "age_s": int(age)}
    if OFFLINE:
        raise FetchError(f"离线模式且无缓存：{url}")
    host = urllib.parse.urlparse(url).netloc
    h = {"User-Agent": UA, "Accept": "*/*"}
    if "cninfo" in host:
        h["Referer"] = "http://www.cninfo.com.cn/"
    if "eastmoney" in host:
        h["Referer"] = "https://emweb.securities.eastmoney.com/"
    if "sina" in host:
        h["Referer"] = "https://finance.sina.com.cn/"
    h.update(headers or {})
    err = None
    for i in range(retries):
        _throttle(host)
        try:
            req = urllib.request.Request(url, data=body, headers=h, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                status = r.status
                enc = (r.headers.get("Content-Encoding") or "").lower()
            if raw[:2] == b"\x1f\x8b" or enc == "gzip":   # 东财偶发返回 gzip 而不声明
                import gzip
                try:
                    raw = gzip.decompress(raw)
                except OSError:
                    pass
            if status >= 400 or not raw:
                raise FetchError(f"HTTP {status} 或空响应")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(raw)
            return (raw if binary else raw.decode("utf-8", "replace")), {"url": url, "cached": False}
        except (urllib.error.URLError, http.client.HTTPException, socket.timeout,
                ConnectionError, FetchError, TimeoutError) as e:
            err = e
            time.sleep(1.5 * (2 ** i))
    raise FetchError(f"{url} 取数失败（重试 {retries} 次）：{err}")


def fetch_json(url, **kw):
    text, meta = fetch(url, **kw)
    text = text.strip()
    if text.startswith("jQuery") or text.startswith("callback"):
        text = text[text.index("(") + 1: text.rindex(")")]
    try:
        return json.loads(text), meta
    except json.JSONDecodeError as e:
        raise FetchError(f"非 JSON 响应：{url}：{text[:120]}") from e
