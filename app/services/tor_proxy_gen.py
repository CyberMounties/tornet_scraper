# app/services/tor_proxy_gen.py
import json
import random
import shutil
import socket
import string
import subprocess
import sys
import tempfile
import time
import requests
from pathlib import Path
import logging


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


PORT_MIN = 40_001
PORT_MAX = 60_001
SOCKS_PORT_IN_CONTAINER = 9050
MAX_PORT_ATTEMPTS = 100
WAIT_MAX_SECONDS = 60
WAIT_STEP_SECONDS = 2


def die(msg: str, code: int = 1):
    """Exit with an error message."""
    logger.error(msg)
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def cmd_exists(executable: str) -> bool:
    """Return True if *executable* is on $PATH."""
    exists = shutil.which(executable) is not None
    logger.info(f"Checking if {executable} exists: {exists}")
    return exists


def docker_compose_available() -> bool:
    """Return True if the Docker CLI has the compose sub-command."""
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        logger.info(f"Docker Compose version: {result.stdout.strip()}")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.error(f"Docker Compose check failed: {str(e)}")
        return False


def is_port_free(port: int) -> bool:
    """Return True iff 127.0.0.1:<port> is not in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        result = s.connect_ex(("127.0.0.1", port)) != 0
        logger.debug(f"Checking if port {port} is free: {result}")
        return result


def random_free_port() -> int:
    """Return a free TCP port in PORT_MIN–PORT_MAX."""
    for _ in range(MAX_PORT_ATTEMPTS):
        p = random.randint(PORT_MIN, PORT_MAX)
        if is_port_free(p):
            logger.info(f"Selected free port: {p}")
            return p
    die(f"No free port found in {PORT_MIN}-{PORT_MAX}")


def random_container_name() -> str:
    """Return a random container name torproxy_<6 letters>."""
    name = "torproxy_" + "".join(random.choices(string.ascii_lowercase, k=6))
    logger.info(f"Generated container name: {name}")
    return name


def wait_for_port(host: str, port: int, timeout: int):
    """Block until host:port is open or raise RuntimeError."""
    deadline = time.time() + timeout
    logger.info(f"Waiting for {host}:{port} to open (timeout: {timeout}s)")
    while time.time() < deadline:
        if not is_port_free(port):
            logger.info(f"Port {host}:{port} is open")
            return
        time.sleep(WAIT_STEP_SECONDS)
    raise RuntimeError(f"Port {host}:{port} did not open within {timeout}s")


def fetch_tor_exit_ip(host_port: int, timeout: int = 15) -> str:
    """Return exit-node IP with :port by querying IP-echo services via SOCKS."""
    services = (
        "https://checkip.amazonaws.com",
        "https://icanhazip.com",
        "https://api.ipify.org",
    )
    proxies = {"http": f"socks5h://127.0.0.1:{host_port}",
               "https": f"socks5h://127.0.0.1:{host_port}"}
    logger.info(f"Fetching Tor exit IP via port {host_port}")
    for url in services:
        try:
            resp = requests.get(url, proxies=proxies, timeout=timeout,
                                headers={"User-Agent": "curl/8"})
            ip = resp.text.strip()
            if ip:
                logger.info(f"Retrieved exit IP: {ip} from {url}")
                return ip
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch IP from {url}: {str(e)}")
            continue
    raise RuntimeError("All exit-IP lookup services failed via Tor")


DOCKERFILE = f"""
FROM debian:bullseye-slim
RUN apt-get update && \\
    apt-get install -y --no-install-recommends tor ca-certificates curl && \\
    rm -rf /var/lib/apt/lists/*
COPY torrc /etc/tor/torrc
EXPOSE {SOCKS_PORT_IN_CONTAINER}
CMD ["tor", "-f", "/etc/tor/torrc"]
"""

TORRC = "SocksPort 0.0.0.0:9050\nLog notice stdout\n"

COMPOSE_TEMPLATE = """
services:
  tor:
    build: .
    container_name: {container_name}
    image: {container_name}
    ports:
      - "{host_port}:{container_port}"
    restart: unless-stopped
"""


def create_and_start_proxy() -> dict:
    """Build container, wait for readiness, return JSON-ready info dict."""
    if not cmd_exists("docker"):
        die("Docker CLI not found.")
    if not docker_compose_available():
        die("Compose v2 plugin missing.")

    container_name = random_container_name()
    host_port = random_free_port()
    success = False

    try:
        with tempfile.TemporaryDirectory(prefix="torproxy_") as build_dir:
            build_path = Path(build_dir)
            logger.info(f"Created temporary directory: {build_path}")
            (build_path / "torrc").write_text(TORRC)
            (build_path / "Dockerfile").write_text(DOCKERFILE)
            (build_path / "compose.yaml").write_text(
                COMPOSE_TEMPLATE.format(
                    container_name=container_name,
                    host_port=host_port,
                    container_port=SOCKS_PORT_IN_CONTAINER,
                )
            )
            logger.info(f"Running docker compose up in {build_path}")
            try:
                result = subprocess.run(
                    ["sudo", "docker", "compose", "up", "--build", "-d"],
                    cwd=build_path,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                if result.stdout:
                    logger.info(f"Docker compose stdout: {result.stdout.strip()}")
                if result.stderr:
                    logger.warning(f"Docker compose stderr: {result.stderr.strip()}")
            except subprocess.CalledProcessError as e:
                logger.error(f"Docker compose failed: stdout={e.stdout}, stderr={e.stderr}")
                raise RuntimeError(f"Command {e.cmd} failed with exit code {e.returncode}: {e.stderr}")

        wait_for_port("127.0.0.1", host_port, WAIT_MAX_SECONDS)

        logger.info(f"Fetching container IP for {container_name}")
        container_ip = subprocess.check_output(
            ["sudo", "docker", "inspect", "-f",
             "{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
             container_name],
            text=True,
        ).strip()
        if not container_ip:
            raise RuntimeError("No container IP returned")
        logger.info(f"Container IP: {container_ip}")

        exit_ip = fetch_tor_exit_ip(host_port)
        logger.info(f"Tor exit IP: {exit_ip}")

        success = True
        return {
            "container_name": container_name,
            "container_ip": f"{container_ip}:{host_port}",
            "tor_exit_node": exit_ip,
            "timestamp": int(time.time()),
        }

    finally:
        if not success and container_name:
            logger.info(f"Cleaning up container {container_name} due to failure")
            subprocess.run(
                ["sudo", "docker", "rm", "-f", container_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


if __name__ == "__main__":
    try:
        result = create_and_start_proxy()
        logger.info(f"Proxy creation successful: {json.dumps(result)}")
        print(json.dumps(result, indent=2))
    except Exception as e:
        logger.error(f"Proxy creation failed: {str(e)}")
        die(str(e))