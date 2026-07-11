# SignalDesk Publisher

A production-oriented Python desktop dashboard for legitimate agency content delivery. It creates standard H.264 renditions, stores channel credentials in the OS keychain, and supports the direct `app_tr.py` Azure GPT + visible TikTok Studio workflow.

## Supported app_tr workflow

1. Run `python app_tr.py`.
2. Add profiles in the intended order.
3. Select one source video and create the desired number of variants.
4. Outputs are named `1.mp4`, `2.mp4`, `3.mp4`, and so on.
5. `1.mp4` is assigned to the first profile, `2.mp4` to the second profile, and so on.
6. Azure GPT creates a caption for the current profile.
7. The visible web uploader completes that profile, then advances to the next one.

The pipeline deliberately stays sequential so browser sessions, profile cookies, captions, and confirmation state cannot cross between accounts.

## Requirements

- Python 3.11+
- FFmpeg and FFprobe on `PATH`
- Google Chrome or Playwright Chromium
- An Azure OpenAI chat-completions deployment
- Authorized TikTok accounts

## Install

Windows:

```powershell
winget install Gyan.FFmpeg
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
python app_tr.py
```

macOS:

```bash
brew install ffmpeg python@3.11
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
python app_tr.py
```

Ubuntu or Debian:

```bash
sudo apt update
sudo apt install -y ffmpeg python3-venv libsecret-1-0
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
python app_tr.py
```

## Security and state

Azure keys, TikTok sessions, and profile credentials are stored through the operating-system keychain. `sitecustomize.py` is intentionally side-effect free: Azure requests are made explicitly by `app_tr.py`, and no global HTTP or Qt monkey patch is used.

Application data and diagnostics use the platform-standard user-data directory. Diagnostics can include screenshots or page HTML, so treat that directory as sensitive and remove old captures when they are no longer needed.

## Publishing reality

The uploader verifies local media quality, keeps content checks enabled, and refuses to force publishing while TikTok reports an incomplete copyright check. These controls remove known false-success paths, but no client code can guarantee views. If a confirmed post remains at zero, check TikTok Studio account status, post visibility, processing state, and For You feed eligibility.

## Tests

```bash
python runtime_contract_smoke.py
python smoke_test.py
python preflight_smoke.py
python media_qa_smoke.py
python antibot_resilience_smoke.py
python antibot_sandbox_smoke.py
```

The runtime contract test locks the supported behavior: numbered variants, ordered profile assignment, explicit Azure caption generation, sequential web upload, and restoration of profile-specific wrappers after errors.
