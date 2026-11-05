# Start the Baseball app locally against the QA Supabase project (port 8611).
# Refuses to start unless .streamlit/secrets.toml carries [qa] is_qa_project = true.
# Prints no key or URL.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$secrets = Join-Path $root ".streamlit\secrets.toml"
if (-not (Test-Path $secrets)) { Write-Host "No .streamlit\secrets.toml in $root. See docs\QA_SHARED_DRAFT_TWO_ACCOUNT.md."; exit 1 }
$check = @'
import sys, tomllib
d = tomllib.load(open(sys.argv[1], "rb"))
ok = bool((d.get("qa") or {}).get("is_qa_project") is True)
sa = d.get("suite_activity") or {}
missing = [k for k in ("supabase_url", "supabase_key", "supabase_anon_key") if not str(sa.get(k) or "").strip()]
print("QA marker:", "yes" if ok else "NO", "| missing keys:", ", ".join(missing) or "none", "| sign-in:", bool(sa.get("suite_auth_enabled")))
sys.exit(0 if ok and not missing and sa.get("suite_auth_enabled") is True else 2)
'@
$check | python - $secrets
if ($LASTEXITCODE -ne 0) { Write-Host "Refusing to start: this secrets file is not marked as the QA project (or is incomplete)."; exit 1 }
Set-Location $root
python -m streamlit run streamlit_app.py --server.port 8611 --server.headless true --browser.gatherUsageStats false
