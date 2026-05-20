#!/bin/bash
# 喜马拉雅 XM → MP3 转换器 一键启动脚本
#
# 双击即可使用。
# 首次运行会检测并自动安装缺失的依赖。
# 仅在需要安装 Homebrew 时会问您一次（因为这会请求系统密码）。

cd "$(dirname "$0")"

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

echo ""
echo -e "${BOLD}===========================================${NC}"
echo -e "${BOLD}   喜马拉雅 XM → MP3 转换器${NC}"
echo -e "${BOLD}===========================================${NC}"
echo ""

# ============================================================
# 前置检查（只警告不阻断）
# ============================================================

# 路径里含特殊字符（中文 OK，但空格/emoji 可能让某些命令出错）
SCRIPT_DIR="$(pwd)"
if echo "$SCRIPT_DIR" | grep -qE "['\"]"; then
    echo -e "${YELLOW}⚠ 当前路径含引号字符，可能导致命令失败：${NC}"
    echo "  $SCRIPT_DIR"
    echo "  建议把项目移到简单路径下（比如 ~/Desktop/xm-converter）"
    echo ""
fi

# 磁盘空间检测
FREE_GB=$(df -g . | awk 'NR==2 {print $4}')
if [ -n "$FREE_GB" ] && [ "$FREE_GB" -lt 3 ]; then
    echo -e "${YELLOW}⚠ 磁盘可用空间不足 3GB（当前 ${FREE_GB}GB）${NC}"
    echo "  安装 Homebrew + Python + ffmpeg 大约需要 2GB 空间。"
    echo ""
fi

# ============================================================
# 第 1 步：Xcode Command Line Tools（brew 的前置依赖）
# ============================================================
if ! xcode-select -p >/dev/null 2>&1; then
    echo -e "${BLUE}→ 检测到缺少 Xcode 命令行工具，开始安装...${NC}"
    echo -e "${DIM}  系统会弹出一个安装对话框，请点击"安装"。${NC}"
    echo -e "${DIM}  整个过程约 2-5 分钟，期间本窗口会等待。${NC}"
    xcode-select --install 2>/dev/null

    # 等用户在弹窗里点击"安装"并完成
    until xcode-select -p >/dev/null 2>&1; do
        sleep 3
    done
    echo -e "${GREEN}✓ Xcode 命令行工具安装完成${NC}"
else
    echo -e "${GREEN}✓ Xcode 命令行工具已就绪${NC}"
fi

# ============================================================
# 第 2 步：Rosetta 2（Apple Silicon 上某些 brew 包需要）
# ============================================================
if [ "$(uname -m)" = "arm64" ]; then
    if ! /usr/bin/pgrep -q oahd; then
        echo -e "${BLUE}→ 检测到缺少 Rosetta 2，正在静默安装...${NC}"
        softwareupdate --install-rosetta --agree-to-license >/dev/null 2>&1 && \
            echo -e "${GREEN}✓ Rosetta 2 安装完成${NC}" || \
            echo -e "${YELLOW}⚠ Rosetta 2 安装失败（可能不影响后续步骤，继续）${NC}"
    else
        echo -e "${GREEN}✓ Rosetta 2 已就绪${NC}"
    fi
fi

# ============================================================
# 第 3 步：Homebrew（唯一需要 y/n 的步骤，因为要 sudo 密码）
# ============================================================
# 修正 PATH，让刚装好但当前 shell 还看不到的 brew 也能找到
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# 检测时不光看 command -v，还要看实际路径，避免重复装
BREW_BIN=""
if command -v brew >/dev/null 2>&1; then
    BREW_BIN=$(command -v brew)
elif [ -x /opt/homebrew/bin/brew ]; then
    BREW_BIN=/opt/homebrew/bin/brew
    eval "$($BREW_BIN shellenv)"
elif [ -x /usr/local/bin/brew ]; then
    BREW_BIN=/usr/local/bin/brew
    eval "$($BREW_BIN shellenv)"
fi

if [ -z "$BREW_BIN" ]; then
    echo ""
    echo -e "${YELLOW}检测到您还没装 Homebrew（macOS 包管理器）。${NC}"
    echo "本程序需要它来安装 Python 和 ffmpeg。"
    echo ""
    echo -e "${BOLD}注意：安装过程会请您输入一次开机密码（输入时屏幕不显示，是正常的）。${NC}"
    echo ""
    read -p "$(echo -e "${YELLOW}是否现在自动安装 Homebrew？${NC} [y/n]: ")" yn
    case $yn in
        [Yy]* )
            echo "→ 正在安装 Homebrew（约 3-5 分钟）..."
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
            if [ $? -ne 0 ]; then
                echo -e "${RED}✗ Homebrew 安装失败${NC}"
                echo "请去 https://brew.sh 手动安装后再次双击本脚本。"
                read -n 1 -s -r -p "按任意键退出..."
                exit 1
            fi
            export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
            echo -e "${GREEN}✓ Homebrew 安装完成${NC}"
            ;;
        * )
            echo "已取消。"
            read -n 1 -s -r -p "按任意键退出..."
            exit 0
            ;;
    esac
else
    echo -e "${GREEN}✓ Homebrew 已就绪${NC}"
fi

# ============================================================
# 第 4 步：Python 3（自动装，不再问）
# ============================================================
if ! command -v python3 >/dev/null 2>&1; then
    echo -e "${BLUE}→ 检测到缺少 Python 3，正在自动安装（约 1-2 分钟）...${NC}"
    brew install python
    if [ $? -ne 0 ]; then
        echo -e "${RED}✗ Python 安装失败${NC}"
        read -n 1 -s -r -p "按任意键退出..."
        exit 1
    fi
    echo -e "${GREEN}✓ Python 安装完成${NC}"
else
    echo -e "${GREEN}✓ Python: $(python3 --version)${NC}"
fi

# ============================================================
# 第 5 步：ffmpeg（自动下载，不再问）
# ============================================================
FFMPEG_OK=0
if [ -x "./bin/ffmpeg" ] && ./bin/ffmpeg -version >/dev/null 2>&1; then
    FFMPEG_OK=1
    echo -e "${GREEN}✓ ffmpeg 已就绪（项目内嵌）${NC}"
elif command -v ffmpeg >/dev/null 2>&1; then
    FFMPEG_OK=1
    echo -e "${GREEN}✓ ffmpeg 已就绪（系统已装）${NC}"
fi

if [ "$FFMPEG_OK" -eq 0 ]; then
    echo -e "${BLUE}→ 检测到缺少 ffmpeg，正在自动下载（约 50MB）...${NC}"
    mkdir -p bin

    # 校验值来自 https://www.osxexperts.net
    EXPECTED_SHA256="9a08d61f9328e8164ba560ee7a79958e357307fcfeea6fe626b7d66cdc287028"

    if curl -fL --progress-bar -o bin/ffmpeg.zip "https://www.osxexperts.net/ffmpeg81arm.zip"; then
        cd bin
        unzip -o -q ffmpeg.zip
        rm -f ffmpeg.zip
        chmod +x ffmpeg

        # SHA256 校验（不强制，作者可能更新版本会变）
        ACTUAL_SHA256=$(shasum -a 256 ffmpeg | awk '{print $1}')
        if [ "$ACTUAL_SHA256" != "$EXPECTED_SHA256" ]; then
            echo -e "${DIM}  注：SHA256 与预期不符，可能 ffmpeg 已更新版本（继续）${NC}"
        fi

        # 移除 quarantine + ad-hoc 签名（Apple Silicon 必须）
        xattr -cr ffmpeg 2>/dev/null
        codesign --force -s - ffmpeg 2>/dev/null
        cd ..

        if [ -x "./bin/ffmpeg" ] && ./bin/ffmpeg -version >/dev/null 2>&1; then
            echo -e "${GREEN}✓ ffmpeg 下载完成${NC}"
        else
            echo -e "${YELLOW}⚠ 下载的 ffmpeg 无法运行，改用 Homebrew 安装${NC}"
            brew install ffmpeg
        fi
    else
        echo -e "${YELLOW}⚠ 直接下载失败（网络问题），改用 Homebrew 安装${NC}"
        brew install ffmpeg
    fi
fi

# ============================================================
# 第 6 步：Python 虚拟环境
# ============================================================
if [ ! -d ".venv" ]; then
    echo -e "${BLUE}→ 首次运行，创建虚拟环境...${NC}"
    python3 -m venv .venv
fi
source .venv/bin/activate

# ============================================================
# 第 7 步：Python 依赖
# ============================================================
if [ ! -f ".venv/.deps_installed" ]; then
    echo -e "${BLUE}→ 安装 Python 依赖中（首次约 1-2 分钟）...${NC}"

    # 用 --trusted-host 绕过部分 macOS 上 Python 缺系统证书导致的 SSL 报错
    PIP_OPTS="--trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org"

    pip install --upgrade pip $PIP_OPTS >/dev/null 2>&1

    if ! pip install $PIP_OPTS -r requirements.txt; then
        echo ""
        echo -e "${RED}✗ Python 依赖安装失败${NC}"
        echo "最常见原因是网络问题。请检查网络后重试。"
        read -n 1 -s -r -p "按任意键退出..."
        exit 1
    fi

    touch .venv/.deps_installed
    echo -e "${GREEN}✓ Python 依赖安装完成${NC}"
fi

# ============================================================
# 启动 GUI
# ============================================================
echo ""
echo -e "${BOLD}→ 启动程序...${NC}"
echo ""
python3 xm_converter.py
