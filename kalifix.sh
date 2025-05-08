#!/bin/bash

# ==============================================
# Kali Repository Fixer v2.0
# Created by: bitpy2023
# GitHub: https://github.com/bitpy2023/Scripts
# ==============================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check root
if [ "$(id -u)" -ne 0 ]; then
  echo -e "${RED}[!] Error: This script must be run as root!${NC}"
  echo -e "${YELLOW}Try: sudo ./kalifix.sh${NC}"
  exit 1
fi

# Banner
echo -e "${BLUE}"
cat << "EOF"
  _  __ _   _ _  __       _  ___  _ __ 
 | |/ /| | | | |/ /      | |/ _ \| '__|
 |   < | |_| |   <       | | (_) | |   
 |_|\_\\ \__,_|_|\_\      |_|\___/|_|   
EOF
echo -e "${NC}"
echo -e "${GREEN}Kali Linux Repository Auto-Fixer v2.0${NC}"
echo -e "Contributed by: bitpy2023"
echo -e "GitHub: https://github.com/bitpy2023/Scripts"
echo "----------------------------------------"

# Main menu
show_menu() {
  echo -e "\n${YELLOW}[?] Select an option:${NC}"
  echo -e "1) Normal Fix (Recommended for most users)"
  echo -e "2) Aggressive Fix (For restricted countries)"
  echo -e "3) Custom DNS Setup"
  echo -e "4) Test Connection"
  echo -e "5) Exit"
  read -p "Your choice [1-5]: " choice
  case $choice in
    1) normal_fix ;;
    2) aggressive_fix ;;
    3) custom_dns ;;
    4) test_connection ;;
    5) exit 0 ;;
    *) echo -e "${RED}[!] Invalid option!${NC}"; show_menu ;;
  esac
}

# Normal fix
normal_fix() {
  echo -e "\n${YELLOW}[*] Applying normal fix...${NC}"
  backup_configs
  setup_dns "1.1.1.1 8.8.8.8 9.9.9.9"
  setup_repositories "normal"
  install_requirements
  optimize_network
  cleanup
  echo -e "\n${GREEN}[✓] Normal fix applied successfully!${NC}"
}

# Aggressive fix
aggressive_fix() {
  echo -e "\n${YELLOW}[*] Applying aggressive fix...${NC}"
  backup_configs
  setup_dns "1.1.1.1 8.8.8.8 9.9.9.9 208.67.222.222"
  setup_repositories "aggressive"
  install_requirements
  optimize_network
  setup_proxy_check
  cleanup
  echo -e "\n${GREEN}[✓] Aggressive fix applied successfully!${NC}"
}

# Custom DNS
custom_dns() {
  echo -e "\n${YELLOW}[?] Enter custom DNS servers (space separated):${NC}"
  read -p "DNS Servers: " custom_dns
  setup_dns "$custom_dns"
  echo -e "\n${GREEN}[✓] Custom DNS configured!${NC}"
}

# Backup configs
backup_configs() {
  echo -e "${YELLOW}[*] Backing up current configurations...${NC}"
  cp /etc/apt/sources.list /etc/apt/sources.list.bak 2>/dev/null
  cp /etc/resolv.conf /etc/resolv.conf.bak 2>/dev/null
}

# Setup DNS
setup_dns() {
  echo -e "${YELLOW}[*] Configuring DNS servers...${NC}"
  > /etc/resolv.conf
  for dns in $1; do
    echo "nameserver $dns" >> /etc/resolv.conf
  done
  chattr +i /etc/resolv.conf 2>/dev/null
}

# Setup repositories
setup_repositories() {
  echo -e "${YELLOW}[*] Configuring repositories...${NC}"
  > /etc/apt/sources.list
  
  if [ "$1" == "normal" ]; then
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

# Install requirements
install_requirements() {
  echo -e "${YELLOW}[*] Installing required packages...${NC}"
  apt-get update --allow-insecure-repositories -qq
  apt-get install -y kali-archive-keyring debian-archive-keyring
}

# Optimize network
optimize_network() {
  echo -e "${YELLOW}[*] Optimizing network settings...${NC}"
  grep -q "net.core.default_qdisc=fq" /etc/sysctl.conf || \
    echo "net.core.default_qdisc=fq" >> /etc/sysctl.conf
  grep -q "net.ipv4.tcp_congestion_control=bbr" /etc/sysctl.conf || \
    echo "net.ipv4.tcp_congestion_control=bbr" >> /etc/sysctl.conf
  sysctl -p >/dev/null 2>&1
}

# Setup proxy check
setup_proxy_check() {
  echo -e "${YELLOW}[*] Checking for proxy settings...${NC}"
  if [ -n "$http_proxy" ]; then
    echo -e "${BLUE}[i] Proxy detected: $http_proxy${NC}"
    echo "Acquire::http::Proxy \"$http_proxy\";" > /etc/apt/apt.conf.d/99proxy
  fi
}

# Test connection
test_connection() {
  echo -e "\n${YELLOW}[*] Testing connection to Kali repositories...${NC}"
  echo -e "${BLUE}[i] Testing DNS resolution...${NC}"
  nslookup http.kali.org
  
  echo -e "\n${BLUE}[i] Testing HTTP connection...${NC}"
  curl -I http://http.kali.org --connect-timeout 5
  
  echo -e "\n${BLUE}[i] Testing repository access...${NC}"
  apt-get update --dry-run
}

# Cleanup
cleanup() {
  echo -e "${YELLOW}[*] Cleaning up...${NC}"
  apt-get clean
  apt-get update -qq
  echo -e "\n${GREEN}[✓] Running final upgrade...${NC}"
  apt-get upgrade -y
}

# Main execution
show_menu
