#!/bin/bash

# ===================== 一键部署脚本 =====================
# 支持系统: Linux (Debian/Ubuntu/CentOS)
# 功能: 自动安装依赖、配置环境、启动服务
# =======================================================

echo "======================================================"
echo "              AI 录音存档系统一键部署脚本             "
echo "======================================================"
echo ""

# ----------------- 配置区域 -----------------
CONFIG_DIR="/volume2/download/records/Sony-2"
DB_PATH="${CONFIG_DIR}/transcripts.db"
WEB_PORT=5009
ASR_SERVER_URL="http://192.168.1.111:5000/transcribe"
# -------------------------------------------

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # 重置颜色

# 检查是否为root用户
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}请使用root用户运行此脚本 (sudo bash $0)${NC}"
    exit 1
fi

# 检查系统类型
check_system() {
    if [ -f /etc/debian_version ]; then
        SYSTEM="debian"
    elif [ -f /etc/redhat-release ]; then
        SYSTEM="centos"
    else
        echo -e "${RED}不支持的系统类型，请手动安装${NC}"
        exit 1
    fi
    echo -e "${GREEN}检测到系统: $SYSTEM${NC}"
}

# 安装Python和依赖
install_dependencies() {
    echo -e "${YELLOW}正在安装Python和依赖...${NC}"
    
    if [ "$SYSTEM" = "debian" ]; then
        apt-get update -y
        apt-get install -y python3 python3-pip python3-venv sqlite3
    elif [ "$SYSTEM" = "centos" ]; then
        yum update -y
        yum install -y python3 python3-pip python3-venv sqlite3
    fi
    
    # 验证安装
    python3 --version
    pip3 --version
    echo -e "${GREEN}Python环境安装完成${NC}"
}

# 创建虚拟环境并安装依赖包
setup_venv() {
    echo -e "${YELLOW}正在设置Python虚拟环境...${NC}"
    
    # 确保配置目录存在
    mkdir -p "$CONFIG_DIR"
    
    # 创建虚拟环境
    python3 -m venv "${CONFIG_DIR}/venv"
    
    # 激活虚拟环境并安装依赖
    source "${CONFIG_DIR}/venv/bin/activate"
    pip install --upgrade pip
    pip install flask requests
    
    # 退出虚拟环境
    deactivate
    
    echo -e "${GREEN}虚拟环境配置完成${NC}"
}

# 配置应用程序
configure_app() {
    echo -e "${YELLOW}正在配置应用程序...${NC}"
    
    # 检查并修复脚本权限
    chmod +x "$(dirname "$0")/web_viewer.py"
    chmod +x "$(dirname "$0")/transcribe.py"
    
    echo -e "${GREEN}应用程序配置完成${NC}"
}

# 初始化数据库
init_database() {
    echo -e "${YELLOW}正在初始化数据库...${NC}"
    
    # 确保配置目录存在
    mkdir -p "$CONFIG_DIR"
    
    # 创建数据库表
    python3 <<EOF
import sqlite3
import os

db_path = "$DB_PATH"

# 确保目录存在
os.makedirs(os.path.dirname(db_path), exist_ok=True)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS transcriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    full_text TEXT,
    segments_json TEXT
);
''')
conn.commit()
conn.close()
EOF
    
    echo -e "${GREEN}数据库初始化完成${NC}"
}

# 启动服务
start_services() {
    echo -e "${YELLOW}正在启动服务...${NC}"
    
    # 进入脚本目录
    cd "$(dirname "$0")"
    
    # 启动Web服务
    if [ ! -f "web_viewer.pid" ]; then
        nohup python3 web_viewer.py > web_viewer.log 2>&1 &
        echo $! > web_viewer.pid
        echo -e "${GREEN}Web服务已启动${NC}"
    else
        echo -e "${YELLOW}Web服务已经在运行中${NC}"
    fi
    
    # 启动转录服务
    if [ ! -f "transcribe.pid" ]; then
        nohup python3 transcribe.py > transcribe.log 2>&1 &
        echo $! > transcribe.pid
        echo -e "${GREEN}转录服务已启动${NC}"
    else
        echo -e "${YELLOW}转录服务已经在运行中${NC}"
    fi
}

# 显示部署结果
show_result() {
    echo -e "${GREEN}======================================================${NC}"
    echo -e "${GREEN}                   部署完成！${NC}"
    echo -e "${GREEN}======================================================${NC}"
    echo -e "${YELLOW}Web 界面地址:${NC} http://$(hostname -I | awk '{print $1}'):$WEB_PORT"
    echo -e "${YELLOW}配置文件目录:${NC} $CONFIG_DIR"
    echo -e "${YELLOW}数据库路径:${NC} $DB_PATH"
    echo -e "${YELLOW}日志文件:${NC} $(pwd)/web_viewer.log $(pwd)/transcribe.log"
    echo -e ""
    echo -e "${GREEN}服务已自动启动，您可以开始使用了！${NC}"
    echo -e "${YELLOW}停止服务:${NC} ./stop_services.sh"
    echo -e "${YELLOW}重启服务:${NC} ./restart_services.sh"
}

# 创建停止服务脚本
create_stop_script() {
    cat > stop_services.sh <<EOF
#!/bin/bash

if [ -f "web_viewer.pid" ]; then
    kill \$(cat web_viewer.pid) 2>/dev/null
    rm web_viewer.pid
    echo "Web服务已停止"
fi

if [ -f "transcribe.pid" ]; then
    kill \$(cat transcribe.pid) 2>/dev/null
    rm transcribe.pid
    echo "转录服务已停止"
fi
EOF
    
    chmod +x stop_services.sh
}

# 创建重启服务脚本
create_restart_script() {
    cat > restart_services.sh <<EOF
#!/bin/bash

echo "正在重启服务..."
./stop_services.sh
./one_click_deploy.sh --start-only
echo "服务已重启完成"
EOF
    
    chmod +x restart_services.sh
}

# 主流程
main() {
    # 解析命令行参数
    if [ "$1" = "--start-only" ]; then
        start_services
        show_result
        exit 0
    fi
    
    check_system
    install_dependencies
    setup_venv
    configure_app
    init_database
    start_services
    create_stop_script
    create_restart_script
    show_result
}

# 执行主流程
main "$@"