<#
.SYNOPSIS
    AI录音存档系统一键部署脚本 (Windows PowerShell)

.DESCRIPTION
    自动安装Python环境、配置依赖、初始化数据库并启动服务

.PARAMETER StartOnly
    仅启动服务，不执行完整部署

.EXAMPLE
    .\one_click_deploy.ps1
    完整部署流程

    .\one_click_deploy.ps1 -StartOnly
    仅启动服务
#>

param(
    [switch]$StartOnly
)

Write-Host "======================================================" -ForegroundColor Green
Write-Host "              AI 录音存档系统一键部署脚本             " -ForegroundColor Green
Write-Host "======================================================" -ForegroundColor Green
Write-Host ""

# ----------------- 配置区域 -----------------
$ConfigDir = "C:\AI\NAS"
$DbPath = "$ConfigDir\transcripts.db"
$WebPort = 5009
$AsrServerUrl = "http://192.168.1.111:5000/transcribe"
$WorkingDir = "d:\AI\nas"
# -------------------------------------------

# 检查PowerShell版本
if ($PSVersionTable.PSVersion.Major -lt 5) {
    Write-Host "错误: 请使用PowerShell 5.0或更高版本运行此脚本" -ForegroundColor Red
    exit 1
}

# 检查管理员权限
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
$isAdmin = $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin -and -not $StartOnly) {
    Write-Host "警告: 某些操作需要管理员权限，建议以管理员身份运行脚本" -ForegroundColor Yellow
    Read-Host -Prompt "按Enter键继续..."
}

function Install-Python {
    Write-Host "正在检查Python环境..." -ForegroundColor Yellow
    
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $pythonVersion = python --version
        Write-Host "检测到Python: $pythonVersion" -ForegroundColor Green
        return $true
    }
    
    if (Get-Command python3 -ErrorAction SilentlyContinue) {
        $pythonVersion = python3 --version
        Write-Host "检测到Python: $pythonVersion" -ForegroundColor Green
        return $true
    }
    
    Write-Host "未检测到Python，正在下载并安装..." -ForegroundColor Yellow
    
    # 下载Python 3.11安装包
    $pythonInstallerUrl = "https://www.python.org/ftp/python/3.11.4/python-3.11.4-amd64.exe"
    $pythonInstallerPath = "$env:TEMP\python-3.11.4-amd64.exe"
    
    try {
        Invoke-WebRequest -Uri $pythonInstallerUrl -OutFile $pythonInstallerPath -UseBasicParsing
        Write-Host "Python安装包下载完成" -ForegroundColor Green
        
        # 静默安装Python
        $installArgs = @(
            "/quiet",
            "InstallAllUsers=1",
            "PrependPath=1",
            "IncludeTest=0",
            "IncludePip=1"
        )
        
        $process = Start-Process -FilePath $pythonInstallerPath -ArgumentList $installArgs -Wait -PassThru
        if ($process.ExitCode -eq 0) {
            Write-Host "Python安装成功" -ForegroundColor Green
            Remove-Item $pythonInstallerPath
            return $true
        } else {
            Write-Host "Python安装失败，退出码: $($process.ExitCode)" -ForegroundColor Red
            Remove-Item $pythonInstallerPath
            return $false
        }
    } catch {
        Write-Host "Python下载失败: $($_.Exception.Message)" -ForegroundColor Red
        return $false
    }
}

function Install-Dependencies {
    Write-Host "正在安装Python依赖包..." -ForegroundColor Yellow
    
    # 安装或升级pip
    python -m pip install --upgrade pip -q
    
    # 安装所需包
    python -m pip install flask requests -q
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "依赖包安装完成" -ForegroundColor Green
        return $true
    } else {
        Write-Host "依赖包安装失败" -ForegroundColor Red
        return $false
    }
}

function Configure-App {
    Write-Host "正在配置应用程序..." -ForegroundColor Yellow
    
    # 创建配置目录
    if (-not (Test-Path $ConfigDir)) {
        New-Item -Path $ConfigDir -ItemType Directory -Force | Out-Null
        Write-Host "创建配置目录: $ConfigDir" -ForegroundColor Green
    }
    
    Write-Host "应用程序配置完成" -ForegroundColor Green
    return $true
}

function Initialize-Database {
    Write-Host "正在初始化数据库..." -ForegroundColor Yellow
    
    # 确保配置目录存在
    if (-not (Test-Path $ConfigDir)) {
        New-Item -Path $ConfigDir -ItemType Directory -Force | Out-Null
    }
    
    $sqlScript = @'
import sqlite3
import os

db_path = "$DbPath"

# 创建目录
os.makedirs(os.path.dirname(db_path), exist_ok=True)

# 连接数据库
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 创建表
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
print("数据库初始化完成")
'@ -replace '\$DbPath', $DbPath
    
    python -c $sqlScript 2>&1
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "数据库初始化完成" -ForegroundColor Green
        return $true
    } else {
        Write-Host "数据库初始化失败" -ForegroundColor Red
        return $false
    }
}

function Start-Services {
    Write-Host "正在启动服务..." -ForegroundColor Yellow
    
    # 切换到工作目录
    Set-Location -Path $WorkingDir
    
    # 检查并启动Web服务
    if (-not (Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object {$_.CommandLine -like "*web_viewer.py*"})) {
        Start-Process -FilePath "python" -ArgumentList "web_viewer.py" -WindowStyle Normal -WorkingDirectory $WorkingDir
        Write-Host "Web服务已启动" -ForegroundColor Green
    } else {
        Write-Host "Web服务已经在运行中" -ForegroundColor Yellow
    }
    
    # 检查并启动转录服务
    if (-not (Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object {$_.CommandLine -like "*transcribe.py*"})) {
        Start-Process -FilePath "python" -ArgumentList "transcribe.py" -WindowStyle Normal -WorkingDirectory $WorkingDir
        Write-Host "转录服务已启动" -ForegroundColor Green
    } else {
        Write-Host "转录服务已经在运行中" -ForegroundColor Yellow
    }
    
    return $true
}

function Show-Result {
    Write-Host "" -ForegroundColor White
    Write-Host "======================================================" -ForegroundColor Green
    Write-Host "                   部署完成！${'0x2705' -as [char]}                " -ForegroundColor Green
    Write-Host "======================================================" -ForegroundColor Green
    Write-Host "" -ForegroundColor White
    
    $ipAddress = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias "Wi-Fi" | Select-Object -First 1).IPAddress
    if (-not $ipAddress) {
        $ipAddress = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -ne "127.0.0.1"} | Select-Object -First 1).IPAddress
    }
    
    Write-Host "Web 界面地址: http://$ipAddress`:$WebPort" -ForegroundColor Cyan
    Write-Host "配置目录: $ConfigDir" -ForegroundColor Cyan
    Write-Host "数据库路径: $DbPath" -ForegroundColor Cyan
    Write-Host "工作目录: $WorkingDir" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "服务已启动，您可以开始使用了！" -ForegroundColor Yellow
    Write-Host "按任意键关闭窗口..." -ForegroundColor White
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
}

# 主流程
if (-not $StartOnly) {
    Install-Python
    Install-Dependencies
    Configure-App
    Initialize-Database
}

Start-Services
Show-Result