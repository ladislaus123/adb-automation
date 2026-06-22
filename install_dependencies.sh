#!/usr/bin/env bash
# =============================================================================
# install_dependencies.sh
# Setup script for adb-automation on Windows (run via Git Bash as Administrator)
#
# Installs:
#   1. Java JDK 21        -- required by Android SDK tools
#   2. Node.js LTS        -- required by Appium
#   3. Android cmdline-tools + platform-tools (adb, sdkmanager, etc.)
#   4. Appium server
#   5. UIAutomator2 Appium driver
#   6. FFmpeg             -- required for voice/audio message conversion
#
# Usage:
#   Right-click Git Bash -> "Run as Administrator", then:
#   bash install_dependencies.sh
# =============================================================================

set -euo pipefail

# ─── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log_info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
log_ok()      { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*"; }
log_section() { echo -e "\n${BOLD}══════════════════════════════════════════${NC}"; echo -e "${BOLD} $*${NC}"; echo -e "${BOLD}══════════════════════════════════════════${NC}"; }

# ─── Guard: must run in Git Bash on Windows ───────────────────────────────────
if [[ "$OSTYPE" != "msys" && "$OSTYPE" != "cygwin" && "$OSTYPE" != "win32" ]]; then
    log_error "This script is for Windows (Git Bash / MSYS2 / Cygwin) only."
    exit 1
fi

# ─── Paths ────────────────────────────────────────────────────────────────────
# Convert Windows USERPROFILE to a Unix-style path usable inside Git Bash
USER_HOME="$(cygpath -u "$USERPROFILE")"
ANDROID_HOME_UNIX="$USER_HOME/Android/Sdk"
ANDROID_HOME_WIN="$USERPROFILE\\Android\\Sdk"

CMDLINE_TOOLS_DIR="$ANDROID_HOME_UNIX/cmdline-tools/latest"
PLATFORM_TOOLS_DIR="$ANDROID_HOME_UNIX/platform-tools"

# Android cmdline-tools download URL.
# Check https://developer.android.com/studio#command-line-tools-only for newer versions.
ANDROID_CMDLINE_URL="https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip"
ANDROID_CMDLINE_ZIP="/tmp/android-cmdline-tools.zip"

# ─── Helper: check if a command exists ────────────────────────────────────────
has_cmd() { command -v "$1" &>/dev/null; }

# ─── Helper: set a persistent Windows environment variable via setx ───────────
setenv_win() {
    local name="$1"
    local value="$2"
    cmd //c setx "$name" "$value" /M &>/dev/null \
        || cmd //c setx "$name" "$value" &>/dev/null \
        || log_warn "Could not set $name via setx — set it manually."
    log_ok "Set $name = $value"
}

# ─── Helper: append a directory to the persistent Windows PATH ────────────────
add_to_path_win() {
    local dir_win="$1"
    # Read current machine PATH
    local current_path
    current_path="$(cmd //c "echo %PATH%" 2>/dev/null || true)"
    if echo "$current_path" | grep -qi "$dir_win"; then
        log_ok "PATH already contains: $dir_win"
    else
        setenv_win "PATH" "$current_path;$dir_win"
        log_ok "Added to PATH: $dir_win"
    fi
    # Also export for the duration of this session
    export PATH="$PATH:$(cygpath -u "$dir_win")"
}

# ─── Helper: check if winget is available ─────────────────────────────────────
check_winget() {
    if has_cmd winget; then
        return 0
    else
        log_warn "winget not found. Install 'App Installer' from the Microsoft Store or use Windows 11+."
        return 1
    fi
}

# =============================================================================
# 1. JAVA JDK
# =============================================================================
log_section "Step 1 — Java JDK 21"

if has_cmd java; then
    JAVA_VERSION=$(java -version 2>&1 | head -1)
    log_ok "Java already installed: $JAVA_VERSION"
else
    log_info "Installing Microsoft OpenJDK 21 via winget..."
    if check_winget; then
        winget install --id Microsoft.OpenJDK.21 --exact --silent --accept-package-agreements --accept-source-agreements
        log_ok "Java JDK 21 installed."
    else
        log_error "Cannot install Java automatically."
        log_info  "Download and install JDK 21 from: https://adoptium.net/temurin/releases/?version=21"
        read -rp "Press Enter after installing Java JDK 21, or Ctrl+C to abort..."
    fi
fi

# Detect JAVA_HOME if not already set
if [[ -z "${JAVA_HOME:-}" ]]; then
    # Try common locations
    for candidate in \
        "C:/Program Files/Microsoft/jdk-21"* \
        "C:/Program Files/Eclipse Adoptium/jdk-21"* \
        "C:/Program Files/Java/jdk-21"*; do
        if [[ -d "$candidate" ]]; then
            JAVA_HOME_WIN="$(cygpath -w "$candidate")"
            setenv_win "JAVA_HOME" "$JAVA_HOME_WIN"
            add_to_path_win "$JAVA_HOME_WIN\\bin"
            break
        fi
    done
fi

# =============================================================================
# 2. NODE.JS
# =============================================================================
log_section "Step 2 — Node.js LTS"

if has_cmd node; then
    log_ok "Node.js already installed: $(node --version)"
else
    log_info "Installing Node.js LTS via winget..."
    if check_winget; then
        winget install --id OpenJS.NodeJS.LTS --exact --silent --accept-package-agreements --accept-source-agreements
        log_ok "Node.js installed."
        # Refresh PATH for this session
        export PATH="$PATH:/c/Program Files/nodejs"
    else
        log_error "Cannot install Node.js automatically."
        log_info  "Download and install Node.js from: https://nodejs.org/en/download"
        read -rp "Press Enter after installing Node.js, or Ctrl+C to abort..."
    fi
fi

if ! has_cmd npm; then
    log_error "npm not found. Ensure Node.js is installed correctly and restart Git Bash."
    exit 1
fi
log_ok "npm version: $(npm --version)"

# =============================================================================
# 3. ANDROID COMMAND-LINE TOOLS
# =============================================================================
log_section "Step 3 — Android SDK Command-Line Tools"

if [[ -f "$CMDLINE_TOOLS_DIR/bin/sdkmanager" ]]; then
    log_ok "Android cmdline-tools already present at: $CMDLINE_TOOLS_DIR"
else
    log_info "Creating Android SDK directory: $ANDROID_HOME_UNIX"
    mkdir -p "$ANDROID_HOME_UNIX/cmdline-tools"

    log_info "Downloading Android cmdline-tools (this may take a minute)..."
    curl -L --progress-bar "$ANDROID_CMDLINE_URL" -o "$ANDROID_CMDLINE_ZIP"

    log_info "Extracting cmdline-tools..."
    # Extract to a temp folder then rename to 'latest' as required by sdkmanager
    TMP_EXTRACT="$ANDROID_HOME_UNIX/cmdline-tools/_extract_tmp"
    mkdir -p "$TMP_EXTRACT"
    unzip -q "$ANDROID_CMDLINE_ZIP" -d "$TMP_EXTRACT"
    # The zip contains a 'cmdline-tools' subfolder
    mv "$TMP_EXTRACT/cmdline-tools" "$CMDLINE_TOOLS_DIR"
    rm -rf "$TMP_EXTRACT" "$ANDROID_CMDLINE_ZIP"
    log_ok "cmdline-tools extracted to: $CMDLINE_TOOLS_DIR"
fi

# Set ANDROID_HOME environment variable
setenv_win "ANDROID_HOME" "$ANDROID_HOME_WIN"
export ANDROID_HOME="$ANDROID_HOME_UNIX"

# Add SDK directories to PATH
add_to_path_win "$ANDROID_HOME_WIN\\cmdline-tools\\latest\\bin"
add_to_path_win "$ANDROID_HOME_WIN\\platform-tools"
add_to_path_win "$ANDROID_HOME_WIN\\emulator"

# Accept licenses non-interactively and install platform-tools (adb)
log_info "Accepting Android SDK licenses..."
yes | "$CMDLINE_TOOLS_DIR/bin/sdkmanager.bat" --licenses &>/dev/null || true

log_info "Installing Android platform-tools (adb)..."
"$CMDLINE_TOOLS_DIR/bin/sdkmanager.bat" \
    --sdk_root="$ANDROID_HOME_WIN" \
    "platform-tools" \
    "build-tools;34.0.0" \
    "platforms;android-34"

# Verify adb
if [[ -f "$PLATFORM_TOOLS_DIR/adb.exe" ]]; then
    log_ok "adb installed: $PLATFORM_TOOLS_DIR/adb.exe"
else
    log_error "adb not found after platform-tools install. Check the SDK path."
    exit 1
fi

# =============================================================================
# 4. APPIUM SERVER
# =============================================================================
log_section "Step 4 — Appium Server"

if has_cmd appium; then
    log_ok "Appium already installed: $(appium --version)"
else
    log_info "Installing Appium globally via npm..."
    npm install -g appium
    log_ok "Appium installed: $(appium --version)"
fi

# =============================================================================
# 5. UIAUTOMATOR2 DRIVER
# =============================================================================
log_section "Step 5 — UIAutomator2 Appium Driver"

INSTALLED_DRIVERS=$(appium driver list --installed 2>/dev/null || true)
if echo "$INSTALLED_DRIVERS" | grep -qi "uiautomator2"; then
    log_ok "UIAutomator2 driver already installed."
else
    log_info "Installing UIAutomator2 driver..."
    appium driver install uiautomator2
    log_ok "UIAutomator2 driver installed."
fi

# =============================================================================
# 6. FFMPEG
# =============================================================================
log_section "Step 6 — FFmpeg (audio conversion)"

if has_cmd ffmpeg; then
    log_ok "FFmpeg already installed: $(ffmpeg -version 2>&1 | head -1)"
else
    log_info "Installing FFmpeg via winget..."
    if check_winget; then
        winget install --id Gyan.FFmpeg --exact --silent --accept-package-agreements --accept-source-agreements
        # Common install path; add to PATH
        add_to_path_win "C:\\ProgramData\\chocolatey\\bin"
        # Winget typically puts it here:
        add_to_path_win "C:\\Program Files\\FFmpeg\\bin"
        log_ok "FFmpeg installed."
    else
        log_warn "winget unavailable. Download FFmpeg from: https://ffmpeg.org/download.html#build-windows"
        log_warn "Extract it and add the 'bin' folder to your PATH manually."
    fi
fi

# =============================================================================
# FINAL SUMMARY
# =============================================================================
log_section "Installation Summary"

check_tool() {
    local label="$1"
    local cmd="$2"
    if has_cmd "$cmd"; then
        log_ok "$label: $(command -v "$cmd")"
    else
        log_warn "$label: NOT FOUND in current session PATH (may require a new terminal)"
    fi
}

check_tool "java"    java
check_tool "node"    node
check_tool "npm"     npm
check_tool "adb"     adb
check_tool "appium"  appium
check_tool "ffmpeg"  ffmpeg

echo ""
log_info "ANDROID_HOME = $ANDROID_HOME_WIN"
echo ""
echo -e "${YELLOW}ACTION REQUIRED:${NC}"
echo "  1. Close this Git Bash window and open a new one for PATH changes to take effect."
echo "  2. Enable ADB on your Android device:"
echo "       Settings → About Phone → tap 'Build Number' 7 times"
echo "       Settings → Developer Options → enable 'USB Debugging'"
echo "  3. Start Appium before running the project:"
echo "       appium --port 4723"
echo ""
log_ok "All non-Python dependencies installed."
