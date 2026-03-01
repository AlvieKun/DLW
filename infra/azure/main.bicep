// ─────────────────────────────────────────────────────────────────
// Learning Navigator AI — Azure Infrastructure (Bicep)
// Deploy: az deployment group create -g <rg> --template-file main.bicep
// ─────────────────────────────────────────────────────────────────

@description('Base name for all resources (lowercase, no spaces)')
param baseName string = 'learningnav'

@description('Azure region for all resources')
param location string = resourceGroup().location

@description('Environment tag (dev / staging / production)')
@allowed(['dev', 'staging', 'production'])
param environment string = 'dev'

// ── Variables ─────────────────────────────────────────────────────
var uniqueSuffix = uniqueString(resourceGroup().id)
var storageAccountName = '${baseName}${uniqueSuffix}'
var functionAppName = '${baseName}-func-${environment}'
var appServicePlanName = '${baseName}-plan-${environment}'
var appInsightsName = '${baseName}-insights-${environment}'
var searchServiceName = '${baseName}-search-${environment}'

// ── Storage Account ───────────────────────────────────────────────
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: take(storageAccountName, 24)  // max 24 chars
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
  }
  tags: {
    environment: environment
    project: 'learning-navigator'
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: storageAccount
  name: 'default'
}

resource container 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: 'learning-navigator'
  properties: {
    publicAccess: 'None'
  }
}

// ── Application Insights ──────────────────────────────────────────
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    RetentionInDays: 90
  }
  tags: {
    environment: environment
    project: 'learning-navigator'
  }
}

// ── App Service Plan (Consumption) ────────────────────────────────
resource appServicePlan 'Microsoft.Web/serverfarms@2022-09-01' = {
  name: appServicePlanName
  location: location
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
  kind: 'functionapp'
  properties: {
    reserved: true  // Linux
  }
  tags: {
    environment: environment
    project: 'learning-navigator'
  }
}

// ── Function App ──────────────────────────────────────────────────
resource functionApp 'Microsoft.Web/sites@2022-09-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    siteConfig: {
      pythonVersion: '3.10'
      linuxFxVersion: 'Python|3.10'
      appSettings: [
        {
          name: 'AzureWebJobsStorage'
          value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=core.windows.net'
        }
        {
          name: 'FUNCTIONS_WORKER_RUNTIME'
          value: 'python'
        }
        {
          name: 'FUNCTIONS_EXTENSION_VERSION'
          value: '~4'
        }
        {
          name: 'APPINSIGHTS_INSTRUMENTATIONKEY'
          value: appInsights.properties.InstrumentationKey
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsights.properties.ConnectionString
        }
        {
          name: 'PYTHON_ISOLATE_WORKER_DEPENDENCIES'
          value: '1'
        }
        // Learning Navigator settings
        {
          name: 'LN_ENVIRONMENT'
          value: environment
        }
        {
          name: 'LN_STORAGE_BACKEND'
          value: 'azure_blob'
        }
        {
          name: 'LN_AZURE_STORAGE_CONNECTION_STRING'
          value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=core.windows.net'
        }
        {
          name: 'LN_AZURE_STORAGE_CONTAINER'
          value: 'learning-navigator'
        }
        {
          name: 'LN_SEARCH_BACKEND'
          value: 'azure_ai_search'
        }
        {
          name: 'LN_AZURE_SEARCH_ENDPOINT'
          value: 'https://${searchServiceName}.search.windows.net'
        }
        {
          name: 'LN_AZURE_SEARCH_INDEX'
          value: 'learning-navigator-index'
        }
        {
          name: 'LN_ADAPTIVE_ROUTING_ENABLED'
          value: 'true'
        }
        {
          name: 'LN_LOG_FORMAT'
          value: 'json'
        }
      ]
    }
  }
  tags: {
    environment: environment
    project: 'learning-navigator'
  }
}

// ── Azure AI Search ───────────────────────────────────────────────
resource searchService 'Microsoft.Search/searchServices@2023-11-01' = {
  name: searchServiceName
  location: location
  sku: {
    name: 'basic'
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
  }
  tags: {
    environment: environment
    project: 'learning-navigator'
  }
}

// ── Outputs ───────────────────────────────────────────────────────
output functionAppName string = functionApp.name
output functionAppUrl string = 'https://${functionApp.properties.defaultHostName}'
output storageAccountName string = storageAccount.name
output searchServiceName string = searchService.name
output appInsightsName string = appInsights.name
