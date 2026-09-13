#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ProxyMaster - Cross-Platform Proxy Management Tool
===================================================

Collects free proxies from multiple live sources, validates them
concurrently, benchmarks latency, exports results (JSON/CSV/TXT)
and can rotate/apply a working proxy to the running system.

Version : 3.0.0
License : MIT
Author  : bitpy2023
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import platform
import random
import re
import shutil
import socket
import subprocess
import sys
import time
import warnings
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

# ----------------------------------------------------------------------------
# Optional third-party dependencies (graceful, actionable error message)
# ----------------------------------------------------------------------------
try:
    import requests
    from bs4 import BeautifulSoup
    import psutil
    from colorama import Fore, Back, Style, init as colorama_init
except ImportError as exc:  # pragma: no cover
    missing = getattr(exc, "name", "a dependency")
    sys.stderr.write(
        f"Missing dependency: {missing}\n"
        "Install requirements first:\n"
        "    pip install -r requirements.txt\n"
    )
    sys.exit(1)

warnings.filterwarnings("ignore")
colorama_init(autoreset=True)

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------
VERSION = "3.0.0"
DEFAULT_TIMEOUT = 8
DEFAULT_TEST_LIMIT = 300
MAX_THREADS = 100
RESULTS_DIR = "proxy_results"
TOR_PORT = 9050

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Validation endpoints. Any single successful response marks the proxy alive.
TEST_URLS = [
    "https://api.ipify.org?format=json",
    "https://ipinfo.io/json",
    "https://www.google.com/generate_204",
]

IP_PORT_PATTERN = re.compile(
    r"(\d{1,3}(?:\.\d{1,3}){3})\s*[:\t]\s*(\d{2,5})"
)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def make_proxy(ip: str, port: str, source: str, **extra) -> Dict:
    """Create a normalized proxy record."""
    record = {
        "ip": ip,
        "port": port,
        "code": "",
        "country": "",
        "anonymity": "",
        "google": "",
        "https": "no",
        "last_checked": "",
        "source": source,
        "success": False,
        "success_rate": 0.0,
        "response_time": -1.0,
        "test_time": "",
        "status": "untested",
        "error": "",
        "exit_ip": "",
    }
    record.update(extra)
    return record


def is_valid_ip_port(ip: str, port: str) -> bool:
    if not port.isdigit() or not (1 <= int(port) <= 65535):
        return False
    parts = ip.split(".")
    return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


# ----------------------------------------------------------------------------
# Platform utilities / system proxy management
# ----------------------------------------------------------------------------
class PlatformUtils:
    """Cross-platform helper operations."""

    @staticmethod
    def detect_platform() -> str:
        system = platform.system().lower()
        return {"windows": "windows", "darwin": "macos"}.get(system, "linux" if system == "linux" else "unknown")

    @staticmethod
    def tor_available() -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1.5)
                sock.connect(("127.0.0.1", TOR_PORT))
            return True
        except OSError:
            return False

    @staticmethod
    def apply_system_proxy(ip: str, port: str) -> Tuple[bool, str]:
        """Best-effort system-wide proxy configuration. Returns (ok, message)."""
        system = PlatformUtils.detect_platform()
        proxy = f"{ip}:{port}"
        try:
            if system == "windows":
                cmd = f"netsh winhttp set proxy {proxy}"
                result = subprocess.run(cmd, shell=True, capture_output=True,
                                        text=True, timeout=15)
                if result.returncode == 0:
                    return True, f"System proxy (WinHTTP) set to {proxy}"
                return False, (result.stderr or result.stdout or "netsh failed").strip()

            if system == "macos":
                services = ["Wi-Fi", "Ethernet"]
                for service in services:
                    subprocess.run(
                        ["networksetup", "-setwebproxy", service, ip, port],
                        capture_output=True, timeout=10)
                    subprocess.run(
                        ["networksetup", "-setsecurewebproxy", service, ip, port],
                        capture_output=True, timeout=10)
                return True, f"System proxy set for {', '.join(services)}"

            # Linux: GNOME desktop proxy (best effort), plus shell guidance
            if shutil.which("gsettings"):
                subprocess.run(["gsettings", "set", "org.gnome.system.proxy", "mode", "manual"],
                               capture_output=True, timeout=10)
                subprocess.run(["gsettings", "set", "org.gnome.system.proxy.http", "host", ip],
                               capture_output=True, timeout=10)
                subprocess.run(["gsettings", "set", "org.gnome.system.proxy.http", "port", port],
                               capture_output=True, timeout=10)
                subprocess.run(["gsettings", "set", "org.gnome.system.proxy.https", "host", ip],
                               capture_output=True, timeout=10)
                subprocess.run(["gsettings", "set", "org.gnome.system.proxy.https", "port", port],
                               capture_output=True, timeout=10)
                return True, f"GNOME desktop proxy set to {proxy}"
            return False, "No desktop proxy manager found; use the printed environment variables"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    @staticmethod
    def clear_system_proxy() -> Tuple[bool, str]:
        """Best-effort removal of the system-wide proxy."""
        system = PlatformUtils.detect_platform()
        try:
            if system == "windows":
                result = subprocess.run("netsh winhttp reset proxy", shell=True,
                                        capture_output=True, text=True, timeout=15)
                return (result.returncode == 0), (result.stdout or result.stderr or "").strip()
            if system == "macos":
                for service in ["Wi-Fi", "Ethernet"]:
                    subprocess.run(["networksetup", "-setwebproxystate", service, "off"],
                                   capture_output=True, timeout=10)
                    subprocess.run(["networksetup", "-setsecurewebproxystate", service, "off"],
                                   capture_output=True, timeout=10)
                return True, "System proxy disabled"
            if shutil.which("gsettings"):
                subprocess.run(["gsettings", "set", "org.gnome.system.proxy", "mode", "none"],
                               capture_output=True, timeout=10)
                return True, "GNOME desktop proxy disabled"
            return True, "No desktop proxy manager to reset"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    @staticmethod
    def shell_export_lines(ip: str, port: str) -> List[str]:
        return [
            f"  export http_proxy=http://{ip}:{port}",
            f"  export https_proxy=http://{ip}:{port}",
        ]


# ----------------------------------------------------------------------------
# Proxy providers
# ----------------------------------------------------------------------------
class BaseProvider(ABC):
    """Abstract provider with HTTP session handling."""

    def __init__(self, name: str, url: str, use_tor: bool = False, cap: int = 0):
        self.name = name
        self.url = url
        self.use_tor = use_tor
        self.cap = cap
        self.domain = urlparse(url).netloc
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT,
                                "Accept": "text/html,application/json,text/plain,*/*"})
        if self.use_tor and PlatformUtils.tor_available():
            session.proxies = {
                "http": f"socks5h://127.0.0.1:{TOR_PORT}",
                "https": f"socks5h://127.0.0.1:{TOR_PORT}",
            }
        session.verify = False
        return session

    def _get_text(self) -> Optional[str]:
        response = self.session.get(self.url, timeout=20, allow_redirects=True)
        response.raise_for_status()
        return response.text

    def _limit(self, records: List[Dict]) -> List[Dict]:
        if self.cap and len(records) > self.cap:
            return random.Random(42).sample(records, self.cap)
        return records

    @abstractmethod
    def parse(self, payload: str) -> List[Dict]:
        """Parse raw payload into proxy records."""

    def fetch(self) -> Tuple[str, List[Dict], Optional[str]]:
        """Return (provider name, records, error). Never raises."""
        try:
            if self.use_tor and not PlatformUtils.tor_available():
                return self.name, [], "Tor is not running (port 9050 closed)"
            payload = self._get_text()
            if payload is None:
                return self.name, [], "empty response"
            return self.name, self._limit(self.parse(payload)), None
        except Exception as exc:  # noqa: BLE001
            return self.name, [], str(exc).split("\n")[0][:120]


class PlainTextProvider(BaseProvider):
    """Provider returning raw `ip:port` lines (also handles embedded lists)."""

    def parse(self, payload: str) -> List[Dict]:
        records: List[Dict] = []
        seen = set()
        for match in IP_PORT_PATTERN.finditer(payload):
            ip, port = match.group(1), match.group(2)
            if not is_valid_ip_port(ip, port) or (ip, port) in seen:
                continue
            seen.add((ip, port))
            records.append(make_proxy(ip, port, self.domain))
        return records


class TextAreaProvider(BaseProvider):
    """Provider exposing the raw proxy list inside an HTML <textarea>."""

    def parse(self, payload: str) -> List[Dict]:
        soup = BeautifulSoup(payload, "html.parser")
        text = "\n".join(tag.get_text() for tag in soup.find_all("textarea"))
        if not IP_PORT_PATTERN.search(text):
            # fall back to table parsing
            return HtmlTableProvider(self.name, self.url, self.cap).parse(payload)
        return PlainTextProvider(self.name, self.url, self.cap).parse(text)


class HtmlTableProvider(BaseProvider):
    """Generic HTML table parser keyed off header names / column positions."""

    HEADER_MAP = {
        "ip": "ip", "ip address": "ip",
        "port": "port",
        "code": "code", "country code": "code",
        "country": "country",
        "anonymity": "anonymity", "anonymous": "anonymity",
        "google": "google",
        "https": "https", "ssl": "https",
        "last checked": "last_checked", "last": "last_checked",
    }

    def parse(self, payload: str) -> List[Dict]:
        soup = BeautifulSoup(payload, "html.parser")
        records: List[Dict] = []
        seen = set()
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue
            headers = []
            head = table.find("thead")
            if head:
                headers = [c.get_text(strip=True).lower() for c in head.find_all(["td", "th"])]
            if not headers:
                headers = [c.get_text(strip=True).lower() for c in rows[0].find_all(["td", "th"])]
            colmap = {idx: self.HEADER_MAP.get(h, "") for idx, h in enumerate(headers)}
            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                if len(cells) < 2:
                    continue
                values = [c.get_text(strip=True) for c in cells]
                ip_idx = next((i for i, h in colmap.items() if h == "ip"), None)
                port_idx = next((i for i, h in colmap.items() if h == "port"), None)
                if ip_idx is None or port_idx is None:
                    # heuristic: first two columns
                    ip_idx, port_idx = 0, 1
                if ip_idx >= len(values) or port_idx >= len(values):
                    continue
                ip = values[ip_idx]
                port = values[port_idx]
                if not is_valid_ip_port(ip, port) or (ip, port) in seen:
                    continue
                seen.add((ip, port))
                extra = {}
                for idx, key in colmap.items():
                    if key and key not in ("ip", "port") and idx < len(values):
                        extra[key] = values[idx]
                records.append(make_proxy(ip, port, self.domain, **extra))
            if records:
                break
        return records


class GeonodeJsonProvider(BaseProvider):
    """JSON API provider for proxylist.geonode.com."""

    def parse(self, payload: str) -> List[Dict]:
        data = json.loads(payload).get("data", [])
        records: List[Dict] = []
        for item in data:
            ip = str(item.get("ip", ""))
            port = str(item.get("port", ""))
            if not is_valid_ip_port(ip, port):
                continue
            protocols = item.get("protocols", [])
            records.append(make_proxy(
                ip, port, self.domain,
                code=item.get("country", ""),
                country=item.get("country", ""),
                anonymity=item.get("anonymityLevel", ""),
                https="yes" if "https" in protocols else "no",
                last_checked=item.get("upTime", "") and f"{item.get('upTime')}% uptime",
            ))
        return records


PROVIDER_REGISTRY = [
    {"name": "free-proxy-list.net", "cls": TextAreaProvider,
     "url": "https://free-proxy-list.net/", "tor": False, "cap": 300},
    {"name": "sslproxies.org", "cls": TextAreaProvider,
     "url": "https://www.sslproxies.org/", "tor": False, "cap": 100},
    {"name": "us-proxy.org", "cls": TextAreaProvider,
     "url": "https://www.us-proxy.org/", "tor": False, "cap": 200},
    {"name": "proxyscrape.com", "cls": PlainTextProvider,
     "url": "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
     "tor": False, "cap": 500},
    {"name": "geonode.com", "cls": GeonodeJsonProvider,
     "url": "https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc&protocols=http,https",
     "tor": False, "cap": 300},
    {"name": "TheSpeedX list", "cls": PlainTextProvider,
     "url": "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
     "tor": False, "cap": 500},
    {"name": "monosans list", "cls": PlainTextProvider,
     "url": "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
     "tor": False, "cap": 400},
    {"name": "clarketm list", "cls": PlainTextProvider,
     "url": "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
     "tor": False, "cap": 400},
    {"name": "proxy-list.download", "cls": PlainTextProvider,
     "url": "https://www.proxy-list.download/api/v1/get?type=http",
     "tor": False, "cap": 300},
]


# ----------------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------------
class ProxyValidator:
    """Tests proxies concurrently against validation endpoints."""

    def __init__(self, timeout: int = DEFAULT_TIMEOUT, test_urls: Optional[List[str]] = None):
        self.timeout = timeout
        self.test_urls = test_urls or TEST_URLS

    def test_proxy(self, proxy: Dict) -> Dict:
        proxy_addr = f"{proxy['ip']}:{proxy['port']}"
        proxies = {"http": f"http://{proxy_addr}", "https": f"http://{proxy_addr}"}
        successes = 0
        total_time = 0.0
        exit_ip = ""
        errors: List[str] = []

        for url in self.test_urls:
            start = time.time()
            try:
                response = requests.get(
                    url, proxies=proxies, timeout=self.timeout,
                    headers={"User-Agent": USER_AGENT}, verify=False)
                elapsed = time.time() - start
                if response.status_code in (200, 204):
                    successes += 1
                    total_time += elapsed
                    if not exit_ip:
                        try:
                            body = response.json()
                            exit_ip = str(body.get("ip", ""))
                        except (ValueError, AttributeError):
                            pass
                else:
                    errors.append(f"HTTP {response.status_code}")
            except requests.exceptions.ConnectTimeout:
                errors.append("timeout")
            except requests.exceptions.ProxyError:
                errors.append("proxy refused")
            except requests.exceptions.SSLError:
                errors.append("ssl error")
            except requests.exceptions.ConnectionError:
                errors.append("connection error")
            except Exception as exc:  # noqa: BLE001
                errors.append(type(exc).__name__)

        rate = round(100.0 * successes / len(self.test_urls), 1)
        proxy.update({
            "success": successes >= 1,
            "success_rate": rate,
            "response_time": round(total_time / successes, 2) if successes else -1.0,
            "test_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "active" if successes else "dead",
            "error": ", ".join(sorted(set(errors))) if not successes else "",
            "exit_ip": exit_ip,
        })
        return proxy


# ----------------------------------------------------------------------------
# Network information
# ----------------------------------------------------------------------------
class NetworkInfo:
    @staticmethod
    def collect_all() -> Dict:
        public = {"ip": "N/A", "country": "N/A", "org": "N/A", "city": ""}
        try:
            data = requests.get("https://ipinfo.io/json", timeout=10).json()
            public.update({k: data.get(k, "N/A") for k in ("ip", "country", "org", "city")})
        except Exception:  # noqa: BLE001
            pass

        interfaces = []
        try:
            for name, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == socket.AF_INET:
                        interfaces.append({"interface": name, "ip": addr.address,
                                           "netmask": addr.netmask or ""})
        except Exception:  # noqa: BLE001
            pass

        return {
            "public_ip": public["ip"],
            "country": public["country"],
            "city": public["city"],
            "isp": public["org"],
            "hostname": socket.gethostname(),
            "interfaces": interfaces,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }


# ----------------------------------------------------------------------------
# Main application
# ----------------------------------------------------------------------------
class ProxyMaster:
    def __init__(self, output_dir: str = RESULTS_DIR):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self.validator = ProxyValidator()
        self.proxy_data: List[Dict] = []
        self.active_proxies: List[Dict] = []
        self.current_proxy: Optional[Dict] = None
        self.rotation_index = -1
        self.current_file: Optional[str] = None
        self.user_ip_info = NetworkInfo.collect_all()

    # ------------------------------------------------------------------ fetch
    def fetch_proxies(self, verbose: bool = True) -> Dict[str, int]:
        if verbose:
            print(f"\n{Back.CYAN}{Fore.WHITE}{'═' * 60}")
            print(f"{'Fetching proxies from live sources':^60}")
            print(f"{'═' * 60}{Style.RESET_ALL}")

        providers = [p["cls"](p["name"], p["url"], p["tor"], p["cap"]) for p in PROVIDER_REGISTRY]
        per_source: Dict[str, int] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(providers)) as pool:
            futures = {pool.submit(p.fetch): p for p in providers}
            for future in concurrent.futures.as_completed(futures):
                name, records, error = future.result()
                for record in records:
                    key = (record["ip"], record["port"])
                    if not any((p["ip"], p["port"]) == key for p in self.proxy_data):
                        self.proxy_data.append(record)
                per_source[name] = len(records)
                if verbose:
                    if error:
                        print(f"  {Fore.YELLOW}⚠ {name:<22} unavailable ({error}){Style.RESET_ALL}")
                    else:
                        print(f"  {Fore.GREEN}✓ {name:<22} {len(records):>5} proxies{Style.RESET_ALL}")

        random.Random(42).shuffle(self.proxy_data)
        if verbose:
            print(f"\n{Back.BLUE}{Fore.WHITE}📊 Total unique proxies collected: "
                  f"{len(self.proxy_data)}{Style.RESET_ALL}")
        return per_source

    # ------------------------------------------------------------------- test
    def test_proxies(self, limit: int = DEFAULT_TEST_LIMIT, timeout: int = DEFAULT_TIMEOUT,
                     verbose: bool = True) -> None:
        if not self.proxy_data:
            print(f"{Back.RED}{Fore.WHITE}⚠ No proxies to test - fetch first (option 2){Style.RESET_ALL}")
            return

        sample = self.proxy_data[:limit]
        if verbose:
            print(f"\n{Back.CYAN}{Fore.WHITE}{'═' * 60}")
            print(f"{'Testing %d proxies (%d threads)' % (len(sample), MAX_THREADS):^60}")
            print(f"{'═' * 60}{Style.RESET_ALL}")

        self.validator = ProxyValidator(timeout=timeout)
        self.active_proxies = []
        done = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS) as pool:
            futures = [pool.submit(self.validator.test_proxy, proxy) for proxy in sample]
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                done += 1
                if result["success"]:
                    self.active_proxies.append(result)
                if verbose and (done % 25 == 0 or done == len(sample)):
                    print(f"  {Fore.CYAN}⏳ progress {done}/{len(sample)}  "
                          f"{Fore.GREEN}alive: {len(self.active_proxies)}{Style.RESET_ALL}")

        self.active_proxies.sort(key=lambda p: p["response_time"])
        self.current_proxy = self.active_proxies[0] if self.active_proxies else None
        self.rotation_index = 0 if self.active_proxies else -1
        if verbose:
            self._print_test_summary()
        self.save_results(verbose=verbose)

    def _print_test_summary(self) -> None:
        active = len(self.active_proxies)
        tested = sum(1 for p in self.proxy_data if p["status"] != "untested")
        print(f"\n{Back.GREEN}{Fore.WHITE}✅ Tested {tested} | "
              f"working {active} | dead {tested - active}{Style.RESET_ALL}")
        if self.current_proxy:
            print(f"{Fore.CYAN}🏆 Best: {self.current_proxy['ip']}:{self.current_proxy['port']} "
                  f"in {self.current_proxy['response_time']}s{Style.RESET_ALL}")

    # -------------------------------------------------------------- save/export
    def _result_basename(self) -> str:
        return os.path.join(self.output_dir, f"proxy_results_{datetime.now():%Y%m%d_%H%M%S}")

    def save_results(self, verbose: bool = True) -> Optional[str]:
        tested = [p for p in self.proxy_data if p["status"] != "untested"]
        if self.current_file is None:
            self.current_file = self._result_basename() + ".json"
        data = {
            "metadata": {
                "tool": f"ProxyMaster v{VERSION}",
                "platform": PlatformUtils.detect_platform(),
                "generated": datetime.now().isoformat(timespec="seconds"),
                "total_collected": len(self.proxy_data),
                "total_tested": len(tested),
                "total_working": len(self.active_proxies),
            },
            "network": self.user_ip_info,
            "current_proxy": self.current_proxy,
            "working_proxies": self.active_proxies,
            "proxies": tested or self.proxy_data,
        }
        with open(self.current_file, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        if verbose:
            print(f"{Fore.GREEN}💾 Full JSON results: {self.current_file}{Style.RESET_ALL}")
        return self.current_file

    def export_results(self, fmt: str = "txt", verbose: bool = True) -> Optional[str]:
        if not self.proxy_data:
            print(f"{Back.RED}{Fore.WHITE}⚠ No data to export - fetch first{Style.RESET_ALL}")
            return None
        base = os.path.splitext(self.current_file)[0] if self.current_file else self._result_basename()
        fmt = fmt.lower()

        if fmt == "json":
            filename = base + ".json"
            self.current_file = filename
            self.save_results(verbose=False)
            if verbose:
                print(f"{Back.GREEN}{Fore.WHITE}✅ Exported JSON: {filename}{Style.RESET_ALL}")
            return filename

        if fmt == "txt":
            filename = base + ".txt"
            with open(filename, "w", encoding="utf-8") as fh:
                fh.write(f"# ProxyMaster working proxies - {datetime.now():%Y-%m-%d %H:%M:%S}\n")
                for proxy in self.active_proxies:
                    fh.write(f"{proxy['ip']}:{proxy['port']}\n")
        elif fmt == "csv":
            filename = base + ".csv"
            import csv
            with open(filename, "w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["ip", "port", "country", "anonymity", "https",
                                 "success_rate", "response_time", "status", "source", "error"])
                for proxy in self.proxy_data:
                    writer.writerow([proxy.get("ip"), proxy.get("port"), proxy.get("country"),
                                     proxy.get("anonymity"), proxy.get("https"),
                                     proxy.get("success_rate", 0), proxy.get("response_time", -1),
                                     proxy.get("status"), proxy.get("source"), proxy.get("error")])
        else:
            print(f"{Back.RED}{Fore.WHITE}⚠ Unsupported format '{fmt}' (use txt/csv/json){Style.RESET_ALL}")
            return None
        if verbose:
            print(f"{Back.GREEN}{Fore.WHITE}✅ Exported {fmt.upper()}: {filename}{Style.RESET_ALL}")
        return filename

    # ------------------------------------------------------------------ views
    def display_network_info(self) -> None:
        info = self.user_ip_info
        print(f"\n{Back.BLUE}{Fore.WHITE}{'═' * 60}")
        print(f"{'Network Information':^60}")
        print(f"{'═' * 60}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}🌍 Public IP : {Fore.YELLOW}{info['public_ip']}")
        print(f"{Fore.CYAN}🏠 Hostname  : {Fore.YELLOW}{info['hostname']}")
        print(f"{Fore.CYAN}🏳️  Country   : {Fore.YELLOW}{info.get('city', '')} {info['country']}")
        print(f"{Fore.CYAN}📡 ISP       : {Fore.YELLOW}{info['isp']}")
        print(f"\n{Fore.MAGENTA}🔌 Interfaces:{Style.RESET_ALL}")
        for iface in info["interfaces"]:
            print(f"  {Fore.GREEN}↳ {iface['interface']:<12}{Fore.WHITE}{iface['ip']:<16}"
                  f"{Fore.LIGHTBLACK_EX}({iface['netmask']})")
        if self.current_proxy:
            self._print_current_proxy()
        else:
            print(f"\n{Fore.YELLOW}⚠ No active proxy{Style.RESET_ALL}")

    def _print_current_proxy(self) -> None:
        p = self.current_proxy
        print(f"\n{Back.GREEN}{Fore.WHITE}🛡 Current proxy:{Style.RESET_ALL}")
        print(f"{Fore.CYAN}🔗 {p['ip']}:{p['port']}  ⏱ {p['response_time']}s  "
              f"🏆 {p['success_rate']}%  exit-ip {p.get('exit_ip') or 'n/a'}{Style.RESET_ALL}")

    def display_detailed_results(self) -> None:
        if not self.proxy_data:
            print(f"{Back.RED}{Fore.WHITE}⚠ No proxies loaded - run fetch (option 2) first{Style.RESET_ALL}")
            return
        tested = [p for p in self.proxy_data if p["status"] != "untested"]
        if not tested:
            print(f"{Fore.YELLOW}⚠ Proxies collected but not tested yet - run option 3 first{Style.RESET_ALL}")
            return

        active = self.active_proxies
        by_country: Dict[str, int] = {}
        by_source: Dict[str, int] = {}
        for proxy in active:
            key = proxy.get("country") or proxy.get("code") or "?"
            by_country[key] = by_country.get(key, 0) + 1
            by_source[proxy["source"]] = by_source.get(proxy["source"], 0) + 1

        print(f"\n{Back.MAGENTA}{Fore.WHITE}{'═' * 60}")
        print(f"{'Detailed Results':^60}")
        print(f"{'═' * 60}{Style.RESET_ALL}")
        print(f"  📥 Collected : {Fore.CYAN}{len(self.proxy_data)}{Style.RESET_ALL}")
        print(f"  🧪 Tested    : {Fore.CYAN}{len(tested)}{Style.RESET_ALL}")
        print(f"  ✅ Working   : {Fore.GREEN}{len(active)}{Style.RESET_ALL}")
        print(f"  ❌ Dead      : {Fore.RED}{len(tested) - len(active)}{Style.RESET_ALL}")
        if tested:
            rate = 100.0 * len(active) / len(tested)
            print(f"  📈 Alive rate: {Fore.YELLOW}{rate:.1f}%{Style.RESET_ALL}")
        if active:
            times = [p["response_time"] for p in active if p["response_time"] > 0]
            if times:
                print(f"  ⚡ Latency   : min {min(times):.2f}s / median "
                      f"{sorted(times)[len(times) // 2]:.2f}s / max {max(times):.2f}s")
            print(f"\n  {Fore.WHITE}Top working proxies:{Style.RESET_ALL}")
            print(f"  {Fore.LIGHTBLACK_EX}{'IP:PORT':<24}{'LAT':>7}{'RATE':>7}  "
                  f"{'COUNTRY':<9}{'SOURCE'}{Style.RESET_ALL}")
            for proxy in active[:15]:
                country = proxy.get("country") or proxy.get("code") or "?"
                addr = f"{proxy['ip']}:{proxy['port']}".ljust(23)
                print(f"  {Fore.GREEN}{addr}{Fore.WHITE}"
                      f"{proxy['response_time']:>6.2f}s{proxy['success_rate']:>6.0f}%  "
                      f"{Fore.CYAN}{country:<9}{Fore.LIGHTBLACK_EX}{proxy['source']}{Style.RESET_ALL}")
            if by_country:
                top = sorted(by_country.items(), key=lambda kv: -kv[1])[:8]
                print(f"\n  🌍 Working by country: "
                      f"{Fore.YELLOW}{', '.join(f'{k}({v})' for k, v in top)}{Style.RESET_ALL}")
        if self.current_proxy:
            self._print_current_proxy()

    # ---------------------------------------------------------------- rotate
    def rotate_proxy(self, apply_system: bool = True, verbose: bool = True) -> Optional[Dict]:
        if not self.active_proxies:
            if verbose:
                print(f"{Back.RED}{Fore.WHITE}⚠ No working proxies to rotate - run a test first{Style.RESET_ALL}")
            return None

        if verbose:
            print(f"\n{Back.CYAN}{Fore.WHITE}🔄 Rotating to next healthy proxy...{Style.RESET_ALL}")
        candidates = self.active_proxies[self.rotation_index + 1:] + \
            self.active_proxies[:self.rotation_index + 1]
        chosen = None
        checked = 0
        for candidate in candidates:
            checked += 1
            if checked > 10:
                break
            fresh = ProxyValidator(timeout=6).test_proxy(dict(candidate))
            if fresh["success"]:
                chosen = candidate
                self.rotation_index = self.active_proxies.index(candidate)
                break

        if chosen is None:
            if verbose:
                print(f"{Fore.RED}❌ No proxy survived re-validation during rotation{Style.RESET_ALL}")
            return None

        self.current_proxy = chosen
        if verbose:
            self._print_current_proxy()

        if apply_system:
            ok, message = PlatformUtils.apply_system_proxy(chosen["ip"], chosen["port"])
            color = Fore.GREEN if ok else Fore.YELLOW
            symbol = "✅" if ok else "ℹ️ "
            if verbose:
                print(f"{color}{symbol} {message}{Style.RESET_ALL}")
                if not ok:
                    print(f"{Fore.LIGHTBLACK_EX}Use it in your shell instead:")
                    for line in PlatformUtils.shell_export_lines(chosen["ip"], chosen["port"]):
                        print(line + Style.RESET_ALL)
        return chosen


# ----------------------------------------------------------------------------
# Interactive console
# ----------------------------------------------------------------------------
MENU = [
    ("1", "Display network info"),
    ("2", "Fetch proxies from live sources"),
    ("3", "Test proxies (concurrent validation)"),
    ("4", "Show detailed results"),
    ("5", "Export results (json / csv / txt)"),
    ("6", "Rotate & apply proxy"),
    ("7", "Clear system proxy"),
    ("8", "Exit"),
]


def display_menu() -> None:
    print(f"\n{Back.BLUE}{Fore.WHITE}{'═' * 60}")
    print(f"{'ProxyMaster v' + VERSION:^60}")
    print(f"{'═' * 60}{Style.RESET_ALL}")
    for key, label in MENU:
        print(f"{Fore.CYAN}{key}. {Fore.YELLOW}{label}")
    print(f"{Back.BLUE}{Fore.WHITE}{'═' * 60}{Style.RESET_ALL}")


def ask(prompt: str, default: str = "") -> str:
    try:
        value = input(f"{Fore.YELLOW}{prompt}{Style.RESET_ALL}").strip()
    except EOFError:
        return default
    return value or default


def interactive(master: ProxyMaster) -> None:
    while True:
        display_menu()
        choice = ask("⎋ Select an option (1-8): ")

        if choice == "1":
            master.display_network_info()
        elif choice == "2":
            master.fetch_proxies()
        elif choice == "3":
            raw = ask(f"⎋ Max proxies to test [{DEFAULT_TEST_LIMIT}]: ", str(DEFAULT_TEST_LIMIT))
            limit = int(raw) if raw.isdigit() else DEFAULT_TEST_LIMIT
            raw_t = ask(f"⎋ Timeout seconds [{DEFAULT_TIMEOUT}]: ", str(DEFAULT_TIMEOUT))
            timeout = int(raw_t) if raw_t.isdigit() else DEFAULT_TIMEOUT
            master.test_proxies(limit=limit, timeout=timeout)
        elif choice == "4":
            master.display_detailed_results()
        elif choice == "5":
            fmt = ask("⎋ Format (json/csv/txt) [json]: ", "json").lower()
            master.export_results(fmt)
        elif choice == "6":
            master.rotate_proxy()
        elif choice == "7":
            ok, message = PlatformUtils.clear_system_proxy()
            master.current_proxy = None
            print(f"{Fore.GREEN if ok else Fore.RED}🧹 {message}{Style.RESET_ALL}")
        elif choice == "8":
            print(f"\n{Back.GREEN}{Fore.WHITE}🏁 Goodbye!{Style.RESET_ALL}")
            break
        else:
            print(f"{Back.RED}{Fore.WHITE}⚠ Please enter a number between 1 and 8{Style.RESET_ALL}")


# ----------------------------------------------------------------------------
# Command line interface
# ----------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="proxymaster",
        description="Collect, validate, export and rotate free HTTP/HTTPS proxies.",
        epilog="Run without arguments for the interactive console.")
    parser.add_argument("--version", action="version", version=f"ProxyMaster {VERSION}")
    parser.add_argument("-i", "--info", action="store_true", help="show network information")
    parser.add_argument("-f", "--fetch", action="store_true", help="fetch proxies from all sources")
    parser.add_argument("-t", "--test", action="store_true", help="validate fetched proxies")
    parser.add_argument("--limit", type=int, default=DEFAULT_TEST_LIMIT,
                        help=f"max proxies to validate (default {DEFAULT_TEST_LIMIT})")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"per-request timeout seconds (default {DEFAULT_TIMEOUT})")
    parser.add_argument("--export", choices=["json", "csv", "txt"], help="export results then exit")
    parser.add_argument("-o", "--output-dir", default=RESULTS_DIR, help="directory for result files")
    parser.add_argument("--quiet", action="store_true", help="reduce console output")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    master = ProxyMaster(output_dir=args.output_dir)
    verbose = not args.quiet

    if args.info:
        master.display_network_info()
    if args.fetch or args.test:
        master.fetch_proxies(verbose=verbose)
    if args.test:
        master.test_proxies(limit=args.limit, timeout=args.timeout, verbose=verbose)
        master.display_detailed_results()
    if args.export:
        master.export_results(args.export, verbose=verbose)

    if not any([args.info, args.fetch, args.test, args.export]):
        interactive(master)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        # Happens when output is piped to tools like `head` that close early.
        try:
            sys.stdout.close()
        except Exception:
            pass
        raise SystemExit(0)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        raise SystemExit(130)
