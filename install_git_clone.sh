#!/bin/bash

# ================================================================= #
# Auto Installer & Cloner - TTMediaBot
# ================================================================= #

# Auto-elevate to root via sudo if needed
if [ "$EUID" -ne 0 ]; then
    echo "Not running as root. Re-launching with sudo..."
    exec sudo bash "$0" "$@"
fi


REPO_URL="https://github.com/JoaoDEVWHADS/TTMediaBot.git"

# Retry package-manager commands when another apt/dpkg process temporarily holds a lock.
run_with_retries() {
    local max_attempts=30
    local delay_seconds=10
    local attempt=1

    while true; do
        if "$@"; then
            return 0
        fi

        if [ "$attempt" -ge "$max_attempts" ]; then
            echo "❌ Command failed after $max_attempts attempts: $*"
            return 1
        fi

        echo "⚠️ Package manager is busy or the command failed. Retrying in ${delay_seconds}s... ($attempt/$max_attempts)"
        sleep "$delay_seconds"
        attempt=$((attempt + 1))
    done
}

# Function to detect package manager and install packages
install_packages() {
    local PKGS=("$@")

    if command -v apt-get &> /dev/null; then
        # apt may be temporarily locked by apt-daily/unattended-upgrades.
        # Retry instead of continuing with missing dependencies.
        run_with_retries apt-get update || return 1
        run_with_retries apt-get -o DPkg::Lock::Timeout=300 install -y "${PKGS[@]}" || return 1
    elif command -v dnf &> /dev/null; then
        dnf install -y "${PKGS[@]}" || return 1
    elif command -v yum &> /dev/null; then
        yum install -y "${PKGS[@]}" || return 1
    elif command -v pacman &> /dev/null; then
        pacman -S --noconfirm "${PKGS[@]}" || return 1
    elif command -v zypper &> /dev/null; then
        zypper install -y "${PKGS[@]}" || return 1
    elif command -v apk &> /dev/null; then
        apk add --no-cache "${PKGS[@]}" || return 1
    else
        echo "❌ Error: Package manager not found. Please install manually: ${PKGS[*]}"
        return 1
    fi
}

ensure_command() {
    local command_name="$1"
    local package_name="${2:-$1}"

    if command -v "$command_name" &> /dev/null; then
        echo "$command_name is already installed."
        return 0
    fi

    echo "$command_name not found. Installing..."
    if ! install_packages "$package_name"; then
        echo "❌ Failed to install required dependency: $package_name"
        exit 1
    fi

    if ! command -v "$command_name" &> /dev/null; then
        echo "❌ $command_name is still unavailable after installation."
        exit 1
    fi

    echo "✅ $command_name installed successfully."
}

echo "--- Checking for Git ---"
ensure_command git git

echo "--- Checking for unzip (ZIP extractor) ---"
ensure_command unzip unzip

# Detect if we are already inside the repository
if [ -d ".git" ] && git remote get-url origin 2>/dev/null | grep -q "TTMediaBot"; then
    echo "--- Already inside TTMediaBot repository. Skipping clone. ---"
    CURRENT_IS_REPO=true
else
    CURRENT_IS_REPO=false
fi

DIR_NAME="TTMediaBot"

if [ "$CURRENT_IS_REPO" = false ]; then
    if [ -d "$DIR_NAME" ]; then
        echo "Directory '$DIR_NAME' already exists. Updating..."
        cd "$DIR_NAME" || exit
        git pull
    else
        echo "--- Cloning Repository ---"
        git clone "$REPO_URL"
        if [ $? -ne 0 ]; then
            echo "Error cloning repository. Check your internet connection."
            exit 1
        fi
        cd "$DIR_NAME" || exit
    fi
fi

# Enter directory and set permissions
# Set permissions and ownership
echo "--- Setting Permissions and Ownership ---"
git config core.fileMode false 2>/dev/null

REAL_USER=${SUDO_USER:-$USER}

# Ensure permissions are correct for the current folder and everything inside
chown -R "$REAL_USER":"$REAL_USER" .
chmod -R 777 .
chmod +x *.sh

echo "Ownership and permissions set for user: $REAL_USER"

echo "--- Checking TeamTalk_DLL ---"

# ... (down near line 148 and 154) ...

DLL_URL="https://github.com/JoaoDEVWHADS/TTMediaBot/releases/download/downloadttdll/TeamTalk_DLL.zip"
ARCH=$(uname -m)
if [[ "$ARCH" == "aarch64" || "$ARCH" =~ ^arm ]]; then
    echo "ℹ️ ARM architecture detected ($ARCH). Using ARM DLL..."
    DLL_URL="https://github.com/JoaoDEVWHADS/TTMediaBot/releases/download/downloadttdll/ttarm.zip"
else
    echo "ℹ️ x86_64/AMD64 architecture detected ($ARCH). Using x86 DLL..."
    DLL_URL="https://github.com/JoaoDEVWHADS/TTMediaBot/releases/download/downloadttdll/TeamTalk_DLL.zip"
fi
DLL_FILE="TeamTalk_DLL.zip"

if [ -d "TeamTalk_DLL" ] && [ -f "TeamTalk_DLL/libTeamTalk5.so" ]; then
    echo "✅ TeamTalk_DLL folder and library already exist. Skipping download and extraction."
else
    if [ -f "$DLL_FILE" ]; then
        echo "📦 TeamTalk_DLL.zip already exists. Skipping download."
    else
        echo "📥 Downloading TeamTalk_DLL..."
        wget "$DLL_URL" -O "$DLL_FILE"
        if [ $? -ne 0 ]; then
            echo "❌ Error downloading TeamTalk_DLL."
            exit 1
        fi
        echo "✅ Download complete!"
    fi

    echo "--- Extracting TeamTalk_DLL ---"
    unzip -o "$DLL_FILE"
    if [ $? -ne 0 ]; then
        echo "❌ Error extracting TeamTalk_DLL."
        exit 1
    fi
    echo "✅ Extraction complete!"

    echo "--- Removing TeamTalk_DLL zip ---"
    rm -f "$DLL_FILE"
    echo "✅ ZIP file removed."
fi

if [ ! -d "TeamTalk_DLL" ]; then
    echo "❌ ERROR: TeamTalk_DLL folder not found!"
    exit 1
fi
echo "✅ TeamTalk_DLL folder is ready!"

    
    echo "--- Setting permissions for TeamTalk_DLL ---"
    chown -R "$REAL_USER":"$REAL_USER" TeamTalk_DLL || true
    chmod -R 777 TeamTalk_DLL
    echo "Permissions set for TeamTalk_DLL folder."
    
    echo "--- Final Verification ---"
    
    ls -la | grep TeamTalk_DLL
    
    echo "Setup Complete! Starting Docker Manager..."
        sleep 2

        if [ -f "./ttbotdocker.sh" ]; then
            chmod +x ./ttbotdocker.sh
            exec ./ttbotdocker.sh
        else
            echo "ERROR: ttbotdocker.sh not found!"
            exit 1
        fi