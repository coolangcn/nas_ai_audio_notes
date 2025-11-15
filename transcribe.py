#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import subprocess
import requests
import json
import datetime
import sqlite3
import time # <-- 必须导入 time

# --- 配置 ---
CONFIG = {
    "ASR_HTTP_URL": "http://192.168.1.111:5000/transcribe",
    "SOURCE_DIR": "/volume2/download/records/Sony-2",
    "TRANSCRIPT_DIR": "/volume2/download/records/Sony-2/transcripts",
    "PROCESSED_DIR": "/volume2/download/records/Sony-2/processed",
    "N8N_WEBHOOK_URL": "https://n8n.moco.fun/webhook/bea45d47-d1fc-498e-bf69-d48dc079f04a",
    "DB_PATH": "/volume2/download/records/Sony-2/transcripts.db" 
}
# ---------------------------------------------

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

def convert_m4a_to_wav(m4a_path, wav_path):
    FFMPEG_PATH = "/usr/local/bin/ffmpeg"
    command = [FFMPEG_PATH, '-i', m4a_path, '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', wav_path, '-y']
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return True
    except Exception as e:
        print(f"  [Convert Error] {e}")
        return False

def save_transcript(text, txt_path):
    try:
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(text)
        return True
    except:
        return False

def transcribe_wav(wav_path):
    url = CONFIG["ASR_HTTP_URL"]
    try:
        with open(wav_path, 'rb') as f:
            files = {'audio_file': (os.path.basename(wav_path), f, 'audio/wav')}
            response = requests.post(url, files=files, timeout=600) 
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
    # 检查目录里有没有 .m4a 文件
    files = [f for f in os.listdir(CONFIG["SOURCE_DIR"]) if f.endswith(".m4a")]
    
    if not files:
        return 0 # 没有文件，直接返回

    print(f"发现 {len(files)} 个新文件，开始处理...")

    for filename in files:
        print(f"\n>>> 处理: {filename}")
        m4a_path = os.path.join(CONFIG["SOURCE_DIR"], filename)
        base_name = os.path.splitext(filename)[0]
        wav_path = os.path.join(CONFIG["SOURCE_DIR"], f"{base_name}_TEMP.wav")
        txt_path = os.path.join(CONFIG["TRANSCRIPT_DIR"], f"{base_name}.txt")
        processed_m4a_path = os.path.join(CONFIG["PROCESSED_DIR"], filename)

        try:
            if not convert_m4a_to_wav(m4a_path, wav_path): continue
            
            result_data = transcribe_wav(wav_path) 
            if result_data is None: continue
            
            full_text = result_data["full_text"]
            segments = result_data["segments"]

            # 过滤掉空文本的片段
            filtered_segments = []
            for seg in segments:
                if seg.get("text", "").strip():
                    filtered_segments.append(seg)

            save_transcript(full_text, txt_path)
            if not save_to_db(filename, full_text, filtered_segments): continue

            os.rename(m4a_path, processed_m4a_path)
            print(f"  [完成] 已归档。")
            notify_n8n("success", filename, full_text[:100])
            processed_count += 1

        except Exception as e:
            print(f"  [异常] {e}")
        finally:
            if os.path.exists(wav_path): os.remove(wav_path)
            
    return processed_count

def main():
    print("--- 启动实时监控模式 (Real-time Monitor) ---")
    init_db()
    os.makedirs(CONFIG["TRANSCRIPT_DIR"], exist_ok=True)
    os.makedirs(CONFIG["PROCESSED_DIR"], exist_ok=True)

    # 【死循环监控核心】
    while True:
        try:
            # 运行处理逻辑
            process_one_loop()
            
            # 休息 3 秒钟再看 (您可以把这个数字改得更小)
            time.sleep(3) 
            
        except KeyboardInterrupt:
            print("停止监控。")
            break
        except Exception as e:
            print(f"主循环发生错误: {e}")
            time.sleep(10) # 出错后多睡一会

if __name__ == "__main__":
    main()