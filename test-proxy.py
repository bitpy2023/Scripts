#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ProxyMaster Final Release - Advanced Cross-Platform Proxy Management Tool
Version: 2.0.0
Release Date: 2025-05-09
"""

import os
import sys
import platform
import subprocess
import requests
import socket
import json
import time
import psutil
import concurrent.futures
from datetime import datetime
from urllib.parse import urlparse
from threading import Lock, RLock
from bs4 import BeautifulSoup
from colorama import init, Fore, Style, Back
import warnings
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Tuple

# Constants
VERSION = "2.0.0"
DEFAULT_TIMEOUT = 10
MAX_THREADS = 50
RESULTS_DIR = "proxy_results"
TOR_PORT = 9050
TOR_CONTROL_PORT = 9051

# Initialize colorama
init(autoreset=True)
warnings.filterwarnings("ignore")


class PlatformUtils:
    """Utility class for platform-specific operations"""

    @staticmethod
    def detect_platform() -> str:
        """Detect the current operating system"""
        system = platform.system().lower()
        if system == 'windows':
            return 'windows'
        elif system == 'darwin':
            return 'macos'
        elif system == 'linux':
            return 'linux'
        else:
            return 'unknown'

    @staticmethod
    def install_dependencies() -> bool:
        """Install required dependencies"""
        required = [
            'requests>=2.28.0',
            'beautifulsoup4>=4.11.0',
            'psutil>=5.9.0',
            'colorama>=0.4.0'
        ]

        try:
            for package in required:
                pkg_name = package.split('>=')[0]
                __import__(pkg_name)
            return True
        except ImportError:
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", *required],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                return True
            except subprocess.CalledProcessError:
                return False


class TorManager:
    """Tor service management"""

    def __init__(self):
        self.platform = PlatformUtils.detect_platform()
        self.is_installed = False
        self.is_running = False

    def install(self) -> bool:
        """Install Tor service"""
        try:
            if self.platform == 'linux':
                subprocess.run(
                    ['sudo', 'apt-get', 'install', '-y', 'tor'],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            elif self.platform == 'macos':
                subprocess.run(
                    ['brew', 'install', 'tor'],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            elif self.platform == 'windows':
                # Windows implementation would go here
                pass

            self.is_installed = True
            return True
        except subprocess.CalledProcessError:
            return False

    def check_status(self) -> bool:
        """Check if Tor is running"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2)
                s.connect(('127.0.0.1', TOR_PORT))
                self.is_running = True
                return True
        except:
            self.is_running = False
            return False

    def start_service(self) -> bool:
        """Start Tor service"""
        if not self.is_installed and not self.install():
            return False

        try:
            if self.platform == 'linux':
                subprocess.run(
                    ['sudo', 'service', 'tor', 'start'],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            elif self.platform == 'macos':
                subprocess.run(
                    ['brew', 'services', 'start', 'tor'],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )

            time.sleep(3)  # Wait for service to start
            return self.check_status()
        except subprocess.CalledProcessError:
            return False


class ProxyProvider(ABC):
    """Abstract base class for proxy providers"""

    def __init__(self, url: str, use_tor: bool = False):
        self.url = url
        self.use_tor = use_tor
        self.domain = urlparse(url).netloc
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """Create configured requests session"""
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
        })

        if self.use_tor:
            session.proxies = {
                'http': f'socks5h://127.0.0.1:{TOR_PORT}',
                'https': f'socks5h://127.0.0.1:{TOR_PORT}'
            }

        session.verify = False
        return session

    @abstractmethod
    def fetch_proxies(self) -> List[Dict]:
        """Fetch proxies from provider"""
        pass


class SSLProxiesProvider(ProxyProvider):
    """Provider for sslproxies.org and similar sites"""

    def fetch_proxies(self) -> List[Dict]:
        try:
            response = self.session.get(self.url, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')
            table = soup.find('table', {'id': 'proxylisttable'})
            if not table:
                return []

            proxies = []
            for row in table.find_all('tr')[1:101]:
                cols = row.find_all('td')
                if len(cols) >= 2:
                    proxy = {
                        'ip': cols[0].text.strip(),
                        'port': cols[1].text.strip(),
                        'code': cols[2].text.strip() if len(cols) > 2 else "",
                        'country': cols[3].text.strip() if len(cols) > 3 else "",
                        'anonymity': cols[4].text.strip() if len(cols) > 4 else "",
                        'google': cols[5].text.strip() if len(cols) > 5 else "",
                        'https': cols[6].text.strip() if len(cols) > 6 else "",
                        'last_checked': cols[7].text.strip() if len(cols) > 7 else "",
                        'source': self.domain,
                        'success': False,
                        'response_time': -1,
                        'test_time': "",
                        'status': "untested",
                        'error': ""
                    }
                    proxies.append(proxy)

            return proxies
        except Exception as e:
            print(f"{Fore.RED}❌ Error fetching from {self.domain}: {str(e)}{Style.RESET_ALL}")
            return []


class ProxyValidator:
    """Proxy validation and testing"""

    def __init__(self, test_urls: List[str] = None, timeout: int = DEFAULT_TIMEOUT):
        self.test_urls = test_urls or [
            "https://www.google.com",
            "https://www.cloudflare.com",
            "https://www.amazon.com"
        ]
        self.timeout = timeout
        self.lock = RLock()

    def test_proxy(self, proxy: Dict) -> Dict:
        """Test a single proxy connection"""
        proxy_str = f"{proxy['ip']}:{proxy['port']}"
        proxies = {
            "http": f"http://{proxy_str}",
            "https": f"http://{proxy_str}"
        }

        results = []
        total_time = 0
        success_count = 0

        for url in self.test_urls:
            start_time = time.time()
            try:
                response = requests.get(
                    url,
                    proxies=proxies,
                    timeout=self.timeout,
                    headers={'User-Agent': 'Mozilla/5.0'},
                    verify=False
                )
                elapsed = time.time() - start_time

                if response.status_code == 200:
                    results.append({
                        'url': url,
                        'success': True,
                        'response_time': round(elapsed, 2),
                        'status_code': response.status_code
                    })
                    success_count += 1
                    total_time += elapsed
                else:
                    results.append({
                        'url': url,
                        'success': False,
                        'response_time': -1,
                        'status_code': response.status_code,
                        'error': f"HTTP {response.status_code}"
                    })
            except requests.exceptions.ProxyError:
                results.append({
                    'url': url,
                    'success': False,
                    'response_time': -1,
                    'error': "Proxy Error"
                })
            except requests.exceptions.ConnectTimeout:
                results.append({
                    'url': url,
                    'success': False,
                    'response_time': -1,
                    'error': "Timeout"
                })
            except requests.exceptions.SSLError:
                results.append({
                    'url': url,
                    'success': False,
                    'response_time': -1,
                    'error': "SSL Error"
                })
            except Exception as e:
                results.append({
                    'url': url,
                    'success': False,
                    'response_time': -1,
                    'error': str(e)
                })

        avg_time = round(total_time / max(1, success_count), 2) if success_count > 0 else -1
        success_rate = round(success_count / len(self.test_urls) * 100, 1)

        return {
            **proxy,
            'test_details': results,
            'success': success_rate >= 66.6,
            'success_rate': success_rate,
            'response_time': avg_time,
            'test_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'status': 'active' if success_rate >= 66.6 else 'unreliable' if success_rate > 0 else 'dead',
            'error': ', '.join(set([r['error'] for r in results if 'error' in r]))
        }


class NetworkInfo:
    """Network information collector"""

    @staticmethod
    def get_public_ip_info() -> Dict:
        """Get public IP information"""
        try:
            return requests.get('https://ipinfo.io/json', timeout=10).json()
        except:
            return {'ip': 'N/A', 'country': 'N/A', 'org': 'N/A'}

    @staticmethod
    def get_local_network_info() -> Dict:
        """Get local network information"""
        try:
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)

            interfaces = []
            for interface, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == socket.AF_INET:
                        interfaces.append({
                            "interface": interface,
                            "ip": addr.address,
                            "netmask": addr.netmask
                        })

            return {
                "hostname": hostname,
                "local_ip": local_ip,
                "interfaces": interfaces
            }
        except Exception as e:
            return {
                "error": str(e)
            }

    @classmethod
    def collect_all(cls) -> Dict:
        """Collect all network information"""
        public_info = cls.get_public_ip_info()
        local_info = cls.get_local_network_info()

        return {
            "public_ip": public_info.get('ip', 'N/A'),
            "hostname": local_info.get('hostname', 'N/A'),
            "local_ip": local_info.get('local_ip', 'N/A'),
            "country": public_info.get('country', 'N/A'),
            "isp": public_info.get('org', 'N/A'),
            "interfaces": local_info.get('interfaces', []),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }


class ProxyMaster:
    """Main ProxyMaster class"""

    def __init__(self):
        # Initialize components
        self.platform_utils = PlatformUtils()
        self.tor_manager = TorManager()
        self.network_info = NetworkInfo()
        self.validator = ProxyValidator()

        # Data storage
        self.proxy_data: List[Dict] = []
        self.active_proxies: List[Dict] = []
        self.current_proxy: Optional[Dict] = None
        self.user_ip_info: Optional[Dict] = None

        # Configuration
        self.max_threads = MAX_THREADS
        self.results_dir = RESULTS_DIR
        self.current_file: Optional[str] = None

        # Ensure results directory exists
        os.makedirs(self.results_dir, exist_ok=True)

        # Initialize providers
        self.proxy_providers = [
            {"url": "https://www.sslproxies.org/", "tor": False, "class": SSLProxiesProvider},
            {"url": "https://free-proxy-list.net/", "tor": False, "class": SSLProxiesProvider},
            {"url": "https://hidemy.name/en/proxy-list/", "tor": True, "class": SSLProxiesProvider},
            {"url": "https://www.proxy-list.download/HTTP", "tor": False, "class": SSLProxiesProvider},
            {"url": "https://geonode.com/free-proxy-list/", "tor": False, "class": SSLProxiesProvider},
            {"url": "https://www.proxynova.com/proxy-server-list/", "tor": False, "class": SSLProxiesProvider},
            {"url": "https://spys.one/en/", "tor": True, "class": SSLProxiesProvider},
            {"url": "https://proxy-daily.com/", "tor": False, "class": SSLProxiesProvider},
            {"url": "https://www.proxyscan.io/", "tor": False, "class": SSLProxiesProvider},
            {"url": "https://advanced.name/freeproxy", "tor": True, "class": SSLProxiesProvider},
        ]

        # Collect initial network info
        self.user_ip_info = self.network_info.collect_all()

    def fetch_proxies(self) -> bool:
        """Fetch proxies from all providers"""
        print(f"\n{Back.CYAN}{Fore.WHITE}{'═' * 40}")
        print(f"{'Fetching Proxies':^40}")
        print(f"{'═' * 40}{Style.RESET_ALL}")

        # Check Tor status
        tor_running = self.tor_manager.check_status()
        if not tor_running:
            print(f"{Fore.YELLOW}⚠️ Tor service is not running. Some sites may be unavailable.{Style.RESET_ALL}")

        total_proxies = 0

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            for provider in self.proxy_providers:
                provider_class = provider['class']
                provider_instance = provider_class(provider['url'], provider['tor'])
                futures.append(executor.submit(provider_instance.fetch_proxies))

            for future in concurrent.futures.as_completed(futures):
                proxies = future.result()
                with self.validator.lock:
                    self.proxy_data.extend(proxies)
                    total_proxies += len(proxies)
                    print(f"{Fore.GREEN}✅ {len(proxies)} proxies added{Style.RESET_ALL}")

        print(f"\n{Back.BLUE}{Fore.WHITE}📊 Total proxies collected: {total_proxies}{Style.RESET_ALL}")
        return total_proxies > 0

    def test_proxies(self) -> None:
        """Test all collected proxies"""
        if not self.proxy_data:
            print(f"{Back.RED}{Fore.WHITE}⚠️ No proxies to test{Style.RESET_ALL}")
            return

        print(f"\n{Back.CYAN}{Fore.WHITE}{'═' * 40}")
        print(f"{'Testing Proxies':^40}")
        print(f"{'═' * 40}{Style.RESET_ALL}")

        self.active_proxies = []  # Reset active proxies

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            futures = {executor.submit(self.validator.test_proxy, proxy): proxy for proxy in self.proxy_data}

            for future in concurrent.futures.as_completed(futures):
                proxy = futures[future]
                try:
                    result = future.result()
                    if result['success']:
                        with self.validator.lock:
                            self.active_proxies.append(result)

                    status = "✅" if result['success'] else "⚠️" if result['success_rate'] > 0 else "❌"
                    color = Fore.GREEN if result['success'] else Fore.YELLOW if result['success_rate'] > 0 else Fore.RED
                    print(
                        f"{status} {color}{proxy['ip']}:{proxy['port']} - {result['status']} ({result['success_rate']}%){Style.RESET_ALL}")
                except Exception as e:
                    print(f"{Fore.RED}❌ Error testing {proxy['ip']}:{proxy['port']} - {str(e)}{Style.RESET_ALL}")

        self.save_results()
        self.select_best_proxy()

    def select_best_proxy(self) -> None:
        """Select the best available proxy"""
        if not self.active_proxies:
            print(f"{Back.RED}{Fore.WHITE}⚠️ No active proxies found{Style.RESET_ALL}")
            return

        # Sort by success rate (descending) and response time (ascending)
        self.active_proxies.sort(key=lambda x: (-x['success_rate'], x['response_time']))
        self.current_proxy = self.active_proxies[0]

        print(f"\n{Back.GREEN}{Fore.WHITE}🌟 Best proxy selected:{Style.RESET_ALL}")
        print(f"{Fore.CYAN}🔗 {self.current_proxy['ip']}:{self.current_proxy['port']}")
        print(f"{Fore.CYAN}⏱️ Response time: {self.current_proxy['response_time']}s")
        print(f"{Fore.CYAN}🏆 Success rate: {self.current_proxy['success_rate']}%{Style.RESET_ALL}")

    def save_results(self) -> None:
        """Save results to JSON file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"proxy_test_{timestamp}.json"
        self.current_file = os.path.join(self.results_dir, filename)

        data = {
            "metadata": {
                "version": VERSION,
                "platform": self.platform_utils.detect_platform(),
                "timestamp": timestamp
            },
            "user_info": self.user_ip_info,
            "proxies": self.proxy_data,
            "active_proxies": self.active_proxies,
            "current_proxy": self.current_proxy
        }

        with open(self.current_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

        print(f"{Fore.GREEN}✅ Results saved to {self.current_file}{Style.RESET_ALL}")

    def display_network_info(self) -> None:
        """Display network information"""
        if not self.user_ip_info:
            print(f"{Back.RED}{Fore.WHITE}⚠️ No network information available{Style.RESET_ALL}")
            return

        print(f"\n{Back.BLUE}{Fore.WHITE}{'═' * 40}")
        print(f"{'Network Information':^40}")
        print(f"{'═' * 40}{Style.RESET_ALL}")

        print(f"{Fore.CYAN}🌍 Public IP: {Fore.YELLOW}{self.user_ip_info['public_ip']}")
        print(f"{Fore.CYAN}🏠 Hostname: {Fore.YELLOW}{self.user_ip_info['hostname']}")
        print(f"{Fore.CYAN}🏳️ Country: {Fore.YELLOW}{self.user_ip_info['country']}")
        print(f"{Fore.CYAN}📡 ISP: {Fore.YELLOW}{self.user_ip_info['isp']}")

        print(f"\n{Fore.MAGENTA}🔌 Network Interfaces:{Style.RESET_ALL}")
        for interface in self.user_ip_info['interfaces']:
            print(
                f"  {Fore.GREEN}↳ {interface['interface']}: {Fore.WHITE}{interface['ip']} {Fore.LIGHTBLACK_EX}({interface['netmask']})")

        if self.current_proxy:
            print(f"\n{Back.GREEN}{Fore.WHITE}🛡️ Active Proxy:{Style.RESET_ALL}")
            print(f"{Fore.CYAN}🔗 {self.current_proxy['ip']}:{self.current_proxy['port']}")
            print(f"{Fore.CYAN}⏱️ Response time: {self.current_proxy['response_time']}s")
            print(f"{Fore.CYAN}🏆 Success rate: {self.current_proxy['success_rate']}%")
        else:
            print(f"\n{Back.RED}{Fore.WHITE}⚠️ No active proxy{Style.RESET_ALL}")

    def export_results(self, format_type: str = 'txt') -> None:
        """Export results to different formats"""
        if not self.proxy_data:
            print(f"{Back.RED}{Fore.WHITE}⚠️ No data to export{Style.RESET_ALL}")
            return

        base_name = os.path.splitext(self.current_file)[0]

        if format_type == 'txt':
            filename = f"{base_name}.txt"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"# Active Proxy List - Generated on {datetime.now()}\n\n")
                for proxy in sorted(self.active_proxies, key=lambda x: x['response_time']):
                    f.write(f"{proxy['ip']}:{proxy['port']}\n")
            print(f"{Back.GREEN}{Fore.WHITE}✅ Active proxies saved to {filename}{Style.RESET_ALL}")

        elif format_type == 'csv':
            filename = f"{base_name}.csv"
            with open(filename, 'w', encoding='utf-8', newline='') as f:
                f.write("IP,Port,Country,Anonymity,HTTPS,Success Rate,Response Time,Status,Error\n")
                for proxy in self.proxy_data:
                    f.write(
                        f"{proxy['ip']},{proxy['port']},{proxy['country']},"
                        f"{proxy['anonymity']},{proxy['https']},{proxy['success_rate']},"
                        f"{proxy['response_time']},{proxy['status']},\"{proxy['error']}\"\n"
                    )
            print(f"{Back.GREEN}{Fore.WHITE}✅ Full results saved to {filename}{Style.RESET_ALL}")
        else:
            print(f"{Back.RED}{Fore.WHITE}⚠️ Invalid format! Please use 'txt' or 'csv'{Style.RESET_ALL}")


def display_menu() -> None:
    """Display the main menu"""
    print(f"\n{Back.BLUE}{Fore.WHITE}{'═' * 40}")
    print(f"{'ProxyMaster v2.0.0':^40}")
    print(f"{'═' * 40}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}1. {Fore.YELLOW}Display network info")
    print(f"{Fore.CYAN}2. {Fore.YELLOW}Fetch proxies")
    print(f"{Fore.CYAN}3. {Fore.YELLOW}Test all proxies")
    print(f"{Fore.CYAN}4. {Fore.YELLOW}Show detailed results")
    print(f"{Fore.CYAN}5. {Fore.YELLOW}Export results (TXT/CSV)")
    print(f"{Fore.CYAN}6. {Fore.YELLOW}Rotate proxy")
    print(f"{Fore.CYAN}7. {Fore.YELLOW}Exit")
    print(f"{Back.BLUE}{Fore.WHITE}{'═' * 40}{Style.RESET_ALL}")


def main() -> None:
    """Main program loop"""
    master = ProxyMaster()

    while True:
        display_menu()
        choice = input(f"\n{Fore.YELLOW}⎋ Select an option (1-7): {Style.RESET_ALL}").strip()

        if choice == "1":
            master.display_network_info()
        elif choice == "2":
            master.fetch_proxies()
        elif choice == "3":
            master.test_proxies()
        elif choice == "4":
            # Implement detailed results display
            pass
        elif choice == "5":
            format_type = input(f"{Fore.YELLOW}⎋ Enter format (txt/csv): {Style.RESET_ALL}").strip().lower()
            if format_type in ['txt', 'csv']:
                master.export_results(format_type)
            else:
                print(f"{Back.RED}{Fore.WHITE}⚠️ Invalid format! Please enter 'txt' or 'csv'{Style.RESET_ALL}")
        elif choice == "6":
            # Implement proxy rotation
            pass
        elif choice == "7":
            print(f"\n{Back.GREEN}{Fore.WHITE}🏁 Exiting. Goodbye!{Style.RESET_ALL}")
            break
        else:
            print(f"{Back.RED}{Fore.WHITE}⚠️ Invalid choice! Please enter a number between 1-7{Style.RESET_ALL}")


if __name__ == "__main__":
    main()