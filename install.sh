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

NODE_VERSION="22.16.0"

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

# Parse options and environment variables for Web UI installation
INSTALL_WEB=""
if [[ -n "$FIRE_INSTALL_WEB" ]]; then
  if [[ "$FIRE_INSTALL_WEB" =~ ^([yY][eE][sS]|[tT][rR][uU][eE]|1)$ ]]; then
    INSTALL_WEB=true
  elif [[ "$FIRE_INSTALL_WEB" =~ ^([nN][oO]|[fF][aA][lL][sS][eE]|0)$ ]]; then
    INSTALL_WEB=false
  fi
fi

FORCE_INSTALL=false
for arg in "$@"; do
  case "$arg" in
    --with-web)
      INSTALL_WEB=true
      ;;
    --no-web|--without-web)
      INSTALL_WEB=false
      ;;
    --force|-f)
      FORCE_INSTALL=true
      ;;
    -h|--help)
      echo "Usage: sudo ./install.sh [options]"
      echo ""
      echo "Options:"
      echo "  --with-web        Build and configure the Web UI Dashboard"
      echo "  --no-web          Skip building the Web UI Dashboard (CLI & TUI only)"
      echo "  --force, -f       Force overwrite unstaged local modifications"
      echo "  -h, --help        Show this help message"
      exit 0
      ;;
  esac
done

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

# Prompt user for Web UI installation if not specified via flag or env var
if [[ -z "$INSTALL_WEB" ]]; then
  echo -ne "${CYAN}? Would you like to build and configure the Web UI Dashboard? (takes ~2-3 mins) (y/n): ${NC}"
  user_choice=""
  if [[ -t 0 ]]; then
    read -r user_choice
  elif [[ -r /dev/tty ]] && ( exec 2>/dev/null; read -r user_choice < /dev/tty ) 2>/dev/null; then
    :
  else
    echo "n (headless mode)"
    user_choice="n"
  fi

  case "$user_choice" in
    [yY]|[yY][eE][sS])
      INSTALL_WEB=true
      ;;
    *)
      INSTALL_WEB=false
      ;;
  esac
fi

echo ""
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

# 3. Check core CLI utilities
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

if ! command -v tar &>/dev/null; then
  install_package "tar"
fi

# 4. Check Python 3 and pip / venv
if ! command -v python3 &>/dev/null; then
  echo -e "  ${YELLOW}Installing python3...${NC}"
  install_package "python3"
fi

if ! command -v pip3 &>/dev/null && ! command -v pip &>/dev/null; then
  echo -e "  ${YELLOW}Installing python3-pip & python3-venv...${NC}"
  install_package "python3-pip"
  install_package "python3-venv"
fi

# 5. Check Node.js & pnpm (only if Web UI is requested)
if [[ "$INSTALL_WEB" == "true" ]]; then
  NEED_NODE=false
  if ! command -v node &>/dev/null; then
    NEED_NODE=true
  else
    NODE_MAJOR=$(node -v 2>/dev/null | sed 's/^v//' | cut -d. -f1)
    if [[ -z "$NODE_MAJOR" || "$NODE_MAJOR" -lt 22 ]]; then
      echo -e "  ${YELLOW}⚠ Node.js v${NODE_MAJOR:-unknown} detected, but v22+ is required. Upgrading...${NC}"
      NEED_NODE=true
    fi
  fi

  if [[ "$NEED_NODE" == "true" ]]; then
    echo -e "  ${CYAN}Installing Node.js v${NODE_VERSION} (official binary)...${NC}"

    ARCH=$(uname -m)
    case "$ARCH" in
      x86_64)  NODE_ARCH="x64" ;;
      aarch64) NODE_ARCH="arm64" ;;
      armv7l)  NODE_ARCH="armv7l" ;;
      *)
        echo -e "  ${RED}✖ Unsupported architecture: ${ARCH}${NC}"
        echo -e "    Please install Node.js v22+ manually: https://nodejs.org/en/download"
        ;;
    esac

    if [[ -n "$NODE_ARCH" ]]; then
      NODE_TARBALL="node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz"
      NODE_URL="https://nodejs.org/dist/v${NODE_VERSION}/${NODE_TARBALL}"

      TMP_DIR=$(mktemp -d)
      if curl -fsSL "$NODE_URL" -o "${TMP_DIR}/${NODE_TARBALL}"; then
        tar -xJf "${TMP_DIR}/${NODE_TARBALL}" -C "${TMP_DIR}"
        cp -rf "${TMP_DIR}/node-v${NODE_VERSION}-linux-${NODE_ARCH}"/bin/* /usr/local/bin/
        cp -rf "${TMP_DIR}/node-v${NODE_VERSION}-linux-${NODE_ARCH}"/lib/* /usr/local/lib/ 2>/dev/null || true
        cp -rf "${TMP_DIR}/node-v${NODE_VERSION}-linux-${NODE_ARCH}"/include/* /usr/local/include/ 2>/dev/null || true
        cp -rf "${TMP_DIR}/node-v${NODE_VERSION}-linux-${NODE_ARCH}"/share/* /usr/local/share/ 2>/dev/null || true
        rm -rf "${TMP_DIR}"
        hash -r
        echo -e "  ${GREEN}✔${NC} Node.js $(node -v) installed to /usr/local/bin/node"
      else
        rm -rf "${TMP_DIR}"
        echo -e "  ${RED}✖ Failed to download Node.js v${NODE_VERSION}.${NC}"
        echo -e "    Please install manually: https://nodejs.org/en/download"
      fi
    fi
  fi

  # Check pnpm
  if command -v node &>/dev/null && ! command -v pnpm &>/dev/null; then
    echo -e "  ${CYAN}Installing pnpm package manager...${NC}"
    if command -v corepack &>/dev/null; then
      corepack enable &>/dev/null || true
      corepack prepare pnpm@latest --activate &>/dev/null || npm install -g pnpm &>/dev/null || true
    else
      npm install -g pnpm &>/dev/null || true
    fi
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
    if [[ "$FORCE_INSTALL" == "true" ]]; then
      git -C "${TARGET_OPT_DIR}" fetch --all --prune &>/dev/null || true
      git -C "${TARGET_OPT_DIR}" checkout main 2>/dev/null || git -C "${TARGET_OPT_DIR}" checkout master 2>/dev/null || true
      git -C "${TARGET_OPT_DIR}" reset --hard origin/main 2>/dev/null || git -C "${TARGET_OPT_DIR}" reset --hard origin/master 2>/dev/null || true
      git -C "${TARGET_OPT_DIR}" clean -fd &>/dev/null || true
    else
      if ! git -C "${TARGET_OPT_DIR}" pull --ff-only &>/dev/null; then
        # Reset local unstaged/untracked modifications to allow clean upgrade
        git -C "${TARGET_OPT_DIR}" fetch --all --prune &>/dev/null || true
        git -C "${TARGET_OPT_DIR}" checkout main 2>/dev/null || git -C "${TARGET_OPT_DIR}" checkout master 2>/dev/null || true
        git -C "${TARGET_OPT_DIR}" reset --hard origin/main 2>/dev/null || git -C "${TARGET_OPT_DIR}" reset --hard origin/master 2>/dev/null || true
        git -C "${TARGET_OPT_DIR}" clean -fd &>/dev/null || true
      fi
    fi
  else
    git clone https://github.com/Fire-Package/fire-pm.git "${TARGET_OPT_DIR}"
  fi
  INSTALL_SOURCE_DIR="${TARGET_OPT_DIR}"
fi

# 7. Install CLI binary
echo -e "${CYAN}1/4 Installing Fire CLI engine...${NC}"
cp "${INSTALL_SOURCE_DIR}/app/fire" /usr/local/bin/fire.tmp
chmod +x /usr/local/bin/fire.tmp
mv -f /usr/local/bin/fire.tmp /usr/local/bin/fire
if [[ -f "${INSTALL_SOURCE_DIR}/app/ff-service" ]]; then
  cp "${INSTALL_SOURCE_DIR}/app/ff-service" /usr/local/bin/ff-service.tmp
  chmod +x /usr/local/bin/ff-service.tmp
  mv -f /usr/local/bin/ff-service.tmp /usr/local/bin/ff-service
fi

# Configure sudoers rule so fire can manage systemd without password prompts
if [[ -d "/etc/sudoers.d" ]]; then
  SUDOERS_FILE="/etc/sudoers.d/fire-pm"
  {
    echo "# Fire PM — Allow administrative users to manage fire services without password prompt"
    echo "%sudo ALL=(ALL) NOPASSWD: SETENV: /usr/local/bin/fire"
    echo "%wheel ALL=(ALL) NOPASSWD: SETENV: /usr/local/bin/fire"
    if [[ -n "$SUDO_USER" && "$SUDO_USER" != "root" ]]; then
      echo "$SUDO_USER ALL=(ALL) NOPASSWD: SETENV: /usr/local/bin/fire"
    fi
  } > "$SUDOERS_FILE"
  chmod 0440 "$SUDOERS_FILE"
  if command -v visudo &>/dev/null; then
    if ! visudo -c -f "$SUDOERS_FILE" &>/dev/null; then
      rm -f "$SUDOERS_FILE"
    fi
  fi
fi
echo -e "    ${GREEN}✔${NC} Fire CLI installed to /usr/local/bin/fire"

# Install Shell Auto-Completion
if [[ -d "/etc/bash_completion.d" ]]; then
  /usr/local/bin/fire completion bash > /etc/bash_completion.d/fire 2>/dev/null || true
  chmod 644 /etc/bash_completion.d/fire 2>/dev/null || true
elif [[ -d "/usr/share/bash-completion/completions" ]]; then
  /usr/local/bin/fire completion bash > /usr/share/bash-completion/completions/fire 2>/dev/null || true
fi
echo -e "    ${GREEN}✔${NC} Shell auto-completion configured"

# 8. Install TUI
echo -e "${CYAN}2/4 Installing Terminal UI (TUI)...${NC}"
cp "${INSTALL_SOURCE_DIR}/tui/fire_tui.py" /usr/local/bin/fire_tui.py
chmod +x /usr/local/bin/fire_tui.py

# Install Python requirements for TUI
REQUIREMENTS_FILE="${INSTALL_SOURCE_DIR}/tui/requirements.txt"
PIP_CMD=""
if command -v pip3 &>/dev/null; then
  PIP_CMD="pip3"
elif command -v pip &>/dev/null; then
  PIP_CMD="pip"
fi

if [[ -n "$PIP_CMD" ]]; then
  if [[ -f "$REQUIREMENTS_FILE" ]]; then
    $PIP_CMD install -r "$REQUIREMENTS_FILE" &>/dev/null || \
    $PIP_CMD install --break-system-packages -r "$REQUIREMENTS_FILE" &>/dev/null || true
  else
    $PIP_CMD install "textual>=0.70.0" &>/dev/null || \
    $PIP_CMD install --break-system-packages "textual>=0.70.0" &>/dev/null || true
  fi
fi

if python3 -c "import textual" &>/dev/null; then
  echo -e "    ${GREEN}✔${NC} Fire TUI and dependencies installed"
else
  echo -e "    ${YELLOW}⚠${NC} Fire TUI installed to /usr/local/bin/fire_tui.py"
  echo -e "      ${GREY}(Run 'pip3 install textual' if TUI does not start)${NC}"
fi

# 9. Install Systemd templates
echo -e "${CYAN}3/4 Registering Systemd templates...${NC}"
mkdir -p /etc/systemd/system /etc/fire-pm
if [[ -f "${INSTALL_SOURCE_DIR}/shared/units/fire-reload@.service" ]]; then
  cp "${INSTALL_SOURCE_DIR}/shared/units/fire-reload@.service" /etc/systemd/system/
fi
systemctl daemon-reload
echo -e "    ${GREEN}✔${NC} Systemd unit templates registered"

# 10. Web UI Build or Skip
if [[ "$INSTALL_WEB" == "true" ]]; then
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
      echo -e "    ${YELLOW}⚠ Node.js not found. Install Node.js (v22+) to run the Web UI.${NC}"
    fi
    chmod +x "${INSTALL_SOURCE_DIR}/web/start.sh" 2>/dev/null || true
    echo -e "    ${GREEN}✔${NC} Web UI built successfully"
  fi
else
  echo -e "${CYAN}4/4 Web UI Dashboard build skipped${NC}"
  if [[ -f "${INSTALL_SOURCE_DIR}/web/start.sh" ]]; then
    chmod +x "${INSTALL_SOURCE_DIR}/web/start.sh" 2>/dev/null || true
  fi
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
if [[ "$INSTALL_WEB" == "true" ]]; then
  echo -e "  ${BOLD}Start Web UI Dashboard:${NC}"
  echo -e "    ${CYAN}fire start ${INSTALL_SOURCE_DIR}/web/start.sh --name fire-web --env PORT=3000${NC}"
else
  echo -e "  ${BOLD}Web UI Dashboard (Optional):${NC}"
  echo -e "    To build and start the Web UI at any time:"
  echo -e "    ${CYAN}cd ${INSTALL_SOURCE_DIR}/web && pnpm install && pnpm build${NC}"
  echo -e "    ${CYAN}fire start ${INSTALL_SOURCE_DIR}/web/start.sh --name fire-web --env PORT=3000${NC}"
fi
echo ""
