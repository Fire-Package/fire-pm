#!/usr/bin/env bash
set -e

# ==============================================================================
# Fire PM — Automated Installer & System Prerequisite Checker
# Supports both:
#   1) Standalone execution: sudo ./install.sh
#   2) One-liner curl pipe:  curl -fsSL <url> | sudo bash
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
   echo -e "${RED}✖ This installer must be run as root (use: sudo ./install.sh or curl ... | sudo bash)${NC}"
   exit 1
fi

SCRIPT_DIR=""
if [[ -n "${BASH_SOURCE[0]}" && -f "${BASH_SOURCE[0]}" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

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

# 3. Check core CLI utilities (procps for ps, iproute2 for ss, git, curl)
if ! command -v ps &>/dev/null; then
  echo -e "  ${YELLOW}Installing procps (ps)...${NC}"
  install_package "procps"
fi

if ! command -v ss &>/dev/null; then
  echo -e "  ${YELLOW}Installing iproute2 (ss)...${NC}"
  install_package "iproute2"
fi

if ! command -v curl &>/dev/null; then
  install_package "curl"
fi

if ! command -v git &>/dev/null; then
  install_package "git"
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

# 5. Check Node.js >= 22 (required by pnpm and Next.js)
NEED_NODE=false
if ! command -v node &>/dev/null; then
  NEED_NODE=true
else
  NODE_MAJOR=$(node -v 2>/dev/null | sed 's/^v//' | cut -d. -f1)
  if [[ -z "$NODE_MAJOR" || "$NODE_MAJOR" -lt 22 ]]; then
    echo -e "  ${YELLOW}⚠ Node.js v${NODE_MAJOR:-unknown} detected, but v22+ is required.${NC}"
    NEED_NODE=true
  fi
fi

if [[ "$NEED_NODE" == "true" ]]; then
  echo -e "  ${CYAN}Installing Node.js v22 LTS...${NC}"
  if command -v apt-get &>/dev/null; then
    # NodeSource setup for Debian/Ubuntu
    if ! command -v curl &>/dev/null; then install_package "curl"; fi
    install_package "ca-certificates"
    install_package "gnupg"
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg 2>/dev/null || true
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" > /etc/apt/sources.list.d/nodesource.list
    apt-get update &>/dev/null
    DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs &>/dev/null
  elif command -v dnf &>/dev/null; then
    dnf module enable -y nodejs:22 &>/dev/null || true
    dnf install -y nodejs &>/dev/null || true
  elif command -v yum &>/dev/null; then
    curl -fsSL https://rpm.nodesource.com/setup_22.x | bash - &>/dev/null
    yum install -y nodejs &>/dev/null || true
  elif command -v pacman &>/dev/null; then
    pacman -Sy --noconfirm nodejs npm &>/dev/null || true
  elif command -v apk &>/dev/null; then
    apk add nodejs npm &>/dev/null || true
  fi

  if command -v node &>/dev/null; then
    echo -e "  ${GREEN}✔${NC} Node.js $(node -v) installed"
  else
    echo -e "  ${RED}✖ Failed to install Node.js v22. Please install it manually:${NC}"
    echo -e "    https://nodejs.org/en/download"
  fi
fi

# 6. Check pnpm
if command -v node &>/dev/null && ! command -v pnpm &>/dev/null; then
  echo -e "  ${CYAN}Installing pnpm package manager...${NC}"
  if command -v corepack &>/dev/null; then
    corepack enable &>/dev/null || true
    corepack prepare pnpm@latest --activate &>/dev/null || npm install -g pnpm &>/dev/null || true
  else
    npm install -g pnpm &>/dev/null || true
  fi
fi

echo -e "  ${GREEN}✔${NC} System dependencies verified"
echo ""

# Determine source directory (local clone or pull into /opt/fire-pm)
INSTALL_SOURCE_DIR=""
if [[ -n "$SCRIPT_DIR" && -f "${SCRIPT_DIR}/app/fire" ]]; then
  INSTALL_SOURCE_DIR="${SCRIPT_DIR}"
else
  TARGET_OPT_DIR="/opt/fire-pm"
  echo -e "${CYAN}Setting up Fire PM repository in ${TARGET_OPT_DIR}...${NC}"
  mkdir -p /opt
  if [[ -d "${TARGET_OPT_DIR}/.git" ]]; then
    git -C "${TARGET_OPT_DIR}" pull --rebase || true
  else
    git clone https://github.com/Fire-Package/fire-pm.git "${TARGET_OPT_DIR}"
  fi
  INSTALL_SOURCE_DIR="${TARGET_OPT_DIR}"
fi

# 7. Install CLI binary
echo -e "${CYAN}1/4 Installing Fire CLI engine...${NC}"
cp "${INSTALL_SOURCE_DIR}/app/fire" /usr/local/bin/fire
chmod +x /usr/local/bin/fire
if [[ -f "${INSTALL_SOURCE_DIR}/app/ff-service" ]]; then
  cp "${INSTALL_SOURCE_DIR}/app/ff-service" /usr/local/bin/ff-service
  chmod +x /usr/local/bin/ff-service
fi
echo -e "    ${GREEN}✔${NC} Fire CLI installed to /usr/local/bin/fire"

# 8. Install TUI
echo -e "${CYAN}2/4 Installing Terminal UI (TUI)...${NC}"
cp "${INSTALL_SOURCE_DIR}/tui/fire_tui.py" /usr/local/bin/fire_tui.py
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
if [[ -f "${INSTALL_SOURCE_DIR}/shared/units/fire-reload@.service" ]]; then
  cp "${INSTALL_SOURCE_DIR}/shared/units/fire-reload@.service" /etc/systemd/system/
fi
systemctl daemon-reload
echo -e "    ${GREEN}✔${NC} Systemd unit templates registered"

# 10. Build Web UI
echo -e "${CYAN}4/4 Building Web UI Dashboard & API...${NC}"
if [[ -d "${INSTALL_SOURCE_DIR}/web" ]]; then
  cd "${INSTALL_SOURCE_DIR}/web"
  
  if command -v pnpm &>/dev/null; then
    pnpm install --prod=false
    pnpm build
  elif command -v npm &>/dev/null; then
    npm install
    npm run build
  else
    echo -e "    ${YELLOW}⚠ Node.js not found. Install Node.js (v18+) to run the Web UI.${NC}"
  fi
  chmod +x "${INSTALL_SOURCE_DIR}/web/start.sh"
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
echo -e "    ${CYAN}fire start ${INSTALL_SOURCE_DIR}/web/start.sh --name fire-web --env PORT=3000${NC}"
echo ""
