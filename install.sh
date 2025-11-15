#!/bin/bash
# ==============================================================================
# NAS AI音频笔记系统 - 可重复部署安装脚本
# 功能：自动化安装依赖、配置环境、部署服务
# ==============================================================================

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# ==============================================================================
# 配置区域 - 可根据实际环境修改
# ==============================================================================
PROJECT_NAME="nas_ai_audio_notes"
SCRIPT_DIR="/volume1/docker/scripts/${PROJECT_NAME}"
SOURCE_DIR="/volume2/download/records/Sony-2"
WEB_PORT=5009
ASR_API_URL="http://192.168.1.111:5000/transcribe"
# ==============================================================================

log_info "开始部署 ${PROJECT_NAME} 系统..."

# 1. 系统依赖检查和安装
log_info "检查系统依赖..."
check_and_install_system_deps() {
    # 检查Python3
    if ! command -v python3 &> /dev/null; then
        log_error "Python3 未安装，请先安装Python3"
        exit 1
    fi
    
    # 检查pip
    if ! command -v pip3 &> /dev/null; then
        log_info "正在安装pip..."
        apt-get update && apt-get install -y python3-pip
    fi
    
    # 检查ffmpeg
    if ! command -v ffmpeg &> /dev/null; then
        log_info "正在安装ffmpeg..."
        apt-get update && apt-get install -y ffmpeg
    fi
    
    # 检查curl
    if ! command -v curl &> /dev/null; then
        log_info "正在安装curl..."
        apt-get update && apt-get install -y curl
    fi
    
    log_success "系统依赖检查完成"
}

# 2. 创建项目目录
create_directories() {
    log_info "创建项目目录..."
    
    # 创建脚本目录
    mkdir -p "${SCRIPT_DIR}"
    log_success "创建脚本目录: ${SCRIPT_DIR}"
    
    # 创建音频源目录
    mkdir -p "${SOURCE_DIR}"
    mkdir -p "${SOURCE_DIR}/transcripts"
    mkdir -p "${SOURCE_DIR}/processed"
    log_success "创建音频目录: ${SOURCE_DIR}"
    
    # 设置权限
    chmod 755 "${SCRIPT_DIR}"
    chmod 755 "${SOURCE_DIR}"
    chmod 755 "${SOURCE_DIR}/transcripts"
    chmod 755 "${SOURCE_DIR}/processed"
}

# 3. 安装Python依赖
install_python_deps() {
    log_info "安装Python依赖包..."
    
    # 创建requirements.txt
    cat > "${SCRIPT_DIR}/requirements.txt" << EOF
Flask==3.0.0
requests==2.31.0
numpy==1.24.0
EOF
    
    # 安装依赖
    pip3 install -r "${SCRIPT_DIR}/requirements.txt" --user
    
    log_success "Python依赖安装完成"
}

# 4. 部署项目文件
deploy_project_files() {
    log_info "部署项目文件..."
    
    # 当前脚本所在目录（假设在项目根目录）
    CURRENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    
    # 复制核心文件到部署目录
    cp -f "${CURRENT_DIR}/web_viewer.py" "${SCRIPT_DIR}/"
    cp -f "${CURRENT_DIR}/transcribe.py" "${SCRIPT_DIR}/"
    cp -f "${CURRENT_DIR}/deploy_nas.sh" "${SCRIPT_DIR}/"
    cp -f "${CURRENT_DIR}/install.sh" "${SCRIPT_DIR}/"
    
    # 设置执行权限
    chmod +x "${SCRIPT_DIR}/web_viewer.py"
    chmod +x "${SCRIPT_DIR}/transcribe.py"
    chmod +x "${SCRIPT_DIR}/deploy_nas.sh"
    chmod +x "${SCRIPT_DIR}/install.sh"
    
    log_success "项目文件部署完成"
}

# 5. 配置服务
configure_services() {
    log_info "配置服务..."
    
    # 创建系统服务文件（可选）
    cat > "${SCRIPT_DIR}/${PROJECT_NAME}.service" << EOF
[Unit]
Description=NAS AI Audio Notes Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${SCRIPT_DIR}
ExecStart=${SCRIPT_DIR}/deploy_nas.sh
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
    
    # 创建systemd服务（如果需要）
    if [ -d "/etc/systemd/system" ]; then
        cp "${SCRIPT_DIR}/${PROJECT_NAME}.service" "/etc/systemd/system/"
        systemctl daemon-reload
        log_success "systemd服务文件已创建"
    fi
    
    # 创建启动快捷脚本
    cat > "${SCRIPT_DIR}/start.sh" << 'EOF'
#!/bin/bash
echo "启动NAS AI音频笔记系统..."
cd "$(dirname "$0")"
bash deploy_nas.sh
EOF
    chmod +x "${SCRIPT_DIR}/start.sh"
    
    log_success "服务配置完成"
}

# 6. 健康检查
health_check() {
    log_info "执行健康检查..."
    
    # 检查必要文件
    if [ ! -f "${SCRIPT_DIR}/web_viewer.py" ]; then
        log_error "web_viewer.py 文件不存在"
        return 1
    fi
    
    if [ ! -f "${SCRIPT_DIR}/transcribe.py" ]; then
        log_error "transcribe.py 文件不存在"
        return 1
    fi
    
    # 检查Python环境
    python3 -c "import flask, requests" 2>/dev/null || {
        log_error "Python依赖包缺失"
        return 1
    }
    
    # 检查端口占用
    if netstat -tlnp 2>/dev/null | grep -q ":${WEB_PORT}"; then
        log_warning "端口 ${WEB_PORT} 已被占用"
    fi
    
    log_success "健康检查通过"
}

# 7. 启动服务
start_services() {
    log_info "启动服务..."
    
    cd "${SCRIPT_DIR}"
    
    # 先停止已有服务
    pkill -f "web_viewer.py" || true
    pkill -f "transcribe.py" || true
    sleep 2
    
    # 启动Web服务
    log_info "启动Web服务..."
    nohup python3 "${SCRIPT_DIR}/web_viewer.py" > "${SCRIPT_DIR}/web_viewer.log" 2>&1 &
    
    sleep 3
    
    # 启动转录监控服务
    log_info "启动转录监控服务..."
    nohup python3 "${SCRIPT_DIR}/transcribe.py" > "${SCRIPT_DIR}/transcribe.log" 2>&1 &
    
    # 检查服务状态
    if ps aux | grep -q "[w]eb_viewer.py"; then
        log_success "Web服务启动成功 (PID: $(ps aux | grep '[w]eb_viewer.py' | awk '{print $2}'))"
    else
        log_error "Web服务启动失败"
    fi
    
    if ps aux | grep -q "[t]ranscribe.py"; then
        log_success "转录服务启动成功 (PID: $(ps aux | grep '[t]ranscribe.py' | awk '{print $2}'))"
    else
        log_error "转录服务启动失败"
    fi
}

# 8. 显示部署信息
show_deployment_info() {
    log_success "=== 部署完成 ==="
    echo
    echo "📁 项目目录: ${SCRIPT_DIR}"
    echo "📁 音频目录: ${SOURCE_DIR}"
    echo "🌐 Web界面: http://$(hostname -I | awk '{print $1}'):${WEB_PORT}"
    echo "🔄 监控脚本: ${SCRIPT_DIR}/transcribe.py"
    echo "🔧 部署脚本: ${SCRIPT_DIR}/deploy_nas.sh"
    echo "📝 日志文件:"
    echo "   - Web服务: ${SCRIPT_DIR}/web_viewer.log"
    echo "   - 转录服务: ${SCRIPT_DIR}/transcribe.log"
    echo
    echo "🚀 快速命令:"
    echo "   - 重启服务: bash ${SCRIPT_DIR}/deploy_nas.sh"
    echo "   - 查看状态: ps aux | grep -E '(web_viewer|transcribe).py'"
    echo "   - 查看日志: tail -f ${SCRIPT_DIR}/web_viewer.log"
    echo
    echo "📋 下一步操作:"
    echo "   1. 确保ASR服务在 ${ASR_API_URL} 运行正常"
    echo "   2. 将音频文件放入 ${SOURCE_DIR} 目录"
    echo "   3. 打开浏览器访问Web界面查看结果"
}

# 主执行流程
main() {
    log_info "开始执行部署流程..."
    
    check_and_install_system_deps
    create_directories
    install_python_deps
    deploy_project_files
    configure_services
    health_check
    start_services
    show_deployment_info
    
    log_success "🎉 部署成功完成！"
}

# 执行主函数
main "$@"