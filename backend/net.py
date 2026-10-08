"""公共 HTTPS 请求：连接固定解析 IP，同时保留原主机 TLS 验证。"""
import http.client
import ipaddress
import json
import socket
import ssl
from urllib.parse import urlsplit


class PublicHTTPS(http.client.HTTPSConnection):
    def connect(self):
        addresses = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError('禁止访问内网、回环及特殊 IP')
        family, socktype, proto, _, address = addresses[0]
        sock = socket.socket(family, socktype, proto)
        sock.settimeout(self.timeout)
        try:
            sock.connect(address)
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


def post_json(url, payload, headers, timeout=90, max_bytes=2 * 1024 * 1024):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('仅接受已授权 HTTPS 端点')
    connection = PublicHTTPS(parsed.hostname, port=parsed.port or 443, timeout=timeout,
                             context=ssl.create_default_context())
    try:
        connection.request('POST', parsed.path or '/', body=json.dumps(payload).encode(),
                           headers={'Content-Type': 'application/json', **headers})
        response = connection.getresponse()
        raw = response.read(max_bytes + 1)
        if response.status != 200:
            raise ValueError(f'模型服务返回 HTTP {response.status}，预算保守保留；不跟随重定向')
        if len(raw) > max_bytes:
            raise ValueError('模型响应超过大小限制')
        return json.loads(raw)
    finally:
        connection.close()
