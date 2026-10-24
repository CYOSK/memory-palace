<#
  下载 bge-small-zh-v1.5 模型（只下量化版，约 23MB）
  默认走 hf-mirror.com —— 国内可直连 huggingface.co 的话也可以 -Mirror https://huggingface.co
#>
param(
    [string]$Dest   = (Join-Path $PSScriptRoot "models"),
    [string]$Mirror = "https://hf-mirror.com"
)

$repo   = "Xenova/bge-small-zh-v1.5"
$files  = @(
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "onnx/model_quantized.onnx"
)
$target = Join-Path $Dest $repo
New-Item -ItemType Directory -Force -Path (Join-Path $target "onnx") | Out-Null

foreach ($f in $files) {
    $out = Join-Path $target $f
    if (Test-Path $out) {
        Write-Host ("  已有  " + $f) -ForegroundColor DarkGray
        continue
    }
    $url = "$Mirror/$repo/resolve/main/$f"
    Write-Host ("  下载  " + $f + "  <- " + $url)
    try {
        Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing -TimeoutSec 600
    } catch {
        Write-Warning ("  失败: " + $f + "  " + $_.Exception.Message)
    }
}

$sz = 0
if (Test-Path $target) { $sz = (Get-ChildItem $target -Recurse -File | Measure-Object Length -Sum).Sum }
Write-Host ("模型目录: " + $target + "   共 " + [math]::Round($sz/1MB,1) + " MB") -ForegroundColor Green
