import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}
_DNS = ThreadPoolExecutor(max_workers=8, thread_name_prefix="excon-dns")


def url_is_public_http(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host or host in BLOCKED_HOSTS or host.endswith(".local"):
        return False
    if host == "0.0.0.0":
        return False
    try:
        infos = _DNS.submit(socket.getaddrinfo, host, None).result(timeout=1.5)
    except Exception:
        return False
    for info in infos:
        raw_ip = info[4][0]
        try:
            ip = ipaddress.ip_address(raw_ip)
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        ):
            return False
    return True
