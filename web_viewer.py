#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sqlite3
import json
from flask import Flask, render_template_string, jsonify
from collections import defaultdict
import datetime
import requests
import subprocess

# --- 配置 ---
DB_PATH = "/volume2/download/records/Sony-2/transcripts.db"
SOURCE_DIR = "/volume2/download/records/Sony-2"
ASR_API_URL = "http://192.168.1.111:5000/transcribe"
LOG_FILE_PATH = "/volume1/docker/scripts/transcribe.log"
WEB_PORT = 5009 
# -----------------

app = Flask(__name__)

def format_timestamp(milliseconds):
    seconds = milliseconds / 1000
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{int(h):02}:{int(m):02}:{s:06.3f}"

def get_system_status():
    status = {
        "asr_server": "unknown",
        "pending_files": 0,
        "last_log": "等待日志..."
    }
    try:
        try:
            requests.get(ASR_API_URL.replace("/transcribe", "/"), timeout=1)
            status["asr_server"] = "online"
        except requests.exceptions.RequestException:
             status["asr_server"] = "online"
    except:
        status["asr_server"] = "offline"

    try:
        files = [f for f in os.listdir(SOURCE_DIR) if f.endswith(".aac")]
        status["pending_files"] = len(files)
    except:
        status["pending_files"] = -1

    try:
        if os.path.exists(LOG_FILE_PATH):
            cmd = f"tail -n 10 {LOG_FILE_PATH}" # 多读几行
            result = subprocess.check_output(cmd, shell=True).decode('utf-8')
            status["last_log"] = result
        else:
            status["last_log"] = f"找不到日志文件: {LOG_FILE_PATH}"
    except Exception as e:
        status["last_log"] = f"读取日志失败: {e}"

    return status

def get_transcripts():
    if not os.path.exists(DB_PATH):
        return []
    try:
        db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
        cursor = db.cursor()
        # 获取最近 100 条记录
        cursor.execute("SELECT id, filename, created_at, full_text, segments_json FROM transcriptions ORDER BY created_at DESC LIMIT 100")
        rows = cursor.fetchall()
        db.close()
        
        results = []
        for row in rows:
            data = dict(row)
            try:
                data['segments'] = json.loads(data['segments_json'])
                # 过滤掉空文本的片段
                data['segments'] = [seg for seg in data['segments'] if seg.get('text', '').strip()]
            except:
                data['segments'] = []
            
            for seg in data['segments']:
                seg['start_fmt'] = format_timestamp(seg['start'])
                # 模拟声纹ID (目前后端未支持，暂时全部设为 0)
                seg['spk_id'] = seg.get('spk', 0) 
            
            # 优先从文件名解析时间
            filename = data['filename']
            dt = None
            # 匹配文件名格式：YYYY-MM-DD_HH-MM-SS.aac
            time_pattern = r'^\s*(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})\s*'
            match = re.match(time_pattern, os.path.splitext(filename)[0])
            if match:
                # 组合日期和时间
                date_part = match.group(1)
                time_part = match.group(2)
                # 转换为datetime对象
                try:
                    dt_str = f"{date_part} {time_part.replace('-', ':')}"
                    dt = datetime.datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    pass

            # 如果文件名解析失败，使用数据库的created_at
            if dt is None:
                try:
                    dt = datetime.datetime.fromisoformat(data['created_at'])
                except:
                    pass

            if dt is not None:
                now = datetime.datetime.now()
                data['is_new'] = (now - dt).total_seconds() < 300
                data['date_group'] = dt.strftime('%Y-%m-%d')
                data['time_simple'] = dt.strftime('%H:%M') # 简单时间 14:30
                data['time_full'] = dt.strftime('%Y-%m-%d %H:%M:%S')
            else:
                data['is_new'] = False
                data['date_group'] = "Unknown"
                data['time_simple'] = ""
                data['time_full'] = ""
            results.append(data)
        return results
    except:
        return []

# --- HTML 模板 ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI 录音存档</title>
    <style>
        :root { --primary: #007bff; --bg: #f0f2f5; --card-bg: #ffffff; --text: #333; --console-bg: #1e1e1e; --console-text: #00ff00; --chat-me: #d9fdd3; --chat-other: #ffffff; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: var(--bg); color: var(--text); margin: 0; padding: 0; height: 100vh; display: flex; flex-direction: column; }
        
        /* 顶部导航 Tab */
        .nav-header { background: var(--card-bg); padding: 10px 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); z-index: 100; display: flex; justify-content: center; gap: 20px; }
        .nav-btn { padding: 8px 20px; border: none; background: none; font-size: 1em; font-weight: 600; color: #666; cursor: pointer; border-bottom: 3px solid transparent; transition: all 0.3s; }
        .nav-btn.active { color: var(--primary); border-bottom-color: var(--primary); }
        .nav-btn:hover { color: var(--primary); }

        /* 主内容区域 (用于切换) */
        .view-container { flex: 1; overflow-y: auto; padding: 20px; display: none; }
        .view-container.active { display: block; }

        /* === 视图 1: 仪表盘样式 === */
        .dashboard-panel { display: grid; grid-template-columns: 1fr 2fr; gap: 20px; margin-bottom: 20px; max-width: 1000px; margin-left: auto; margin-right: auto; }
        .status-card { background: var(--card-bg); padding: 20px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); }
        .status-item { margin-bottom: 15px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #eee; padding-bottom: 10px; }
        .status-item:last-child { border-bottom: none; }
        .badge { padding: 4px 8px; border-radius: 4px; font-size: 0.9em; color: white; font-weight: bold; }
        .bg-green { background-color: #28a745; } .bg-red { background-color: #dc3545; } .bg-blue { background-color: #17a2b8; }
        
        .console-window { background: var(--console-bg); color: var(--console-text); padding: 15px; border-radius: 8px; font-family: monospace; font-size: 0.85em; height: 150px; overflow-y: auto; white-space: pre-wrap; }
        
        .transcript-card { background: var(--card-bg); border-radius: 8px; margin-bottom: 15px; padding: 20px; max-width: 1000px; margin-left: auto; margin-right: auto; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        .transcript-card.new-item { border-left: 4px solid #28a745; background-color: #f8fff9; }
        .card-meta { display: flex; justify-content: space-between; color: #888; font-size: 0.85em; margin-bottom: 10px; border-bottom: 1px solid #eee; padding-bottom: 5px; }
        .filename { font-weight: 600; color: #444; }
        .segment { display: flex; gap: 10px; margin-bottom: 4px; }
        .timestamp { font-family: monospace; color: #999; font-size: 0.8em; min-width: 80px; }

        /* === 视图 2: 时光对话样式 (Chat) === */
        .chat-container { max-width: 800px; margin: 0 auto; }
        .chat-date-separator { text-align: center; margin: 20px 0; }
        .chat-date-label { background-color: rgba(0,0,0,0.05); color: #666; padding: 4px 12px; border-radius: 12px; font-size: 0.85em; }
        
        /* 模拟文件分割线 */
        .file-separator { text-align: center; margin: 15px 0; font-size: 0.8em; color: #aaa; display: flex; align-items: center; gap: 10px; }
        .file-separator::before, .file-separator::after { content: ""; flex: 1; height: 1px; background: #ddd; }

        .chat-bubble-row { display: flex; margin-bottom: 15px; gap: 10px; }
        .avatar { width: 40px; height: 40px; background-color: #ccc; border-radius: 50%; display: flex; justify-content: center; align-items: center; font-weight: bold; color: white; font-size: 0.9em; flex-shrink: 0; }
        /* 简单的颜色生成，区分不同说话人(如果有) */
        .avatar-0 { background-color: #007bff; } /* 蓝色 */
        .avatar-1 { background-color: #e83e8c; } /* 粉色 */
        
        .bubble-content { max-width: 70%; display: flex; flex-direction: column; }
        .speaker-name { font-size: 0.75em; color: #888; margin-bottom: 2px; margin-left: 5px; }
        .bubble { background-color: var(--chat-other); padding: 10px 14px; border-radius: 0 12px 12px 12px; position: relative; box-shadow: 0 1px 2px rgba(0,0,0,0.1); font-size: 1em; line-height: 1.5; }
        .chat-time { font-size: 0.7em; color: #999; text-align: right; margin-top: 4px; margin-right: 5px; }

    </style>
</head>
<body>

    <div class="nav-header">
        <button class="nav-btn active" onclick="switchTab('dashboard')">️ 仪表盘</button>
        <button class="nav-btn" onclick="switchTab('chat')"> 时光对话</button>
    </div>

    <div id="view-dashboard" class="view-container active">
        <div class="dashboard-panel">
            <div class="status-card">
                <div class="status-item">
                    <span class="status-label">PC 服务状态</span>
                    <span id="status-asr" class="badge bg-red">检测中...</span>
                </div>
                <div class="status-item">
                    <span class="status-label">排队文件数</span>
                    <span id="status-files" class="badge bg-blue">0</span>
                </div>
                <div class="status-item">
                    <span class="status-label">Web 界面</span>
                    <span class="badge bg-green">在线</span>
                </div>
            </div>
            <div class="console-window">
                <div style="border-bottom:1px solid #444; margin-bottom:5px; color:#888;">root@NAS: monitor_logs (实时)</div>
                <div id="log-display">正在连接日志流...</div>
            </div>
        </div>
        <div id="dashboard-content">
            <div style="text-align: center; color: #999;">加载中...</div>
        </div>
    </div>

    <div id="view-chat" class="view-container">
        <div class="chat-container" id="chat-content">
            <div style="text-align: center; color: #999; margin-top: 50px;">正在生成对话流...</div>
        </div>
    </div>

    <script>
        let lastDataFingerprint = "";

        function switchTab(tabName) {
            document.querySelectorAll('.view-container').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));
            
            document.getElementById('view-' + tabName).classList.add('active');
            // 找到对应的按钮加 active (简单处理)
            const btns = document.querySelectorAll('.nav-btn');
            if(tabName === 'dashboard') btns[0].classList.add('active');
            else btns[1].classList.add('active');
        }

        async function updateLoop() {
            try {
                // 1. 状态更新
                const statusRes = await fetch('/api/status');
                const statusData = await statusRes.json();
                
                const asrBadge = document.getElementById('status-asr');
                if (statusData.asr_server === 'online') {
                    asrBadge.innerText = "在线"; asrBadge.className = "badge bg-green";
                } else {
                    asrBadge.innerText = "离线"; asrBadge.className = "badge bg-red";
                }
                document.getElementById('status-files').innerText = statusData.pending_files;
                document.getElementById('log-display').innerText = statusData.last_log;
                // 自动滚动日志到底部
                const consoleWin = document.querySelector('.console-window');
                consoleWin.scrollTop = consoleWin.scrollHeight;

                // 2. 数据更新
                const dataRes = await fetch('/api/data');
                const items = await dataRes.json();
                
                // 指纹检测，避免无效渲染
                if (items.length === 0) return;
                const currentFingerprint = items.length + "_" + items[0].id;
                if (currentFingerprint === lastDataFingerprint) return;
                lastDataFingerprint = currentFingerprint;

                // 渲染两个视图
                renderDashboard(items);
                renderChat(items);

            } catch (e) { console.error(e); }
        }

        function renderDashboard(items) {
            const container = document.getElementById('dashboard-content');
            let html = "";
            items.forEach(item => {
                let segHtml = "";
                if (item.segments && item.segments.length > 0) {
                    item.segments.forEach(seg => {
                        segHtml += `<div class="segment"><span class="timestamp">[${seg.start_fmt}]</span><span>${seg.text}</span></div>`;
                    });
                } else {
                    segHtml = `<div class="segment"><span>${item.full_text}</span></div>`;
                }
                html += `
                    <div class="transcript-card ${item.is_new ? 'new-item' : ''}">
                        <div class="card-meta"><span class="filename">${item.filename}</span><span>${item.time_full}</span></div>
                        <div>${segHtml}</div>
                    </div>`;
            });
            container.innerHTML = html;
        }

        function renderChat(items) {
            // 这里的 items 是按时间倒序的 (最新的在最前)，为了对话流体验，通常需要正序？
            // 但如果是查看历史记录，倒序看最近的也可以。
            // 我们保持倒序，但把每个文件内部的对话按正序排列。
            
            const container = document.getElementById('chat-content');
            let html = "";
            let currentDay = "";

            items.forEach(item => {
                // 日期分割线
                if (item.date_group !== currentDay) {
                    html += `<div class="chat-date-separator"><span class="chat-date-label">${item.date_group}</span></div>`;
                    currentDay = item.date_group;
                }

                // 文件分割线 (提示来源)
                html += `<div class="file-separator">来源: ${item.filename} (${item.time_simple})</div>`;

                if (item.segments && item.segments.length > 0) {
                    item.segments.forEach(seg => {
                        // 跳过空白文本
                        if (!seg.text || seg.text.trim() === "") {
                            return;
                        }
                        // 模拟头像ID，如果没有就默认 0
                        const spkId = seg.spk_id || 0; 
                        const spkName = "说话人"; // 如果后端能识别，这里可以变成 "Speaker 1"

                        html += `
                            <div class="chat-bubble-row">
                                <div class="avatar avatar-${spkId % 2}">User</div>
                                <div class="bubble-content">
                                    <div class="speaker-name">${spkName}</div>
                                    <div class="bubble">
                                        ${seg.text}
                                    </div>
                                    <div class="chat-time">${seg.start_fmt}</div>
                                </div>
                            </div>
                        `;
                    });
                } else {
                    // 如果没有分段，检查是否有文本内容
                    if (item.full_text && item.full_text.trim() !== "") {
                        html += `
                            <div class="chat-bubble-row">
                                 <div class="avatar avatar-0">User</div>
                                 <div class="bubble-content">
                                    <div class="bubble">${item.full_text}</div>
                                 </div>
                            </div>`;
                    }
                }
            });
            container.innerHTML = html;
        }

        setInterval(updateLoop, 3000);
        updateLoop();
    </script>
</body>
</html>
"""

@app.route('/api/status')
def api_status():
    return jsonify(get_system_status())

@app.route('/api/data')
def api_data():
    return jsonify(get_transcripts())

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=WEB_PORT, debug=False)#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import json
from flask import Flask, render_template_string, jsonify
from collections import defaultdict
import datetime
import os
import requests
import subprocess

# --- 配置 ---
DB_PATH = "/volume2/download/records/Sony-2/transcripts.db"
SOURCE_DIR = "/volume2/download/records/Sony-2"
ASR_API_URL = "http://192.168.1.111:5000/transcribe"
LOG_FILE_PATH = "/volume1/docker/scripts/transcribe.log"
WEB_PORT = 5009 
# -----------------

app = Flask(__name__)

def format_timestamp(milliseconds):
    seconds = milliseconds / 1000
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{int(h):02}:{int(m):02}:{s:06.3f}"

def get_system_status():
    status = {
        "asr_server": "unknown",
        "pending_files": 0,
        "last_log": "等待日志..."
    }
    try:
        try:
            requests.get(ASR_API_URL.replace("/transcribe", "/"), timeout=1)
            status["asr_server"] = "online"
        except requests.exceptions.RequestException:
             status["asr_server"] = "online"
    except:
        status["asr_server"] = "offline"

    try:
        files = [f for f in os.listdir(SOURCE_DIR) if f.endswith(".aac")]
        status["pending_files"] = len(files)
    except:
        status["pending_files"] = -1

    try:
        if os.path.exists(LOG_FILE_PATH):
            cmd = f"tail -n 10 {LOG_FILE_PATH}" # 多读几行
            result = subprocess.check_output(cmd, shell=True).decode('utf-8')
            status["last_log"] = result
        else:
            status["last_log"] = f"找不到日志文件: {LOG_FILE_PATH}"
    except Exception as e:
        status["last_log"] = f"读取日志失败: {e}"

    return status

def get_transcripts():
    if not os.path.exists(DB_PATH):
        return []
    try:
        db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
        cursor = db.cursor()
        # 获取最近 100 条记录
        cursor.execute("SELECT id, filename, created_at, full_text, segments_json FROM transcriptions ORDER BY created_at DESC LIMIT 100")
        rows = cursor.fetchall()
        db.close()
        
        results = []
        for row in rows:
            data = dict(row)
            try:
                data['segments'] = json.loads(data['segments_json'])
            except:
                data['segments'] = []
            
            for seg in data['segments']:
                seg['start_fmt'] = format_timestamp(seg['start'])
                # 模拟声纹ID (目前后端未支持，暂时全部设为 0)
                seg['spk_id'] = seg.get('spk', 0) 
            
            try:
                dt = datetime.datetime.fromisoformat(data['created_at'])
                now = datetime.datetime.now()
                data['is_new'] = (now - dt).total_seconds() < 300
                data['date_group'] = dt.strftime('%Y-%m-%d')
                data['time_simple'] = dt.strftime('%H:%M') # 简单时间 14:30
                data['time_full'] = dt.strftime('%Y-%m-%d %H:%M:%S')
            except:
                data['is_new'] = False
                data['date_group'] = "Unknown"
                data['time_simple'] = ""
                data['time_full'] = ""
            results.append(data)
        return results
    except:
        return []

# --- HTML 模板 ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI 录音存档</title>
    <style>
        :root { --primary: #007bff; --bg: #f0f2f5; --card-bg: #ffffff; --text: #333; --console-bg: #1e1e1e; --console-text: #00ff00; --chat-me: #d9fdd3; --chat-other: #ffffff; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: var(--bg); color: var(--text); margin: 0; padding: 0; height: 100vh; display: flex; flex-direction: column; }
        
        /* 顶部导航 Tab */
        .nav-header { background: var(--card-bg); padding: 10px 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); z-index: 100; display: flex; justify-content: center; gap: 20px; }
        .nav-btn { padding: 8px 20px; border: none; background: none; font-size: 1em; font-weight: 600; color: #666; cursor: pointer; border-bottom: 3px solid transparent; transition: all 0.3s; }
        .nav-btn.active { color: var(--primary); border-bottom-color: var(--primary); }
        .nav-btn:hover { color: var(--primary); }

        /* 主内容区域 (用于切换) */
        .view-container { flex: 1; overflow-y: auto; padding: 20px; display: none; }
        .view-container.active { display: block; }

        /* === 视图 1: 仪表盘样式 === */
        .dashboard-panel { display: grid; grid-template-columns: 1fr 2fr; gap: 20px; margin-bottom: 20px; max-width: 1000px; margin-left: auto; margin-right: auto; }
        .status-card { background: var(--card-bg); padding: 20px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); }
        .status-item { margin-bottom: 15px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #eee; padding-bottom: 10px; }
        .status-item:last-child { border-bottom: none; }
        .badge { padding: 4px 8px; border-radius: 4px; font-size: 0.9em; color: white; font-weight: bold; }
        .bg-green { background-color: #28a745; } .bg-red { background-color: #dc3545; } .bg-blue { background-color: #17a2b8; }
        
        .console-window { background: var(--console-bg); color: var(--console-text); padding: 15px; border-radius: 8px; font-family: monospace; font-size: 0.85em; height: 150px; overflow-y: auto; white-space: pre-wrap; }
        
        .transcript-card { background: var(--card-bg); border-radius: 8px; margin-bottom: 15px; padding: 20px; max-width: 1000px; margin-left: auto; margin-right: auto; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        .transcript-card.new-item { border-left: 4px solid #28a745; background-color: #f8fff9; }
        .card-meta { display: flex; justify-content: space-between; color: #888; font-size: 0.85em; margin-bottom: 10px; border-bottom: 1px solid #eee; padding-bottom: 5px; }
        .filename { font-weight: 600; color: #444; }
        .segment { display: flex; gap: 10px; margin-bottom: 4px; }
        .timestamp { font-family: monospace; color: #999; font-size: 0.8em; min-width: 80px; }

        /* === 视图 2: 时光对话样式 (Chat) === */
        .chat-container { max-width: 800px; margin: 0 auto; }
        .chat-date-separator { text-align: center; margin: 20px 0; }
        .chat-date-label { background-color: rgba(0,0,0,0.05); color: #666; padding: 4px 12px; border-radius: 12px; font-size: 0.85em; }
        
        /* 模拟文件分割线 */
        .file-separator { text-align: center; margin: 15px 0; font-size: 0.8em; color: #aaa; display: flex; align-items: center; gap: 10px; }
        .file-separator::before, .file-separator::after { content: ""; flex: 1; height: 1px; background: #ddd; }

        .chat-bubble-row { display: flex; margin-bottom: 15px; gap: 10px; }
        .avatar { width: 40px; height: 40px; background-color: #ccc; border-radius: 50%; display: flex; justify-content: center; align-items: center; font-weight: bold; color: white; font-size: 0.9em; flex-shrink: 0; }
        /* 简单的颜色生成，区分不同说话人(如果有) */
        .avatar-0 { background-color: #007bff; } /* 蓝色 */
        .avatar-1 { background-color: #e83e8c; } /* 粉色 */
        
        .bubble-content { max-width: 70%; display: flex; flex-direction: column; }
        .speaker-name { font-size: 0.75em; color: #888; margin-bottom: 2px; margin-left: 5px; }
        .bubble { background-color: var(--chat-other); padding: 10px 14px; border-radius: 0 12px 12px 12px; position: relative; box-shadow: 0 1px 2px rgba(0,0,0,0.1); font-size: 1em; line-height: 1.5; }
        .chat-time { font-size: 0.7em; color: #999; text-align: right; margin-top: 4px; margin-right: 5px; }

    </style>
</head>
<body>

    <div class="nav-header">
        <button class="nav-btn active" onclick="switchTab('dashboard')">️ 仪表盘</button>
        <button class="nav-btn" onclick="switchTab('chat')"> 时光对话</button>
    </div>

    <div id="view-dashboard" class="view-container active">
        <div class="dashboard-panel">
            <div class="status-card">
                <div class="status-item">
                    <span class="status-label">PC 服务状态</span>
                    <span id="status-asr" class="badge bg-red">检测中...</span>
                </div>
                <div class="status-item">
                    <span class="status-label">排队文件数</span>
                    <span id="status-files" class="badge bg-blue">0</span>
                </div>
                <div class="status-item">
                    <span class="status-label">Web 界面</span>
                    <span class="badge bg-green">在线</span>
                </div>
            </div>
            <div class="console-window">
                <div style="border-bottom:1px solid #444; margin-bottom:5px; color:#888;">root@NAS: monitor_logs (实时)</div>
                <div id="log-display">正在连接日志流...</div>
            </div>
        </div>
        <div id="dashboard-content">
            <div style="text-align: center; color: #999;">加载中...</div>
        </div>
    </div>

    <div id="view-chat" class="view-container">
        <div class="chat-container" id="chat-content">
            <div style="text-align: center; color: #999; margin-top: 50px;">正在生成对话流...</div>
        </div>
    </div>

    <script>
        let lastDataFingerprint = "";

        function switchTab(tabName) {
            document.querySelectorAll('.view-container').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));
            
            document.getElementById('view-' + tabName).classList.add('active');
            // 找到对应的按钮加 active (简单处理)
            const btns = document.querySelectorAll('.nav-btn');
            if(tabName === 'dashboard') btns[0].classList.add('active');
            else btns[1].classList.add('active');
        }

        async function updateLoop() {
            try {
                // 1. 状态更新
                const statusRes = await fetch('/api/status');
                const statusData = await statusRes.json();
                
                const asrBadge = document.getElementById('status-asr');
                if (statusData.asr_server === 'online') {
                    asrBadge.innerText = "在线"; asrBadge.className = "badge bg-green";
                } else {
                    asrBadge.innerText = "离线"; asrBadge.className = "badge bg-red";
                }
                document.getElementById('status-files').innerText = statusData.pending_files;
                document.getElementById('log-display').innerText = statusData.last_log;
                // 自动滚动日志到底部
                const consoleWin = document.querySelector('.console-window');
                consoleWin.scrollTop = consoleWin.scrollHeight;

                // 2. 数据更新
                const dataRes = await fetch('/api/data');
                const items = await dataRes.json();
                
                // 指纹检测，避免无效渲染
                if (items.length === 0) return;
                const currentFingerprint = items.length + "_" + items[0].id;
                if (currentFingerprint === lastDataFingerprint) return;
                lastDataFingerprint = currentFingerprint;

                // 渲染两个视图
                renderDashboard(items);
                renderChat(items);

            } catch (e) { console.error(e); }
        }

        function renderDashboard(items) {
            const container = document.getElementById('dashboard-content');
            let html = "";
            items.forEach(item => {
                let segHtml = "";
                if (item.segments && item.segments.length > 0) {
                    item.segments.forEach(seg => {
                        segHtml += `<div class="segment"><span class="timestamp">[${seg.start_fmt}]</span><span>${seg.text}</span></div>`;
                    });
                } else {
                    segHtml = `<div class="segment"><span>${item.full_text}</span></div>`;
                }
                html += `
                    <div class="transcript-card ${item.is_new ? 'new-item' : ''}">
                        <div class="card-meta"><span class="filename">${item.filename}</span><span>${item.time_full}</span></div>
                        <div>${segHtml}</div>
                    </div>`;
            });
            container.innerHTML = html;
        }

        function renderChat(items) {
            // 这里的 items 是按时间倒序的 (最新的在最前)，为了对话流体验，通常需要正序？
            // 但如果是查看历史记录，倒序看最近的也可以。
            // 我们保持倒序，但把每个文件内部的对话按正序排列。
            
            const container = document.getElementById('chat-content');
            let html = "";
            let currentDay = "";

            items.forEach(item => {
                // 日期分割线
                if (item.date_group !== currentDay) {
                    html += `<div class="chat-date-separator"><span class="chat-date-label">${item.date_group}</span></div>`;
                    currentDay = item.date_group;
                }

                // 文件分割线 (提示来源)
                html += `<div class="file-separator">来源: ${item.filename} (${item.time_simple})</div>`;

                if (item.segments && item.segments.length > 0) {
                    item.segments.forEach(seg => {
                    // 跳过空白文本
                    if (!seg.text || seg.text.trim() === "") {
                        return;
                    }
                    // 模拟头像ID，如果没有就默认 0
                    const spkId = seg.spk_id || 0; 
                    const spkName = "说话人"; // 如果后端能识别，这里可以变成 "Speaker 1"

                    html += `
                        <div class="chat-bubble-row">
                            <div class="avatar avatar-${spkId % 2}">User</div>
                            <div class="bubble-content">
                                <div class="speaker-name">${spkName}</div>
                                <div class="bubble">
                                    ${seg.text}
                                </div>
                                <div class="chat-time">${seg.start_fmt}</div>
                            </div>
                        </div>
                    `;
                });
                } else {
                // 如果没有分段，就显示一大块
                if (!item.full_text || item.full_text.trim() === "") {
                    return;
                }
                html += `
                    <div class="chat-bubble-row">
                         <div class="avatar avatar-0">User</div>
                         <div class="bubble-content">
                            <div class="bubble">${item.full_text}</div>
                         </div>
                    </div>`;
            }
            });
            container.innerHTML = html;
        }

        setInterval(updateLoop, 3000);
        updateLoop();
    </script>
</body>
</html>
"""

@app.route('/api/status')
def api_status():
    return jsonify(get_system_status())

@app.route('/api/data')
def api_data():
    return jsonify(get_transcripts())

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=WEB_PORT, debug=False)