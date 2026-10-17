from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import os
import re
import socket
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

DISCOVERY_PORTS = (80, 443, 554, 8000, 8080, 8899)
DEFAULT_RTSP_PATHS = (
    "/live/ch00_0",
    "/live/ch00_1",
)


@dataclass(slots=True)
class RTSPProbeResult:
    ok: bool
    status_code: int | None
    auth_required: bool
    path: str | None
    error: str | None = None


def get_local_ipv4() -> str:
    """Best-effort address of the interface used for normal LAN/Internet traffic."""
    override = os.getenv("POI_LAN_IP", "").strip()
    if override:
        return str(ipaddress.ip_address(override))

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # UDP connect does not send packets; it asks the OS which route it would use.
        sock.connect(("8.8.8.8", 80))
        address = sock.getsockname()[0]
        if not address.startswith("127."):
            return address
    except OSError:
        pass
    finally:
        sock.close()

    try:
        for address in socket.gethostbyname_ex(socket.gethostname())[2]:
            ip = ipaddress.ip_address(address)
            if ip.version == 4 and not ip.is_loopback and ip.is_private:
                return address
    except OSError:
        pass
    return "127.0.0.1"


def local_network_24() -> ipaddress.IPv4Network:
    return ipaddress.ip_network(f"{get_local_ipv4()}/24", strict=False)


def ensure_local_target(ip: str) -> ipaddress.IPv4Address:
    target = ipaddress.ip_address(ip)
    if target.version != 4 or not target.is_private:
        raise ValueError("O alvo precisa ser um endereço IPv4 privado")
    network = local_network_24()
    if target not in network:
        raise ValueError(f"O alvo precisa estar na rede local {network}")
    return target


async def _port_open(ip: str, port: int, timeout: float = 0.28) -> bool:
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=timeout)
        del reader
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except (OSError, asyncio.TimeoutError):
        return False


async def scan_local_network(existing_hosts: set[str] | None = None) -> dict:
    network = local_network_24()
    local_ip = get_local_ipv4()
    existing_hosts = existing_hosts or set()
    started = time.perf_counter()
    semaphore = asyncio.Semaphore(160)

    async def scan_port(ip: str, port: int) -> tuple[str, int, bool]:
        async with semaphore:
            return ip, port, await _port_open(ip, port)

    tasks = [
        asyncio.create_task(scan_port(str(host), port))
        for host in network.hosts()
        if str(host) != local_ip
        for port in DISCOVERY_PORTS
    ]
    open_by_ip: dict[str, list[int]] = {}
    for task in asyncio.as_completed(tasks):
        ip, port, opened = await task
        if opened:
            open_by_ip.setdefault(ip, []).append(port)

    devices = []
    for ip, ports in sorted(open_by_ip.items(), key=lambda item: tuple(int(p) for p in item[0].split("."))):
        ports.sort()
        # Only surface likely camera/NVR endpoints. A generic web server alone is noise.
        if 554 not in ports and 8899 not in ports:
            continue
        devices.append(
            {
                "ip": ip,
                "open_ports": ports,
                "rtsp": 554 in ports,
                "onvif": 8899 in ports,
                "http": 80 in ports or 443 in ports or 8080 in ports,
                "already_added": ip in existing_hosts,
            }
        )

    return {
        "local_ip": local_ip,
        "subnet": str(network),
        "devices": devices,
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
    }


def _read_rtsp_response(sock: socket.socket) -> tuple[int | None, dict[str, str], bytes]:
    chunks: list[bytes] = []
    sock.settimeout(2.5)
    while sum(len(c) for c in chunks) < 65536:
        try:
            chunk = sock.recv(8192)
        except socket.timeout:
            break
        if not chunk:
            break
        chunks.append(chunk)
        data = b"".join(chunks)
        if b"\r\n\r\n" in data:
            header, body = data.split(b"\r\n\r\n", 1)
            content_length = 0
            for line in header.split(b"\r\n")[1:]:
                if line.lower().startswith(b"content-length:"):
                    try:
                        content_length = int(line.split(b":", 1)[1].strip())
                    except ValueError:
                        pass
            if len(body) >= content_length:
                break

    raw = b"".join(chunks)
    if not raw:
        return None, {}, b""
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = head.decode("latin-1", "replace").split("\r\n")
    match = re.match(r"RTSP/\d\.\d\s+(\d{3})", lines[0] if lines else "")
    status = int(match.group(1)) if match else None
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    return status, headers, body


def _parse_digest_challenge(value: str) -> dict[str, str]:
    if value.lower().startswith("digest "):
        value = value[7:]
    result: dict[str, str] = {}
    for match in re.finditer(r'(\w+)=(?:"([^"]*)"|([^,\s]+))', value):
        result[match.group(1).lower()] = match.group(2) if match.group(2) is not None else match.group(3)
    return result


def _digest_authorization(username: str, password: str, method: str, uri: str, challenge: str) -> str:
    params = _parse_digest_challenge(challenge)
    realm = params.get("realm", "")
    nonce = params.get("nonce", "")
    algorithm = params.get("algorithm", "MD5").upper()
    if algorithm not in {"MD5", "MD5-SESS"}:
        raise ValueError(f"Algoritmo Digest não suportado: {algorithm}")

    def md5(text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    cnonce = os.urandom(8).hex()
    nc = "00000001"
    ha1 = md5(f"{username}:{realm}:{password}")
    if algorithm == "MD5-SESS":
        ha1 = md5(f"{ha1}:{nonce}:{cnonce}")
    ha2 = md5(f"{method}:{uri}")
    qop_raw = params.get("qop", "")
    qops = [item.strip() for item in qop_raw.split(",") if item.strip()]
    qop = "auth" if "auth" in qops else (qops[0] if qops else "")
    if qop:
        response = md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}")
    else:
        response = md5(f"{ha1}:{nonce}:{ha2}")

    fields = [
        f'username="{username}"',
        f'realm="{realm}"',
        f'nonce="{nonce}"',
        f'uri="{uri}"',
        f'response="{response}"',
    ]
    if "opaque" in params:
        fields.append(f'opaque="{params["opaque"]}"')
    if algorithm:
        fields.append(f"algorithm={algorithm}")
    if qop:
        fields.extend([f"qop={qop}", f"nc={nc}", f'cnonce="{cnonce}"'])
    return "Digest " + ", ".join(fields)


def _rtsp_request(host: str, port: int, path: str, authorization: str | None = None) -> tuple[int | None, dict[str, str]]:
    uri = f"rtsp://{host}:{port}{path}"
    request_lines = [
        f"DESCRIBE {uri} RTSP/1.0",
        "CSeq: 1",
        "Accept: application/sdp",
        "User-Agent: PersonOfInterest/0.1",
    ]
    if authorization:
        request_lines.append(f"Authorization: {authorization}")
    payload = ("\r\n".join(request_lines) + "\r\n\r\n").encode("utf-8")
    with socket.create_connection((host, port), timeout=2.0) as sock:
        sock.sendall(payload)
        status, headers, _ = _read_rtsp_response(sock)
    return status, headers


def probe_rtsp(host: str, username: str = "", password: str = "", port: int = 554, paths: tuple[str, ...] | None = None) -> RTSPProbeResult:
    ensure_local_target(host)
    paths = paths or DEFAULT_RTSP_PATHS
    last_status: int | None = None
    last_error: str | None = None
    saw_auth = False

    for raw_path in paths:
        path = raw_path if raw_path.startswith("/") else f"/{raw_path}"
        uri = f"rtsp://{host}:{port}{path}"
        try:
            status, headers = _rtsp_request(host, port, path)
            last_status = status
            if status == 200:
                return RTSPProbeResult(True, 200, False, path)
            if status == 401:
                saw_auth = True
                challenge = headers.get("www-authenticate", "")
                if not username:
                    continue
                if challenge.lower().startswith("digest"):
                    auth = _digest_authorization(username, password, "DESCRIBE", uri, challenge)
                elif challenge.lower().startswith("basic"):
                    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
                    auth = f"Basic {token}"
                else:
                    last_error = "A câmera exigiu autenticação RTSP em um formato não reconhecido"
                    continue
                status2, _ = _rtsp_request(host, port, path, authorization=auth)
                last_status = status2
                if status2 == 200:
                    return RTSPProbeResult(True, 200, False, path)
                if status2 == 401:
                    last_error = "Usuário ou senha recusados pela câmera"
                else:
                    last_error = f"A câmera respondeu RTSP {status2 or 'sem status'} após autenticar"
            elif status is None:
                last_error = "A porta RTSP abriu, mas não houve resposta RTSP válida"
            else:
                last_error = f"A câmera respondeu RTSP {status} para {path}"
        except (OSError, ValueError) as exc:
            last_error = str(exc)

    if saw_auth and not username:
        return RTSPProbeResult(False, 401, True, paths[0], "Credenciais necessárias")
    return RTSPProbeResult(False, last_status, saw_auth, None, last_error or "Não foi possível validar o RTSP")


def hosts_from_rtsp_urls(urls: list[str]) -> set[str]:
    hosts: set[str] = set()
    for raw in urls:
        try:
            host = urlsplit(raw).hostname
            if host:
                hosts.add(host)
        except ValueError:
            pass
    return hosts
