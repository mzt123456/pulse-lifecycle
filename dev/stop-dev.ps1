#Requires -Version 5.1
<#
  停止开发环境：按端口结束前端、后端与 MCP 进程；可选停掉 MySQL 容器。

  用法：
      powershell -ExecutionPolicy Bypass -File C:\codex_project\update_for_single\dev\stop-dev.ps1
      powershell -ExecutionPolicy Bypass -File ...\stop-dev.ps1 -WithDocker

  只按端口结束进程，不动别的项目；加 -WithDocker 才会停数据库容器（数据保留在 dev\mysql-data）。
#>
[CmdletBinding()]
param(
    [switch]$WithDocker,
    # 逗号分隔的端口列表；用字符串是因为 powershell -File 传数组参数会被拼成一个值
    [string]$Ports = '5173,8000,8001'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot

$portList = $Ports -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ } | ForEach-Object { [int]$_ }

function Get-PortOwner([int]$Port) {
    $line = netstat -ano | Select-String 'LISTENING' | Select-String ":$Port\s" | Select-Object -First 1
    if (-not $line) { return $null }
    return [int](($line.Line -split '\s+')[-1])
}

$names = @{ 5173 = '前端'; 8000 = '后端'; 8001 = 'MCP' }

Write-Host '== 停止开发环境 ==' -ForegroundColor Cyan
foreach ($port in $portList) {
    $owner = Get-PortOwner $port
    $label = if ($names.ContainsKey($port)) { $names[$port] } else { '服务' }
    if (-not $owner) {
        Write-Host "  $port（$label）：没有在跑" -ForegroundColor DarkGray
        continue
    }
    try {
        Stop-Process -Id $owner -Force -ErrorAction Stop
        Write-Host "  $port（$label）：已停止 PID $owner" -ForegroundColor Green
    } catch {
        Write-Warning "  $port（$label）：停止 PID $owner 失败，$($_.Exception.Message)"
    }
}

if ($WithDocker) {
    Write-Host '  停止 MySQL 容器（数据保留在 dev\mysql-data）'
    docker compose -f (Join-Path $Root 'dev\docker-compose.dev.yml') down | Out-Host
} else {
    Write-Host '  MySQL 容器未动（需要一起停就加 -WithDocker）' -ForegroundColor DarkGray
}
