# Start the Baseball app locally against the QA Supabase project (port 8611).
# Refuses to start unless scripts/qa/qa_guard.py accepts .streamlit/secrets.toml
# ([qa] is_qa_project = true, project_ref matching supabase_url). Prints no key or URL.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root
python scripts\qa\qa_guard.py
if ($LASTEXITCODE -ne 0) { Write-Host "Refusing to start. See docs\QA_SHARED_DRAFT_TWO_ACCOUNT.md."; exit 1 }
# Like Streamlit Cloud: never load the sibling Command Center repo's suite_storage module.
$env:SUITE_STORAGE_ISOLATED = "1"
python -m streamlit run streamlit_app.py --server.port 8611 --server.address 127.0.0.1 --server.headless true --browser.gatherUsageStats false
