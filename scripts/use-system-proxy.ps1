# Process-local proxy for official dependency downloads; never changes Windows settings.
if (-not $env:HTTPS_PROXY) {
    $settings=Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -ErrorAction SilentlyContinue
    if ($settings.ProxyEnable -eq 1) {
        $downloadProxy=$settings.ProxyServer
        if ($downloadProxy -match 'https=([^;]+)') {$downloadProxy=$Matches[1]}
        elseif ($downloadProxy -match 'http=([^;]+)') {$downloadProxy=$Matches[1]}
        if ($downloadProxy -and $downloadProxy -notmatch ';') {
            if ($downloadProxy -notmatch '^https?://') {$downloadProxy='http://'+$downloadProxy}
            $env:HTTPS_PROXY=$downloadProxy
        }
    }
}
if ($env:HTTPS_PROXY) {
    $env:ELECTRON_GET_USE_PROXY='1'
    $env:GLOBAL_AGENT_HTTP_PROXY=$env:HTTPS_PROXY
    $env:GLOBAL_AGENT_HTTPS_PROXY=$env:HTTPS_PROXY
    $env:NO_PROXY='127.0.0.1,localhost'
    $env:GLOBAL_AGENT_NO_PROXY='127.0.0.1,localhost'
}
