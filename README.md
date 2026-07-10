# SignalDesk Publisher

A production-oriented Python desktop dashboard for legitimate agency content delivery. It creates standard H.264 renditions, stores channel credentials in the OS keychain, and schedules posts through TikTok's documented Content Posting API.

The project intentionally excludes fingerprint evasion, stealth account isolation, engagement manipulation, and mass duplicate posting.

## Capabilities

- Dark PySide6 dashboard with Profile Manager, Asset Processing, and Deployment Queue tabs
- Real `threading.Thread` workers for encoding and network requests
- Batch output selection with 1 to 100 renditions
- H.264 High Profile, CRF 20 to 23, standard resolutions, light unsharp, optional micro grain, AAC, 44.1/48 kHz, EBU-style loudness normalization, fast-start container layout
- Atomic `pipeline_registry.json` with backup recovery
- Tokens stored in Windows Credential Manager, macOS Keychain, or Linux Secret Service
- TikTok OAuth refresh, creator-info query, Direct Post initialization, and official chunked upload
- Deterministic 23-hour guard checked both when a post is queued and immediately before upload
- Daily recurrence that always advances beyond the protected window

## Requirements

- Python 3.11+
- FFmpeg and FFprobe on `PATH`
- A TikTok developer application with Login Kit and Content Posting API access
- User authorization for the required scopes, including `video.publish`

Unaudited TikTok clients are restricted to private posts. Public visibility requires TikTok review and compliance with its UX and API policies.

## Install

Windows:

```powershell
winget install Gyan.FFmpeg
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

macOS:

```bash
brew install ffmpeg python@3.11
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Ubuntu or Debian:

```bash
sudo apt update
sudo apt install -y ffmpeg python3-venv libsecret-1-0
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Configure and run

Do not commit app credentials. Supply them through the environment:

```bash
export TIKTOK_CLIENT_KEY="your-client-key"
export TIKTOK_CLIENT_SECRET="your-client-secret"
python app.py
```

PowerShell:

```powershell
$env:TIKTOK_CLIENT_KEY="your-client-key"
$env:TIKTOK_CLIENT_SECRET="your-client-secret"
python app.py
```

Initial user access and refresh tokens are entered in Profile Manager and saved through `keyring`.

## State and rate-limit behavior

Application data uses the platform-standard user data directory. `pipeline_registry.json` stores profiles, queue state, token expiry, and the last accepted submission timestamp. It does not store tokens.

The guard rejects a new queue item when another queued or running post for the same profile is within 23 hours. Immediately before every upload, `claim_due_job()` atomically rechecks the profile's `last_post_at`. When TikTok accepts a submission, `complete_job()` atomically records that timestamp. This closes the usual race between the scheduler and worker thread.

## Official references

- https://developers.tiktok.com/doc/content-posting-api-get-started
- https://developers.tiktok.com/doc/content-posting-api-reference-direct-post
- https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide
- https://developers.tiktok.com/doc/oauth-user-access-token-management

## Production hardening

For shared or unattended deployments, move OAuth exchange to a controlled backend, add signed updates, package with PyInstaller, poll publication status, and add integration tests against a sandbox account. This desktop build is designed for one authorized agency operator.
