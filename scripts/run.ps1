# Start the watcher in the foreground. Ctrl+C stops it.
$root = Split-Path -Parent $PSScriptRoot
python (Join-Path $root "watch.py") @args
