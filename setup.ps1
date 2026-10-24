<#
  记忆宫殿 · 一键安装（Windows）

  用法（在 PowerShell 里，cd 到本文件夹）：
      powershell -ExecutionPolicy Bypass -File .\setup.ps1

  它会做四件事：
    1) 找 node
    2) npm install 装依赖
    3) 把两个补丁盖进 node_modules（onnxruntime-node -> wasm 转发层，sharp -> 空桩）
    4) 下载 bge-small-zh-v1.5 模型，然后跑一次自检

  要跳过模型下载： -SkipModel      要指定 node： -NodeExe D:\nodejs\node.exe
#>
param(
    [string]$NodeExe = "",
    [string]$PythonExe = "",
    [switch]$SkipModel
)

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
Write-Host ""
Write-Host "== 记忆宫殿 · 安装 ==" -ForegroundColor Cyan
Write-Host "目录: $here"

# ---------- 1. node ----------
if (-not $NodeExe) {
    $cands = @(
        (Join-Path $env:USERPROFILE ".dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe"),
        "C:\Program Files\nodejs\node.exe",
        "C:\Program Files (x86)\nodejs\node.exe"
    )
    foreach ($c in $cands) { if (Test-Path $c) { $NodeExe = $c; break } }
    if (-not $NodeExe) {
        $cmd = Get-Command node -ErrorAction SilentlyContinue
        if ($cmd) { $NodeExe = $cmd.Source }
    }
}
if (-not $NodeExe -or -not (Test-Path $NodeExe)) {
    Write-Host "找不到 node.exe。装一下 Node.js（>=22.13，语义层需要 node:sqlite），或者用 -NodeExe 指过去。" -ForegroundColor Red
    exit 1
}
$nodeVer = & $NodeExe --version
Write-Host "node: $NodeExe ($nodeVer)" -ForegroundColor Green
if (-not $nodeVer.StartsWith("v2") -and -not $nodeVer.StartsWith("v1")) {
    Write-Host "node 版本看着不对：$nodeVer" -ForegroundColor Yellow
}

# ---------- 2. npm install ----------
Push-Location $here
try {
    Write-Host ""
    Write-Host "== 装依赖（npm，约 1-3 分钟）==" -ForegroundColor Cyan
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npm) {
        Write-Host "找不到 npm。请装 Node.js 完整版（带 npm），或者手动在那台机器上 npm install。" -ForegroundColor Red
        exit 1
    }
    & npm install --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) {
        Write-Host "npm install 失败（exit $LASTEXITCODE）。" -ForegroundColor Red
        Write-Host "如果提示 EPERM/软链，试试换到 NTFS 盘；或改用 pnpm：pnpm install --config.node-linker=hoisted" -ForegroundColor Yellow
        exit 1
    }

    # ---------- 3. 补丁 ----------
    Write-Host ""
    Write-Host "== 打补丁 ==" -ForegroundColor Cyan
    $nm = Join-Path $here "node_modules"
    foreach ($pair in @(@("onnxruntime-node", "onnxruntime-node"), @("sharp-stub", "sharp"))) {
        $srcDir = Join-Path $here ("patches\" + $pair[0])
        $dstDir = Join-Path $nm $pair[1]
        if (Test-Path $dstDir) { Remove-Item $dstDir -Recurse -Force }
        New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
        Copy-Item (Join-Path $srcDir "*") $dstDir -Recurse -Force
        Write-Host ("  " + $pair[1] + " <- patches\" + $pair[0]) -ForegroundColor Green
    }
} finally {
    Pop-Location
}

# ---------- 4. 模型 ----------
if ($SkipModel) {
    Write-Host ""
    Write-Host "== 跳过模型下载（--SkipModel）。之后可单独跑 .\download-model.ps1 ==" -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "== 下载模型 ==" -ForegroundColor Cyan
    & (Join-Path $here "download-model.ps1")
}

# ---------- 5. 自检 ----------
if (-not $PythonExe) {
    $cands = @(
        (Join-Path $env:USERPROFILE ".dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"),
        "python"
    )
    foreach ($c in $cands) {
        if ($c -eq "python") { $PythonExe = "python"; break }
        if (Test-Path $c) { $PythonExe = $c; break }
    }
}
Write-Host ""
Write-Host "== 自检 ==" -ForegroundColor Cyan
try {
    & $PythonExe (Join-Path $here "palace.py") stats
} catch {
    Write-Host "自检没跑成（python 不在）。手动跑：python palace.py stats" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "== 完成 ==" -ForegroundColor Green
Write-Host "下一步："
Write-Host "  python palace.py save --scope user --kind fact --content `"测试一条`""
Write-Host "  python palace.py search --query 测试"
Write-Host "  # 有 node_modules + 模型时，save 会自动补 embedding"
Write-Host ""
