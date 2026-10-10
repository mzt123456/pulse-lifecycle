#Requires -Version 5.1
<#
  一键启动开发环境：MySQL 容器 → 后端 FastAPI → 前端 Vite。

  用法（在任意目录打开 PowerShell）：
      powershell -ExecutionPolicy Bypass -File C:\codex_project\update_for_single\dev\start-dev.ps1

  常用参数：
      -Restart        端口已被占用时先停掉占用者再启动（例如接管旧的服务）
      -SkipDocker     不启动 MySQL 容器（库已经在跑时用）
      -SkipBackend    只起前端
      -SkipFrontend   只起后端
      -WithMcp        额外启动 MCP Server 的 HTTP 传输（127.0.0.1:8001，需要访问令牌）
      -Hidden         后台隐藏窗口运行（默认每个服务开一个可见窗口，方便看日志、Ctrl+C 停止）

  为什么要有这个脚本：开发服务必须由**你自己的终端**拉起。
  挂在别的进程（比如编辑器或助手的会话）上的服务，宿主被回收时会跟着消失，
  表现就是"用着用着就打不开了"。
#>
[CmdletBinding()]
param(
    [switch]$Restart,
    [switch]$SkipDocker,
    [switch]$SkipBackend,
    [switch]$SkipFrontend,
    [switch]$WithMcp,
    [switch]$Hidden,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
    [int]$McpPort = 8001
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Python = Join-Path $Root 'backend\.venv\Scripts\python.exe'
$Node = 'C:\Program Files\nodejs\node.exe'
$Compose = Join-Path $Root 'dev\docker-compose.dev.yml'

function Get-PortOwner([int]$Port) {
    $line = netstat -ano | Select-String 'LISTENING' | Select-String ":$Port\s" | Select-Object -First 1
    if (-not $line) { return $null }
    return [int](($line.Line -split '\s+')[-1])
}

function Stop-PortOwner([int]$Port, [string]$Name) {
    $owner = Get-PortOwner $Port
    if (-not $owner) { return }
    try {
        Stop-Process -Id $owner -Force -ErrorAction Stop
        Write-Host "  已停止占用 $Port 的旧进程（$Name，PID $owner）" -ForegroundColor DarkYellow
        Start-Sleep -Seconds 2
    } catch {
        Write-Warning "  停止 PID $owner 失败：$($_.Exception.Message)。请手动结束该进程后重试。"
    }
}

function Wait-Http([string]$Url, [int]$TimeoutSeconds = 60) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -TimeoutSec 3 -UseBasicParsing
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { return $true }
        } catch {
            Start-Sleep -Milliseconds 800
        }
    }
    return $false
}

function Start-Service-Window([string]$Title, [string]$WorkDir, [string]$Command, [string]$LogName) {
    if ($Hidden) {
        $stdout = Join-Path $LogDir "$LogName.log"
        $stderr = Join-Path $LogDir "$LogName.err.log"
        Start-Process -WindowStyle Hidden -FilePath 'powershell.exe' `
            -ArgumentList '-NoProfile', '-Command', $Command `
            -WorkingDirectory $WorkDir `
            -RedirectStandardOutput $stdout -RedirectStandardError $stderr | Out-Null
        Write-Host "  已后台启动，日志：$stdout" -ForegroundColor DarkGray
    } else {
        Start-Process -FilePath 'powershell.exe' `
            -ArgumentList '-NoExit', '-Command', "`$host.UI.RawUI.WindowTitle='$Title'; $Command" `
            -WorkingDirectory $WorkDir | Out-Null
        Write-Host "  已在新窗口启动：$Title" -ForegroundColor DarkGray
    }
}

Write-Host '== 开发环境启动 ==' -ForegroundColor Cyan

# 1) 数据库
if (-not $SkipDocker) {
    Write-Host '[1/3] MySQL 容器'
    docker compose -f $Compose up -d | Out-Host
    $healthy = $false
    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep -Seconds 3
        $status = docker inspect --format '{{.State.Health.Status}}' pulse-mysql-dev 2>$null
        if ($status -eq 'healthy') { $healthy = $true; break }
    }
    if ($healthy) { Write-Host '  容器健康（127.0.0.1:3307）' -ForegroundColor Green }
    else { Write-Warning '  容器尚未就绪，后端可能连不上库；稍后可用 -SkipDocker 重跑后端' }
} else {
    Write-Host '[1/3] MySQL 容器（已跳过）' -ForegroundColor DarkGray
}

# 2) 后端
if (-not $SkipBackend) {
    Write-Host '[2/3] 后端 FastAPI'
    if (Get-PortOwner $BackendPort) {
        if ($Restart) { Stop-PortOwner $BackendPort '后端' }
        else { Write-Host "  端口 $BackendPort 已被占用，跳过（要用新代码重启请加 -Restart）" -ForegroundColor DarkYellow }
    }
    if (-not (Get-PortOwner $BackendPort)) {
        Start-Service-Window -Title '后端 :8000' -WorkDir (Join-Path $Root 'backend') `
            -Command "& '$Python' -m uvicorn app.main:app --host 127.0.0.1 --port $BackendPort" `
            -LogName 'backend'
    }
    if (Wait-Http "http://127.0.0.1:$BackendPort/api/v1/health" 60) {
        Write-Host '  后端就绪：http://127.0.0.1:' -NoNewline; Write-Host $BackendPort -ForegroundColor Green
    } else {
        Write-Warning "  后端 60 秒内没有就绪，看一眼窗口里的报错或 $LogDir\backend.err.log"
    }
} else {
    Write-Host '[2/3] 后端（已跳过）' -ForegroundColor DarkGray
}

# 3) 前端
if (-not $SkipFrontend) {
    Write-Host '[3/3] 前端 Vite'
    if (Get-PortOwner $FrontendPort) {
        if ($Restart) { Stop-PortOwner $FrontendPort '前端' }
        else { Write-Host "  端口 $FrontendPort 已被占用，跳过（要重启请加 -Restart）" -ForegroundColor DarkYellow }
    }
    if (-not (Get-PortOwner $FrontendPort)) {
        Start-Service-Window -Title '前端 :5173' -WorkDir (Join-Path $Root 'frontend') `
            -Command "& '$Node' node_modules/vite/bin/vite.js --host 127.0.0.1 --port $FrontendPort" `
            -LogName 'frontend'
    }
    if (Wait-Http "http://127.0.0.1:$FrontendPort/" 60) {
        Write-Host '  前端就绪：http://127.0.0.1:' -NoNewline; Write-Host $FrontendPort -ForegroundColor Green
    } else {
        Write-Warning "  前端 60 秒内没有就绪，看一眼窗口里的报错或 $LogDir\frontend.err.log"
    }
} else {
    Write-Host '[3/3] 前端（已跳过）' -ForegroundColor DarkGray
}

# 4) 可选的 MCP HTTP
if ($WithMcp) {
    Write-Host '[+] MCP Server（HTTP）'
    if (Get-PortOwner $McpPort) {
        if ($Restart) { Stop-PortOwner $McpPort 'MCP' }
        else { Write-Host "  端口 $McpPort 已被占用，跳过" -ForegroundColor DarkYellow }
    }
    if (-not (Get-PortOwner $McpPort)) {
        Start-Service-Window -Title 'MCP :8001' -WorkDir (Join-Path $Root 'backend') `
            -Command "`$env:MCP_TRANSPORT='streamable-http'; `$env:PYTHONPATH='$Root\backend'; & '$Python' -m app.mcp.server" `
            -LogName 'mcp'
        Start-Sleep -Seconds 4
        Write-Host "  MCP 端点：http://127.0.0.1:$McpPort/mcp（需要访问令牌，无令牌返回 401）" -ForegroundColor Green
    }
}

Write-Host ''
Write-Host '== 就绪 ==' -ForegroundColor Cyan
Write-Host '  系统地址：http://127.0.0.1:' -NoNewline; Write-Host $FrontendPort -ForegroundColor Green
Write-Host '  接口文档：http://127.0.0.1:' -NoNewline; Write-Host "$BackendPort/docs" -ForegroundColor Green
Write-Host '  开发账号：admin / Admin@12345'
Write-Host '  停止服务：dev\stop-dev.ps1'
