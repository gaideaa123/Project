# SignalDesk Publisher

A dark, responsive Python desktop application for standards-based video rendition generation, multi-profile credential management, and scheduled publishing through TikTok's official Content Posting API.

## What it intentionally does not do

This project does not implement perceptual-hash evasion, fingerprint bypassing, engagement manipulation, stealth account isolation, or mass duplicate posting. The processing center creates normal H.264 delivery renditions for legitimate publishing workflows. Scheduling is limited to one queued post per profile in a 23-hour window.

## Features

- Polished PySide6 interface with Accounts, Processing, and Scheduler views
- Background rendering and uploads through `QThreadPool`, keeping the UI responsive
- Atomic `multi_account_registry.json` state with a rolling backup
- Access and refresh tokens stored in the operating system keychain, never in JSON
- FFmpeg H.264/AAC rendition profiles with aspect-safe scale/pad, frame-rate normalization, fast-start, and metadata removal
- TikTok creator-info validation, OAuth refresh, Direct Post initialization, and chunked upload
- Optional HTTP(S) proxy support for an approved organizational gateway
- Daily recurrence, per-profile queue isolation, logs, and recoverable failure states

## Requirements

- Python 3.11 or newer
- FFmpeg and FFprobe available on `PATH`
- A TikTok developer application with Login Kit and Content Posting API access
- User authorization for the required scopes, including `video.publish`

TikTok requires unaudited clients to publish privately. Production visibility requires TikTok app review and compliance with its UX and API policies.

## Install

### Windows

```powershell
winget install Gyan.FFmpeg
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### macOS

```bash
brew install ffmpeg python@3.11
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Ubuntu / Debian

```bash
sudo apt update && sudo apt install -y ffmpeg python3-venv libsecret-1-0
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Configure TikTok OAuth refresh

Set the developer app credentials in the process environment. Do not commit them.

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

Initial user access and refresh tokens are entered in the Accounts view and saved to Windows Credential Manager, macOS Keychain, or the Linux Secret Service through `keyring`.

## Run

```bash
python app.py
```

Application data is stored in the platform-standard user data directory. It contains `multi_account_registry.json`, its backup, and `signaldesk.log`. Tokens remain in the OS keychain.

## Official API behavior

The scheduler queries creator information before each post, selects `SELF_ONLY` when available, initializes a `FILE_UPLOAD` Direct Post, and uploads the MP4 in TikTok-compatible chunks. The app marks a job `submitted` when TikTok accepts the media. Final moderation and publication remain asynchronous on TikTok's side.

Current documentation:

- https://developers.tiktok.com/doc/content-posting-api-get-started
- https://developers.tiktok.com/doc/content-posting-api-reference-direct-post
- https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide
- https://developers.tiktok.com/doc/oauth-user-access-token-management

## Production notes

For a larger deployment, move OAuth token exchange to a controlled backend, add signed application updates, package with PyInstaller, and add API status polling. Desktop storage is suitable for a single authorized operator, not a shared server or unattended multi-user service.
