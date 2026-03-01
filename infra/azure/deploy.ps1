# ─────────────────────────────────────────────────────────────────
# Learning Navigator AI — Azure Deployment Script (PowerShell)
# ─────────────────────────────────────────────────────────────────
#
# Usage:
#   .\deploy.ps1 -ResourceGroup "rg-learning-nav" -Environment "dev"
#
# Prerequisites:
#   - Azure CLI installed (az --version)
#   - Logged in (az login)
#   - Bicep CLI available (az bicep install)
# ─────────────────────────────────────────────────────────────────

param(
    [Parameter(Mandatory = $true)]
    [string]$ResourceGroup,

    [Parameter()]
    [ValidateSet("dev", "staging", "production")]
    [string]$Environment = "dev",

    [Parameter()]
    [string]$Location = "eastus2",

    [Parameter()]
    [string]$BaseName = "learningnav"
)

$ErrorActionPreference = "Stop"

Write-Host "╔══════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  Learning Navigator AI — Azure Deployment    ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: Ensure resource group ─────────────────────────────────
Write-Host "[1/4] Ensuring resource group '$ResourceGroup' exists..." -ForegroundColor Yellow
$rgExists = az group exists --name $ResourceGroup | ConvertFrom-Json
if (-not $rgExists) {
    Write-Host "  Creating resource group in $Location..."
    az group create --name $ResourceGroup --location $Location --output none
}
Write-Host "  ✓ Resource group ready" -ForegroundColor Green

# ── Step 2: Deploy Bicep template ─────────────────────────────────
Write-Host "[2/4] Deploying Bicep infrastructure..." -ForegroundColor Yellow
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$templateFile = Join-Path $scriptDir "main.bicep"

$deployResult = az deployment group create `
    --resource-group $ResourceGroup `
    --template-file $templateFile `
    --parameters baseName=$BaseName environment=$Environment location=$Location `
    --output json | ConvertFrom-Json

$functionAppName = $deployResult.properties.outputs.functionAppName.value
$functionAppUrl = $deployResult.properties.outputs.functionAppUrl.value
$storageAccountName = $deployResult.properties.outputs.storageAccountName.value
$searchServiceName = $deployResult.properties.outputs.searchServiceName.value

Write-Host "  ✓ Infrastructure deployed" -ForegroundColor Green
Write-Host "    Function App:  $functionAppName"
Write-Host "    Storage:       $storageAccountName"
Write-Host "    Search:        $searchServiceName"

# ── Step 3: Set Search API key app setting ─────────────────────────
Write-Host "[3/4] Configuring Azure AI Search key..." -ForegroundColor Yellow
$searchKey = az search admin-key show `
    --resource-group $ResourceGroup `
    --service-name $searchServiceName `
    --query primaryKey --output tsv

az functionapp config appsettings set `
    --resource-group $ResourceGroup `
    --name $functionAppName `
    --settings "LN_AZURE_SEARCH_KEY=$searchKey" `
    --output none

Write-Host "  ✓ Search key configured" -ForegroundColor Green

# ── Step 4: Deploy function code ──────────────────────────────────
Write-Host "[4/4] Deploying function app code..." -ForegroundColor Yellow
$projectRoot = Resolve-Path (Join-Path $scriptDir "../..")
Push-Location $projectRoot
try {
    func azure functionapp publish $functionAppName --python
} finally {
    Pop-Location
}
Write-Host "  ✓ Code deployed" -ForegroundColor Green

# ── Summary ────────────────────────────────────────────────────────
Write-Host ""
Write-Host "╔══════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║  Deployment Complete!                        ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Write-Host "  Health endpoint: $functionAppUrl/api/health"
Write-Host "  Event endpoint:  $functionAppUrl/api/v1/events"
Write-Host ""
Write-Host "  Test with:"
Write-Host "    curl $functionAppUrl/api/health"
Write-Host ""
