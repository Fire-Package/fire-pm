#!/usr/bin/env bash
set -e

# ==============================================================================
# Fire PM — Automated Installer & Setup Script
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
   echo -e "${RED}✖ This installer must be run as root.${NC}"
   exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 2. Install CLI binary
echo -e "${CYAN}1/4 Installing Fire CLI engine...${NC}"
cp "${SCRIPT_DIR}/app/fire" /usr/local/bin/fire
chmod +x /usr/local/bin/fire
if [[ -f "${SCRIPT_DIR}/app/ff-service" ]]; then
  cp "${SCRIPT_DIR}/app/ff-service" /usr/local/bin/ff-service
  chmod +x /usr/local/bin/ff-service
fi
echo -e "    ${GREEN}✔${NC} Fire CLI installed to /usr/local/bin/fire"

# 3. Install TUI
echo -e "${CYAN}2/4 Installing Terminal UI (TUI)...${NC}"
cp "${SCRIPT_DIR}/tui/fire_tui.py" /usr/local/bin/fire_tui.py
chmod +x /usr/local/bin/fire_tui.py

# Check Python environment for textual
if command -v pip3 &>/dev/null; then
  pip3 install textual &>/dev/null || true
elif [[ -x "/root/myenv/bin/pip" ]]; then
  /root/myenv/bin/pip install textual &>/dev/null || true
fi
echo -e "    ${GREEN}✔${NC} Fire TUI installed to /usr/local/bin/fire_tui.py"

# 4. Install Systemd templates
echo -e "${CYAN}3/4 Registering Systemd templates...${NC}"
mkdir -p /etc/systemd/system /etc/fire-pm
if [[ -f "${SCRIPT_DIR}/shared/units/fire-reload@.service" ]]; then
  cp "${SCRIPT_DIR}/shared/units/fire-reload@.service" /etc/systemd/system/
fi
systemctl daemon-reload
echo -e "    ${GREEN}✔${NC} Systemd unit templates registered"

# 5. Build Web UI
echo -e "${CYAN}4/4 Building Web UI Dashboard & API...${NC}"
if [[ -d "${SCRIPT_DIR}/web" ]]; then
  cd "${SCRIPT_DIR}/web"
  if command -v pnpm &>/dev/null; then
    pnpm install
    pnpm build
  elif command -v npm &>/dev/null; then
    npm install
    npm run build
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
