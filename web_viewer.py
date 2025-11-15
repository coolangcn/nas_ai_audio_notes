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
LOG_FILE_PATH = "/volume1/docker/scripts/nas_ai_audio_notes/transcribe.log"
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
        files = [f for f in os.listdir(SOURCE_DIR) if f.endswith(".m4a")]
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
                # 兼容后端传来的 spk 字段
                seg['spk_id'] = seg.get('spk', 0) 
            
            # 优先从文件名解析时间
            filename = data['filename']
            dt = None
            time_patterns = [
                r'^\s*(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})\s*',  # 原始格式
                r'^\s*recording-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})\s*'  # 新格式
            ]
            
            for pattern in time_patterns:
                match = re.match(pattern, os.path.splitext(filename)[0])
                if match:
                    try:
                        if pattern == time_patterns[0]: 
                            date_part = match.group(1)
                            time_part = match.group(2)
                            dt_str = f"{date_part} {time_part.replace('-', ':')}"
                            dt = datetime.datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
                        else: 
                            year, month, day, hour, minute, second = match.groups()
                            dt_str = f"{year}-{month}-{day} {hour}:{minute}:{second}"
                            dt = datetime.datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
                        break 
                    except ValueError:
                        continue 
                        
            if dt is None:
                try:
                    dt = datetime.datetime.fromisoformat(data['created_at'])
                except:
                    pass

            if dt is not None:
                now = datetime.datetime.now()
                data['is_new'] = (now - dt).total_seconds() < 300
                data['date_group'] = dt.strftime('%Y-%m-%d')
                data['time_simple'] = dt.strftime('%H:%M') 
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

        /* 主内容区域 */
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
        .file-separator { text-align: center; margin: 15px 0; font-size: 0.8em; color: #aaa; display: flex; align-items: center; gap: 10px; }
        .file-separator::before, .file-separator::after { content: ""; flex: 1; height: 1px; background: #ddd; }

        .chat-bubble-row { display: flex; margin-bottom: 15px; gap: 10px; }
        .avatar { width: 40px; height: 40px; background-color: #ccc; border-radius: 50%; display: flex; justify-content: center; align-items: center; font-weight: bold; color: white; font-size: 0.9em; flex-shrink: 0; }
        
        .bubble-content { max-width: 70%; display: flex; flex-direction: column; }
        .speaker-name { font-size: 0.75em; color: #888; margin-bottom: 2px; margin-left: 5px; }
        .bubble { background-color: var(--chat-other); padding: 10px 14px; border-radius: 0 12px 12px 12px; position: relative; box-shadow: 0 1px 2px rgba(0,0,0,0.1); font-size: 1em; line-height: 1.5; }
        .chat-time { font-size: 0.7em; color: #999; text-align: right; margin-top: 4px; margin-right: 5px; }

        /* === 视图 3: 统计分析样式 (新增) === */
        .analysis-card { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 12px; margin-bottom: 25px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }
        .analysis-card h3 { margin: 0 0 10px 0; font-size: 1.5em; }
        .analysis-card p { margin: 0; opacity: 0.9; }
        .speaker-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 20px; }
        .speaker-card { background: var(--card-bg); border-radius: 12px; padding: 20px; display: flex; align-items: center; gap: 15px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); transition: transform 0.2s; border: 1px solid #eee; }
        .speaker-card:hover { transform: translateY(-3px); box-shadow: 0 5px 15px rgba(0,0,0,0.1); }
        .speaker-icon { width: 60px; height: 60px; border-radius: 50%; display: flex; justify-content: center; align-items: center; font-size: 1.5em; font-weight: bold; color: white; flex-shrink: 0; }
        .speaker-info { flex: 1; }
        .speaker-info h4 { margin: 0 0 10px 0; color: #333; font-size: 1.1em; }
        .speaker-stats-detail { display: flex; justify-content: space-between; background: #f8f9fa; padding: 8px 12px; border-radius: 8px; text-align: center; }
        
        /* 扩展头像颜色到 10 种 */
        .avatar-0 { background: #4e54c8; } .avatar-1 { background: #ef476f; } .avatar-2 { background: #ffd166; color: #333; } .avatar-3 { background: #06d6a0; } .avatar-4 { background: #118ab2; }
        .avatar-5 { background: #073b4c; } .avatar-6 { background: #9d4edd; } .avatar-7 { background: #ff9f1c; } .avatar-8 { background: #2ec4b6; } .avatar-9 { background: #e71d36; }

    </style>
</head>
<body>

    <div class="nav-header">
        <button class="nav-btn active" onclick="switchTab('dashboard')">️ 仪表盘</button>
        <button class="nav-btn" onclick="switchTab('chat')"> 时光对话</button>
        <button class="nav-btn" onclick="switchTab('analysis')">📊 统计分析</button>
    </div>

    <div id="view-dashboard" class="view-container active">
        <div class="dashboard-panel">
            <div class="status-card">
                <div class="status-item"><span class="status-label">PC 服务状态</span><span id="status-asr" class="badge bg-red">检测中...</span></div>
                <div class="status-item"><span class="status-label">排队文件数</span><span id="status-files" class="badge bg-blue">0</span></div>
                <div class="status-item"><span class="status-label">Web 界面</span><span class="badge bg-green">在线</span></div>
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
    
    <div id="view-analysis" class="view-container">
        <div id="analysis-content" style="max-width: 1000px; margin: 0 auto;">
            <div style="text-align: center; color: #999; margin-top: 50px;">正在分析声纹数据...</div>
        </div>
    </div>

    <script>
        let lastDataFingerprint = "";

        function switchTab(tabName) {
            document.querySelectorAll('.view-container').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));
            
            document.getElementById('view-' + tabName).classList.add('active');
            
            // 简单处理按钮激活状态
            const btns = document.querySelectorAll('.nav-btn');
            if(tabName === 'dashboard') btns[0].classList.add('active');
            else if(tabName === 'chat') btns[1].classList.add('active');
            else if(tabName === 'analysis') btns[2].classList.add('active');
        }
        
        // 辅助函数：获取头像颜色索引
        function getAvatarIndex(spkId) {
            if (typeof spkId === 'number') return spkId;
            let hash = 0;
            for (let i = 0; i < spkId.length; i++) hash += spkId.charCodeAt(i);
            return Math.abs(hash);
        }

        // 辅助函数：从原始 segments 计算统计数据
        function processStats(items) {
            items.forEach(item => {
                const stats = {};
                if (item.segments && item.segments.length > 0) {
                    item.segments.forEach(seg => {
                        const spkId = seg.spk_id !== undefined ? seg.spk_id : 'unknown';
                        // 如果是数字ID，转成 "说话人 X"；如果是名字，直接用
                        const spkName = typeof seg.spk_id === 'number' ? `说话人 ${seg.spk_id}` : (seg.spk_id || "未知");
                        
                        if (!stats[spkId]) {
                            stats[spkId] = {
                                speaker_name: spkName,
                                count: 0,
                                total_duration: 0
                            };
                        }
                        stats[spkId].count += 1;
                        // 简单计算时长：结束时间 - 开始时间
                        stats[spkId].total_duration += (seg.end - seg.start);
                    });
                }
                item.speaker_stats = stats;
            });
            return items;
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
                const consoleWin = document.querySelector('.console-window');
                consoleWin.scrollTop = consoleWin.scrollHeight;

                // 2. 数据更新
                const dataRes = await fetch('/api/data');
                let items = await dataRes.json();
                
                // === 预处理统计数据 ===
                items = processStats(items);
                // ==================
                
                // 指纹检测
                if (items.length === 0) return;
                const currentFingerprint = items.length + "_" + items[0].id;
                if (currentFingerprint === lastDataFingerprint) return;
                lastDataFingerprint = currentFingerprint;

                // 渲染三个视图
                renderDashboard(items);
                renderChat(items);
                renderAnalysis(items);

            } catch (e) { console.error(e); }
        }

        function renderDashboard(items) {
            const container = document.getElementById('dashboard-content');
            let html = "";
            items.forEach(item => {
                let segHtml = "";
                if (item.segments && item.segments.length > 0) {
                    item.segments.forEach(seg => {
                        if (!seg.text || seg.text.trim() === "") return;
                        segHtml += `<div class="segment"><span class="timestamp">[${seg.start_fmt}]</span><span>${seg.text}</span></div>`;
                    });
                } else {
                    if (item.full_text) segHtml = `<div class="segment"><span>${item.full_text}</span></div>`;
                }
                if (!segHtml) return; // 空卡片不显示

                html += `
                    <div class="transcript-card ${item.is_new ? 'new-item' : ''}">
                        <div class="card-meta"><span class="filename">${item.filename}</span><span>${item.time_full}</span></div>
                        <div>${segHtml}</div>
                    </div>`;
            });
            container.innerHTML = html;
        }

        function renderChat(items) {
            const container = document.getElementById('chat-content');
            let html = "";
            let currentDay = "";

            items.forEach(item => {
                // 预检内容
                let hasContent = false;
                if (item.segments && item.segments.length > 0) {
                    hasContent = item.segments.some(seg => seg.text && seg.text.trim() !== "");
                } else if (item.full_text && item.full_text.trim() !== "") {
                    hasContent = true;
                }
                if (!hasContent) return;

                if (item.date_group !== currentDay) {
                    html += `<div class="chat-date-separator"><span class="chat-date-label">${item.date_group}</span></div>`;
                    currentDay = item.date_group;
                }
                html += `<div class="file-separator">来源: ${item.filename} (${item.time_simple})</div>`;

                if (item.segments && item.segments.length > 0) {
                    item.segments.forEach(seg => {
                        if (!seg.text || seg.text.trim() === "") return;
                        
                        const spkId = seg.spk_id !== undefined ? seg.spk_id : 0;
                        let spkName = typeof spkId === 'number' ? `说话人 ${spkId}` : spkId;
                        let avatarIdx = getAvatarIndex(spkId);
                        const timeDisplay = `<div class="chat-time">${seg.start_fmt}</div>`;

                        html += `
                            <div class="chat-bubble-row">
                                <div class="avatar avatar-${avatarIdx % 10}">User</div>
                                <div class="bubble-content">
                                    <div class="speaker-name">${spkName}</div>
                                    <div class="bubble">${seg.text}</div>
                                    ${timeDisplay}
                                </div>
                            </div>
                        `;
                    });
                } else {
                    html += `
                        <div class="chat-bubble-row">
                             <div class="avatar avatar-0">User</div>
                             <div class="bubble-content">
                                <div class="bubble">${item.full_text}</div>
                                <div class="chat-time">来源时间: ${item.time_simple}</div>
                             </div>
                        </div>`;
                }
            });
            container.innerHTML = html;
        }

        function renderAnalysis(items) {
            const container = document.getElementById('analysis-content');
            const globalSpeakerStats = {};
            let totalFiles = items.length;
            
            items.forEach(item => {
                if (item.speaker_stats) {
                    for (const [spkId, stats] of Object.entries(item.speaker_stats)) {
                        // 这里的 spkId 是字典键，总是字符串类型，需要转回原始类型判断
                        let originalSpkId = spkId;
                        if (!isNaN(spkId)) originalSpkId = parseInt(spkId);

                        if (!globalSpeakerStats[spkId]) {
                            globalSpeakerStats[spkId] = {
                                id: originalSpkId,
                                name: stats.speaker_name,
                                totalCount: 0,
                                totalDuration: 0,
                                filesParticipated: new Set()
                            };
                        }
                        globalSpeakerStats[spkId].totalCount += stats.count;
                        globalSpeakerStats[spkId].totalDuration += stats.total_duration;
                        globalSpeakerStats[spkId].filesParticipated.add(item.filename);
                    }
                }
            });
            
            let html = `
                <div class="analysis-card">
                    <h3>📊 声纹识别统计分析</h3>
                    <p>共分析 ${totalFiles} 个录音文件，识别出 ${Object.keys(globalSpeakerStats).length} 位不同的说话人</p>
                </div>
                <div class="speaker-grid">`;
            
            for (const [key, stats] of Object.entries(globalSpeakerStats)) {
                const avgDuration = stats.totalCount > 0 ? (stats.totalDuration / stats.totalCount / 1000).toFixed(1) : 0;
                const filesCount = stats.filesParticipated.size;
                const avatarIdx = getAvatarIndex(stats.id);
                
                html += `
                    <div class="speaker-card">
                        <div class="speaker-icon avatar-${avatarIdx % 10}">
                            ${stats.name.slice(-1)}
                        </div>
                        <div class="speaker-info">
                            <h4>${stats.name}</h4>
                            <div class="speaker-stats-detail">
                                <div><div style="font-weight: bold;">${stats.totalCount}</div><div style="font-size: 0.8em;">发言次数</div></div>
                                <div><div style="font-weight: bold;">${avgDuration}s</div><div style="font-size: 0.8em;">平均时长</div></div>
                                <div><div style="font-weight: bold;">${filesCount}</div><div style="font-size: 0.8em;">参与文件</div></div>
                            </div>
                        </div>
                    </div>`;
            }
            
            html += '</div>';
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