#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import subprocess
import requests
import json
import datetime
import sqlite3
import time
import argparse

# --- 配置 ---
DEFAULT_CONFIG = {
    "ASR_HTTP_URL": "http://192.168.1.111:5000/transcribe",
    "SOURCE_DIR": "/volume2/download/records/Sony-2",
    "TRANSCRIPT_DIR": "/volume2/download/records/Sony-2/transcripts",
    "PROCESSED_DIR": "/volume2/download/records/Sony-2/processed",
    "N8N_WEBHOOK_URL": "https://n8n.moco.fun/webhook/bea45d47-d1fc-498e-bf69-d48dc079f04a",
    "DB_PATH": "/volume2/download/records/Sony-2/transcripts.db" 
}

# 全局配置变量
CONFIG = DEFAULT_CONFIG.copy()

def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='音频转录脚本')
    parser.add_argument('--source-path', type=str, help='源音频文件路径')
    return parser.parse_args()

def update_config(args):
    """根据命令行参数更新配置"""
    global CONFIG
    if args.source_path:
        # 更新所有相关路径
        base_path = args.source_path
        CONFIG["SOURCE_DIR"] = base_path
        CONFIG["TRANSCRIPT_DIR"] = os.path.join(base_path, "transcripts")
        CONFIG["PROCESSED_DIR"] = os.path.join(base_path, "processed")
        CONFIG["DB_PATH"] = os.path.join(base_path, "transcripts.db")
        print(f"[配置] 使用自定义源路径: {base_path}")
# ---------------------------------------------

def format_time(ms):
    """辅助函数：将毫秒转换为 HH:MM:SS 格式"""
    seconds = ms / 1000
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{int(h):02}:{int(m):02}:{int(s):02}"

def init_db():
    try:
        conn = sqlite3.connect(CONFIG["DB_PATH"])
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
    except Exception as e:
        print(f"数据库初始化失败: {e}")

def save_to_db(filename, full_text, segments_list):
    try:
        conn = sqlite3.connect(CONFIG["DB_PATH"])
        cursor = conn.cursor()
        # 这里的 segments_list 现在包含了后端返回的 'spk' 字段
        # json.dumps 会自动把它存入数据库，无需修改表结构
        segments_json = json.dumps(segments_list, ensure_ascii=False)
        cursor.execute(
            "INSERT INTO transcriptions (filename, full_text, segments_json) VALUES (?, ?, ?)",
            (filename, full_text, segments_json)
        )
        conn.commit()
        conn.close()
        print(f"  [DB] Saved {filename}")
        return True
    except Exception as e:
        print(f"  [DB Error] {e}")
        return False

def notify_n8n(status, filename, details):
    if not CONFIG["N8N_WEBHOOK_URL"]: return
    payload = {"status": status, "filename": filename, "details": details, "timestamp": datetime.datetime.now().isoformat()}
    try:
        requests.post(CONFIG["N8N_WEBHOOK_URL"], json=payload, timeout=5)
    except:
        pass

def convert_audio_to_wav(audio_path, wav_path):
    """将音频文件转换为WAV格式，支持m4a、acc、aac格式"""
    FFMPEG_PATH = "/usr/local/bin/ffmpeg"
    # 转换为 16k 采样率单声道，符合 FunASR 最佳实践
    command = [FFMPEG_PATH, '-i', audio_path, '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', wav_path, '-y']
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return True
    except Exception as e:
        print(f"  [Convert Error] {e}")
        return False

def save_transcript_with_spk(full_text, segments, txt_path):
    """保存带有声纹和时间戳的 TXT 文件"""
    try:
        content_lines = []
        
        # 1. 先写入全文摘要
        content_lines.append(f"=== 全文摘要 ===\n{full_text}\n")
        content_lines.append("=== 对话记录 (按说话人) ===")
        
        # 2. 写入带声纹的分段对话
        for seg in segments:
            start_str = format_time(seg.get('start', 0))
            spk_id = seg.get('spk', 0) # 获取声纹ID
            text = seg.get('text', '').strip()
            
            # 格式: [00:05:12] [Speaker 0]: 这里的饭很好吃
            line = f"[{start_str}] [Speaker {spk_id}]: {text}"
            content_lines.append(line)
            
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write("\n\n".join(content_lines))
            
        return True
    except Exception as e:
        print(f"  [Save TXT Error] {e}")
        return False

def transcribe_wav(wav_path):
    url = CONFIG["ASR_HTTP_URL"]
    try:
        with open(wav_path, 'rb') as f:
            files = {'audio_file': (os.path.basename(wav_path), f, 'audio/wav')}
            # 【修改】超时时间增加到 1800s (30分钟)，因为声纹识别会增加耗时
            response = requests.post(url, files=files, timeout=1800) 
        response.raise_for_status() 
        data = response.json()
        if data.get("full_text") is not None:
            return data
        else:
            print(f"  [API Error] {data}")
            return None
    except Exception as e:
        print(f"  [Request Error] {e}")
        return None

def process_one_loop():
    """执行一次扫描处理"""
    processed_count = 0
    # 检查目录里有没有 .m4a、.acc、.aac 文件
    files = [f for f in os.listdir(CONFIG["SOURCE_DIR"]) 
             if f.endswith(".m4a") or f.endswith(".acc") or f.endswith(".aac")]
    
    if not files:
        return 0 # 没有文件，直接返回

    print(f"发现 {len(files)} 个新文件，开始处理...")

    for filename in files:
        print(f"\n>>> 处理: {filename}")
        audio_path = os.path.join(CONFIG["SOURCE_DIR"], filename)
        base_name = os.path.splitext(filename)[0]
        wav_path = os.path.join(CONFIG["SOURCE_DIR"], f"{base_name}_TEMP.wav")
        txt_path = os.path.join(CONFIG["TRANSCRIPT_DIR"], f"{base_name}.txt")
        processed_audio_path = os.path.join(CONFIG["PROCESSED_DIR"], filename)

        try:
            if not convert_audio_to_wav(audio_path, wav_path): continue
            
            result_data = transcribe_wav(wav_path) 
            if result_data is None: continue
            
            full_text = result_data["full_text"]
            segments = result_data["segments"]

            # 过滤掉空文本的片段
            filtered_segments = []
            for seg in segments:
                if seg.get("text", "").strip():
                    filtered_segments.append(seg)

            # 【修改】调用新的带声纹保存函数
            save_transcript_with_spk(full_text, filtered_segments, txt_path)
            
            # 保存到数据库 (segments 中已包含 spk 字段)
            if not save_to_db(filename, full_text, filtered_segments): continue

            os.rename(audio_path, processed_audio_path)
            print(f"  [完成] 已归档。")
            notify_n8n("success", filename, full_text[:100])
            processed_count += 1

        except Exception as e:
            print(f"  [异常] {e}")
        finally:
            if os.path.exists(wav_path): os.remove(wav_path)
            
    return processed_count

def main():
    # 解析命令行参数
    args = parse_args()
    
    # 根据命令行参数更新配置
    update_config(args)
    
    print("--- 启动实时监控模式 (含声纹支持) ---")
    init_db()
    os.makedirs(CONFIG["TRANSCRIPT_DIR"], exist_ok=True)
    os.makedirs(CONFIG["PROCESSED_DIR"], exist_ok=True)

    # 【死循环监控核心】
    while True:
        try:
            # 运行处理逻辑
            process_one_loop()
            
            # 休息 3 秒钟再看
            time.sleep(3) 
            
        except KeyboardInterrupt:
            print("停止监控。")
            break
        except Exception as e:
            print(f"主循环发生错误: {e}")
            time.sleep(10) # 出错后多睡一会

if __name__ == "__main__":
    main()