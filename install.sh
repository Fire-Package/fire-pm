#!/usr/bin/env bash
set -e

# ==============================================================================
# Fire PM — Automated Installer & System Prerequisite Checker
# ==============================================================================

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${CYAN}${BOLD}"
echo "    ▄████████  ▄█  ███▄▄▄▄      ▄████████ "
echo "   ███    ███ ███  ███▀▀▀██▄   ███    ███ "
echo "   ███    █▀  ███▌ ███   ███   ███    █▀  "
echo "  ▄███▄▄▄     ███▌ ███   ███  ▄███▄▄▄     "
echo " ▀▀███▀▀▀     ███▌ ███   ███ ▀▀███▀▀▀     "
echo "   ███        ███  ███   ███   ███    █▄  "
echo "   ███        ███  ███   ███   ███    ███ "
echo "   ███        █▀    ▀█   █▀    ████████▀  "
echo -e "${NC}"
echo -e "${BOLD}Fire PM — Linux Process & Application Management Platform${NC}"
echo -e "${CYAN}================================================================${NC}"
echo ""

# 1. Root Check
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}✖ This installer must be run as root (use: sudo ./install.sh)${NC}"
   exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Package manager helper
install_package() {
  local pkg="$1"
  if command -v apt-get &>/dev/null; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y "$pkg" &>/dev/null || true
  elif command -v dnf &>/dev/null; then
    dnf install -y "$pkg" &>/dev/null || true
  elif command -v yum &>/dev/null; then
    yum install -y "$pkg" &>/dev/null || true
  elif command -v pacman &>/dev/null; then
    pacman -Sy --noconfirm "$pkg" &>/dev/null || true
  elif command -v zypper &>/dev/null; then
    zypper install -y "$pkg" &>/dev/null || true
  elif command -v apk &>/dev/null; then
    apk add "$pkg" &>/dev/null || true
  fi
}

echo -e "${CYAN}Checking and installing system prerequisites...${NC}"

# 2. Check systemd / systemctl
if ! command -v systemctl &>/dev/null; then
  echo -e "  ${YELLOW}⚠ systemd not found. Attempting to install systemd...${NC}"
  install_package "systemd"
  install_package "systemd-sysv"
  
  if ! command -v systemctl &>/dev/null; then
    echo -e "  ${RED}✖ Could not find or install systemd.${NC}"
    echo -e "    Fire PM requires a Linux system with systemd init."
    echo -e "    If you are running in a Docker container, ensure systemd init is enabled."
    exit 1
  fi
fi
echo -e "  ${GREEN}✔${NC} systemd / systemctl is active"

# 3. Check core CLI utilities (procps for ps, iproute2 for ss)
if ! command -v ps &>/dev/null; then
  echo -e "  ${YELLOW}Installing procps (ps)...${NC}"
  install_package "procps"
fi

if ! command -v ss &>/dev/null; then
  echo -e "  ${YELLOW}Installing iproute2 (ss)...${NC}"
  install_package "iproute2"
fi

# 4. Check Python 3 and pip
if ! command -v python3 &>/dev/null; then
  echo -e "  ${YELLOW}Installing python3...${NC}"
  install_package "python3"
fi

if ! command -v pip3 &>/dev/null && ! command -v pip &>/dev/null; then
  echo -e "  ${YELLOW}Installing python3-pip...${NC}"
  install_package "python3-pip"
fi

# 5. Check Node.js (for Web UI)
if ! command -v node &>/dev/null; then
  echo -e "  ${YELLOW}Node.js not detected.${NC}"
  if command -v apt-get &>/dev/null; then
    echo -e "  ${CYAN}Attempting to install Node.js via apt...${NC}"
    install_package "nodejs"
    install_package "npm"
  fi
fi

# 6. Check pnpm
if command -v npm &>/dev/null && ! command -v pnpm &>/dev/null; then
  echo -e "  ${CYAN}Installing pnpm package manager...${NC}"
  npm install -g pnpm &>/dev/null || true
fi

echo -e "  ${GREEN}✔${NC} System dependencies verified"
echo ""

# 7. Install CLI binary
echo -e "${CYAN}1/4 Installing Fire CLI engine...${NC}"
cp "${SCRIPT_DIR}/app/fire" /usr/local/bin/fire
chmod +x /usr/local/bin/fire
if [[ -f "${SCRIPT_DIR}/app/ff-service" ]]; then
  cp "${SCRIPT_DIR}/app/ff-service" /usr/local/bin/ff-service
  chmod +x /usr/local/bin/ff-service
fi
echo -e "    ${GREEN}✔${NC} Fire CLI installed to /usr/local/bin/fire"

# 8. Install TUI
echo -e "${CYAN}2/4 Installing Terminal UI (TUI)...${NC}"
cp "${SCRIPT_DIR}/tui/fire_tui.py" /usr/local/bin/fire_tui.py
chmod +x /usr/local/bin/fire_tui.py

# Install python textual library
if command -v pip3 &>/dev/null; then
  pip3 install textual &>/dev/null || pip3 install --break-system-packages textual &>/dev/null || true
elif command -v pip &>/dev/null; then
  pip install textual &>/dev/null || true
elif [[ -x "/root/myenv/bin/pip" ]]; then
  /root/myenv/bin/pip install textual &>/dev/null || true
fi
echo -e "    ${GREEN}✔${NC} Fire TUI installed to /usr/local/bin/fire_tui.py"

# 9. Install Systemd templates
echo -e "${CYAN}3/4 Registering Systemd templates...${NC}"
mkdir -p /etc/systemd/system /etc/fire-pm
if [[ -f "${SCRIPT_DIR}/shared/units/fire-reload@.service" ]]; then
  cp "${SCRIPT_DIR}/shared/units/fire-reload@.service" /etc/systemd/system/
fi
systemctl daemon-reload
echo -e "    ${GREEN}✔${NC} Systemd unit templates registered"

# 10. Build Web UI
echo -e "${CYAN}4/4 Building Web UI Dashboard & API...${NC}"
if [[ -d "${SCRIPT_DIR}/web" ]]; then
  cd "${SCRIPT_DIR}/web"
  
  if command -v pnpm &>/dev/null; then
    pnpm install --prod=false
    pnpm build
  elif command -v npm &>/dev/null; then
    npm install
    npm run build
  else
    echo -e "    ${YELLOW}⚠ Node.js not found. Install Node.js (v18+) to run the Web UI.${NC}"
  fi
  chmod +x "${SCRIPT_DIR}/web/start.sh"
  echo -e "    ${GREEN}✔${NC} Web UI built successfully"
fi

echo ""
echo -e "${GREEN}${BOLD}✔ Fire PM installation completed successfully!${NC}"
echo -e "${CYAN}================================================================${NC}"
echo -e "  ${BOLD}Commands:${NC}"
echo -e "    ${YELLOW}fire${NC}                — Launch interactive dashboard"
echo -e "    ${YELLOW}fire start <file>${NC}   — Start a Python/Node.js/Bash service"
echo -e "    ${YELLOW}fire list${NC}           — List all managed processes"
echo -e "    ${YELLOW}fire tunnel open <p>${NC} — Expose local port via reverse proxy"
echo -e "    ${YELLOW}fire doctor${NC}         — Run system diagnostics"
echo ""
echo -e "  ${BOLD}Start Web UI Dashboard:${NC}"
echo -e "    ${CYAN}fire start ${SCRIPT_DIR}/web/start.sh --name fire-web --env PORT=3000${NC}"
echo ""
