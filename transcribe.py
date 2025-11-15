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
import re

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

# 支持的音频扩展名
SUPPORTED_EXTENSIONS = ('.m4a', '.acc', '.aac', '.mp3', '.wav', '.ogg', '.flac')

def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='音频转录脚本')
    parser.add_argument('--source-path', type=str, help='源音频文件路径')
    return parser.parse_args()

def update_config(args):
    """根据命令行参数更新配置"""
    global CONFIG
    if args.source_path:
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

def clean_sensevoice_tags(text):
    """清洗 SenseVoice 可能残留的特殊标签"""
    if not text: return ""
    # 移除 <|zh|>, <|happy|>, <|speech|> 等标签
    cleaned = re.sub(r'<\|.*?\|>', '', text)
    return cleaned.strip()

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
    payload = {
        "status": status, 
        "filename": filename, 
        "details": details, 
        "timestamp": datetime.datetime.now().isoformat()
    }
    try:
        requests.post(CONFIG["N8N_WEBHOOK_URL"], json=payload, timeout=5)
    except:
        pass

def convert_audio_to_wav(audio_path, wav_path):
    """使用 ffmpeg 转换音频 (增强版)"""
    FFMPEG_PATH = "/usr/local/bin/ffmpeg"
    
    # 优化参数：
    # -map 0:a : 只提取第一个音频流 (防止 m4a 封面图被当成视频流报错)
    # -ac 1    : 强制转为单声道 (ASR 模型通常需要单声道)
    command = [
        FFMPEG_PATH, 
        '-y', 
        '-i', audio_path, 
        '-vn',         # 禁用视频
        '-map', '0:a', # 明确映射音频流
        '-ar', '16000', 
        '-ac', '1',    # 强制单声道
        '-c:a', 'pcm_s16le', 
        wav_path
    ]
    
    try:
        # capture_output=True 用于捕获错误日志，check=True 遇到错误抛出异常
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return True
    except subprocess.CalledProcessError as e:
        # 打印 stderr 以便调试 ffmpeg 错误
        error_msg = e.stderr.decode().strip() if e.stderr else "Unknown error"
        print(f"  [Convert Error] ffmpeg 转换失败: {error_msg[:200]}...") # 只打印前200字符
        return False
    except Exception as e:
        print(f"  [Convert Error] {e}")
        return False

def save_transcript_with_spk(full_text, segments, txt_path):
    """保存带有声纹和时间戳的 TXT 文件"""
    try:
        content_lines = []
        
        # 1. 先写入全文摘要
        clean_full_text = clean_sensevoice_tags(full_text)
        content_lines.append(f"=== 全文摘要 ===\n{clean_full_text}\n")
        content_lines.append("=== 对话记录 (按说话人) ===")
        
        # 2. 写入带声纹的分段对话
        for seg in segments:
            start_str = format_time(seg.get('start', 0))
            
            spk_raw = seg.get('spk')
            if spk_raw is None:
                spk_label = "Unknown"
            elif isinstance(spk_raw, int):
                spk_label = f"Speaker {spk_raw}"
            else:
                spk_label = str(spk_raw)
            
            text = clean_sensevoice_tags(seg.get('text', ''))
            if not text.strip(): continue

            # 格式: [00:05:12] [爸爸]: 今天的饭很好吃
            line = f"[{start_str}] [{spk_label}]: {text}"
            content_lines.append(line)
            
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write("\n\n".join(content_lines))
            
        return True
    except Exception as e:
        print(f"  [Save TXT Error] {e}")
        return False

def transcribe_wav(wav_path):
    url = CONFIG["ASR_HTTP_URL"]
    max_retries = 3 # 最大重试次数
    
    for attempt in range(max_retries):
        try:
            with open(wav_path, 'rb') as f:
                files = {'audio_file': (os.path.basename(wav_path), f, 'audio/wav')}
                
                if attempt > 0:
                    print(f"  网络波动，正在重试 ({attempt+1}/{max_retries})...")
                else:
                    print(f"  正在上传并等待转录结果 (超时: 3600s)...")
                
                response = requests.post(url, files=files, timeout=3600) 
            
            response.raise_for_status() 
            data = response.json()
            
            if "error" in data:
                print(f"  [Server Error] {data['error']}")
                return None
                
            if data.get("full_text") is not None:
                return data
            else:
                print(f"  [API Error] {data}")
                return None

        except requests.exceptions.Timeout:
            print(f"  [Timeout] 请求超时，服务端仍在处理。")
            return None # 超时不重试，避免重复提交大文件
        except requests.exceptions.ConnectionError:
            print(f"  [Connection Error] 无法连接服务端，等待 5秒 后重试...")
            time.sleep(5)
        except Exception as e:
            print(f"  [Request Error] {e}")
            return None
            
    print("  [Failed] 重试次数耗尽，跳过此文件")
    return None

def process_one_loop():
    """执行一次扫描处理"""
    processed_count = 0
    
    if not os.path.exists(CONFIG["SOURCE_DIR"]):
        print(f"源目录不存在: {CONFIG['SOURCE_DIR']}")
        return 0

    files = [f for f in os.listdir(CONFIG["SOURCE_DIR"]) 
             if f.lower().endswith(SUPPORTED_EXTENSIONS)]
    
    if not files:
        return 0 

    print(f"发现 {len(files)} 个新文件，开始处理...")

    for filename in files:
        print(f"\n>>> 处理: {filename}")
        audio_path = os.path.join(CONFIG["SOURCE_DIR"], filename)
        base_name = os.path.splitext(filename)[0]
        
        wav_path = os.path.join(CONFIG["SOURCE_DIR"], f"{base_name}_TEMP.wav")
        txt_path = os.path.join(CONFIG["TRANSCRIPT_DIR"], f"{base_name}.txt")
        processed_audio_path = os.path.join(CONFIG["PROCESSED_DIR"], filename)

        try:
            # 1. 转换
            if not convert_audio_to_wav(audio_path, wav_path): 
                print("  转换失败，跳过")
                continue
            
            # 2. 转录
            result_data = transcribe_wav(wav_path) 
            if result_data is None: 
                print("  转录失败，跳过")
                continue
            
            full_text = result_data["full_text"]
            segments = result_data["segments"]

            # 3. 过滤
            filtered_segments = []
            for seg in segments:
                if seg.get("text", "").strip():
                    filtered_segments.append(seg)

            # 4. 保存
            save_transcript_with_spk(full_text, filtered_segments, txt_path)
            
            if not save_to_db(filename, full_text, filtered_segments): 
                print("  数据库保存失败，跳过归档")
                continue

            # 5. 归档
            if os.path.exists(processed_audio_path):
                os.remove(processed_audio_path)
            os.rename(audio_path, processed_audio_path)
            
            print(f"  [完成] 已归档 -> {processed_audio_path}")
            
            notify_n8n("success", filename, full_text[:100])
            processed_count += 1

        except Exception as e:
            print(f"  [异常] {e}")
        finally:
            if os.path.exists(wav_path): 
                try: os.remove(wav_path)
                except: pass
            
    return processed_count

def main():
    args = parse_args()
    update_config(args)
    
    print("--- 启动实时监控模式 (SenseVoice 适配版) ---")
    print(f"监控目录: {CONFIG['SOURCE_DIR']}")
    
    init_db()
    os.makedirs(CONFIG["TRANSCRIPT_DIR"], exist_ok=True)
    os.makedirs(CONFIG["PROCESSED_DIR"], exist_ok=True)

    while True:
        try:
            process_one_loop()
            time.sleep(3) 
        except KeyboardInterrupt:
            print("停止监控。")
            break
        except Exception as e:
            print(f"主循环发生错误: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()