#!/bin/bash

# ==============================================
# Kali Repository Fixer v2.1 (Enhanced)
# Created by: bitpy2023
# GitHub: https://github.com/bitpy2023/Scripts
# Last Updated: 2025-05-08
# ==============================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Initialize
ARCH=""
PROXY=""
trap 'cleanup_on_exit' EXIT INT TERM

# Functions
cleanup_on_exit() {
  chattr -i /etc/resolv.conf 2>/dev/null
  echo -e "\n${BLUE}[i] Cleanup completed. Safe to exit.${NC}"
}

log() {
  echo -e "${YELLOW}[*] $1${NC}"
}

show_help() {
  cat <<EOF
Usage: ./kalifix.sh [OPTION]
Options:
  -n, --normal      Apply normal fix (recommended)
  -a, --aggressive  Apply aggressive fix (for restricted regions)
  -t, --test        Test connection only
  -h, --help        Show this help message
EOF
}

check_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}[!] Error: This script must be run as root!${NC}"
    echo -e "${YELLOW}Try: sudo ./kalifix.sh${NC}"
    exit 1
  fi
}

check_architecture() {
  case $(uname -m) in
    x86_64) ARCH="amd64" ;;
    aarch64) ARCH="arm64" ;;
    *) echo -e "${RED}[!] Unsupported architecture${NC}"; exit 1 ;;
  esac
  log "Detected architecture: $ARCH"
}

backup_configs() {
  [ ! -f /etc/apt/sources.list ] && { echo -e "${RED}[!] sources.list not found!${NC}"; exit 1; }
  
  log "Backing up current configurations..."
  cp /etc/apt/sources.list /etc/apt/sources.list.bak 2>/dev/null || {
    echo -e "${RED}[!] Failed to backup sources.list${NC}"; exit 1
  }
  cp /etc/resolv.conf /etc/resolv.conf.bak 2>/dev/null
}

setup_dns() {
  local dns_servers=($1)
  local conf_file="/etc/resolv.conf"
  
  [ ${#dns_servers[@]} -eq 0 ] && { echo -e "${RED}[!] No DNS servers provided${NC}"; return 1; }
  
  log "Configuring DNS servers..."
  printf "nameserver %s\n" "${dns_servers[@]}" > "$conf_file" || {
    echo -e "${RED}[!] Failed to write DNS config${NC}"; return 1
  }
  chattr +i "$conf_file" 2>/dev/null
}

setup_repositories() {
  local mode=$1
  log "Configuring $mode repositories..."
  
  > /etc/apt/sources.list || {
    echo -e "${RED}[!] Failed to clear sources.list${NC}"; return 1
  }

  if [ "$mode" == "normal" ]; then
    cat >> /etc/apt/sources.list <<EOL
deb http://http.kali.org/kali kali-rolling main contrib non-free
deb http://ftp.acc.umu.se/mirror/kali.org/kali kali-rolling main contrib non-free
EOL
  else
    cat >> /etc/apt/sources.list <<EOL
deb http://ftp.yzu.edu.tw/Linux/kali kali-rolling main contrib non-free
deb http://ftp.halifax.rwth-aachen.de/kali kali-rolling main contrib non-free
deb http://kali.mirror.garr.it/kali kali-rolling main contrib non-free
EOL
  fi
}

install_requirements() {
  log "Installing required packages..."
  apt-get update --allow-insecure-repositories -qq || {
    echo -e "${RED}[!] Failed to update packages${NC}"; return 1
  }
  apt-get install -y kali-archive-keyring debian-archive-keyring || {
    echo -e "${RED}[!] Failed to install keyrings${NC}"; return 1
  }
}

optimize_network() {
  log "Optimizing network settings..."
  grep -q "net.core.default_qdisc=fq" /etc/sysctl.conf || \
    echo "net.core.default_qdisc=fq" >> /etc/sysctl.conf
  grep -q "net.ipv4.tcp_congestion_control=bbr" /etc/sysctl.conf || \
    echo "net.ipv4.tcp_congestion_control=bbr" >> /etc/sysctl.conf
  sysctl -p >/dev/null 2>&1
}

test_connection() {
  local test_urls=(
    "http://http.kali.org"
    "http://ftp.acc.umu.se"
    "http://kali.download"
  )
  
  log "Testing connection to Kali repositories..."
  for url in "${test_urls[@]}"; do
    if curl -s --head "$url" | grep "200 OK"; then
      echo -e "${GREEN}[✓] $url accessible${NC}"
    else
      echo -e "${RED}[!] $url unreachable${NC}"
    fi
  done
  
  log "Testing DNS resolution..."
  nslookup http.kali.org || echo -e "${RED}[!] DNS resolution failed${NC}"
}

normal_fix() {
  log "Applying normal fix..."
  backup_configs
  setup_dns "1.1.1.1 8.8.8.8 9.9.9.9"
  setup_repositories "normal"
  install_requirements
  optimize_network
  echo -e "\n${GREEN}[✓] Normal fix applied successfully!${NC}"
}

aggressive_fix() {
  log "Applying aggressive fix..."
  backup_configs
  setup_dns "1.1.1.1 8.8.8.8 9.9.9.9 208.67.222.222"
  setup_repositories "aggressive"
  install_requirements
  optimize_network
  echo -e "\n${GREEN}[✓] Aggressive fix applied successfully!${NC}"
}

show_banner() {
  echo -e "${BLUE}"
  cat << "EOF"
  _  __ _   _ _  __       _  ___  _ __ 
 | |/ /| | | | |/ /      | |/ _ \| '__|
 |   < | |_| |   <       | | (_) | |   
 |_|\_\\ \__,_|_|\_\      |_|\___/|_|   
EOF
  echo -e "${NC}"
  echo -e "${GREEN}Kali Linux Repository Auto-Fixer v2.1${NC}"
  echo -e "Contributed by: bitpy2023"
  echo -e "Last Updated: 2025-05-08"
  echo "----------------------------------------"
}

# Main execution
check_root
check_architecture
show_banner

# Process arguments
while [ $# -gt 0 ]; do
  case $1 in
    -n|--normal) normal_fix; exit ;;
    -a|--aggressive) aggressive_fix; exit ;;
    -t|--test) test_connection; exit ;;
    -h|--help) show_help; exit ;;
    *) show_help; exit 1 ;;
  esac
  shift
done

# Interactive mode
PS3="$(echo -e '\n')${YELLOW}[?] Select an option:${NC} "
options=(
  "Normal Fix (Recommended)"
  "Aggressive Fix (Restricted regions)"
  "Test Connection"
  "Exit"
)

select opt in "${options[@]}"; do
  case $REPLY in
    1) normal_fix; break ;;
    2) aggressive_fix; break ;;
    3) test_connection; break ;;
    4) exit 0 ;;
    *) echo -e "${RED}[!] Invalid option!${NC}" ;;
  esac
done
