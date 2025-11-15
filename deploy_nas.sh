#!/bin/bash

# ================= 配置区域 =================
PYTHON_PATH="/bin/python3"
SCRIPT_DIR="/volume1/docker/scripts"

# 需要运行的两个核心脚本
WEB_SCRIPT="web_viewer.py"
MONITOR_SCRIPT="transcribe.py"
# ===========================================

echo "=== 开始执行 NAS 部署 (幂等模式) ==="
echo "时间: $(date)"

# --- 核心函数: 确保服务运行 (幂等) ---
ensure_service_running() {
    local SCRIPT_NAME=$1
    local FULL_PATH="${SCRIPT_DIR}/${SCRIPT_NAME}"
    local LOG_FILE="${SCRIPT_DIR}/${SCRIPT_NAME%.*}.log"

    echo "正在检查: $SCRIPT_NAME ..."

    # 1. 获取正在运行的进程数量
    # 使用 grep 技巧 [f]ile.py 避免匹配到 grep 命令本身
    # wc -l 用于统计行数
    local PROC_COUNT=$(ps aux | grep "[${SCRIPT_NAME:0:1}]${SCRIPT_NAME:1}" | wc -l)

    if [ "$PROC_COUNT" -eq 1 ]; then
        echo "  [保持] $SCRIPT_NAME 已经在运行中 (PID: $(ps aux | grep "[${SCRIPT_NAME:0:1}]${SCRIPT_NAME:1}" | awk '{print $2}')). 无需操作。"
    elif [ "$PROC_COUNT" -gt 1 ]; then
        echo "  [警告] 检测到 $PROC_COUNT 个 $SCRIPT_NAME 实例在运行！建议手动停止多余进程。"
        echo "  (为安全起见，脚本不会自动杀进程，请手动运行: killall python3 或 pkill -f $SCRIPT_NAME)"
    else
        echo "  [启动] 未检测到运行实例。正在启动..."
        nohup $PYTHON_PATH "$FULL_PATH" > "$LOG_FILE" 2>&1 &
        sleep 2 # 等待进程初始化

        # 二次确认启动结果
        if ps aux | grep -q "[${SCRIPT_NAME:0:1}]${SCRIPT_NAME:1}"; then
             echo "  [成功] $SCRIPT_NAME 已成功启动。"
        else
             echo "  [失败] $SCRIPT_NAME 启动失败！请查看日志: $LOG_FILE"
        fi
    fi
    echo "-----------------------------------"
}

# --- 执行部署逻辑 ---

# 1. 检查并部署 Web 查看器
ensure_service_running "$WEB_SCRIPT"

# 2. 检查并部署 实时监控器
ensure_service_running "$MONITOR_SCRIPT"

echo "=== 部署检查完成 ==="
echo "Web 界面地址: http://[NAS_IP]:5009"
echo "监控模式: 实时监控中"