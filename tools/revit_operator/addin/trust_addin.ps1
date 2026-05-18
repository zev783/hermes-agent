param(
    [Parameter(Mandatory = $true)]
    [string]$AssemblyPath,
    [string]$Subject = "CN=Hermes Revit Operator Local Code Signing"
)

$ErrorActionPreference = "Stop"
$ResolvedAssembly = (Resolve-Path -LiteralPath $AssemblyPath).Path

$cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
    Where-Object { $_.Subject -eq $Subject } |
    Select-Object -First 1

if (-not $cert) {
    $cert = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject $Subject `
        -CertStoreLocation Cert:\CurrentUser\My `
        -KeyUsage DigitalSignature `
        -KeyExportPolicy Exportable
}

$tempCert = Join-Path $env:TEMP "HermesRevitOperatorCodeSigning.cer"
Export-Certificate -Cert $cert -FilePath $tempCert | Out-Null
Import-Certificate -FilePath $tempCert -CertStoreLocation Cert:\CurrentUser\Root | Out-Null
Import-Certificate -FilePath $tempCert -CertStoreLocation Cert:\CurrentUser\TrustedPublisher | Out-Null

foreach ($storeName in @("Root", "TrustedPublisher")) {
    $store = [System.Security.Cryptography.X509Certificates.X509Store]::new(
        $storeName,
        [System.Security.Cryptography.X509Certificates.StoreLocation]::CurrentUser)
    $store.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
    try {
        $store.Add($cert)
    }
    finally {
        $store.Close()
    }
}

$signature = Set-AuthenticodeSignature -FilePath $ResolvedAssembly -Certificate $cert
if ($signature.Status -ne "Valid") {
    throw "Signing failed: $($signature.Status) $($signature.StatusMessage)"
}

Write-Host "Signed $ResolvedAssembly"
Write-Host "Certificate thumbprint: $($cert.Thumbprint)"
