# SignalDesk Agency Console

A production-oriented PySide6 desktop dashboard for legitimate agency content operations: official channel credentials, standards-based H.264 rendition batches, and scheduled TikTok delivery through the documented Content Posting API.

## Safety and compliance

SignalDesk does not implement fingerprint evasion, stealth account isolation, engagement manipulation, or mass duplicate posting. Its deterministic guard checks both future queue entries and immutable successful-delivery history in `pipeline_registry.json`. A profile cannot be queued or claimed for execution inside another deployment's 23-hour window.

## Features

- Professional dark Profile Manager, Batch Processing Center, and Deployment Queue
- Credentials in Windows Credential Manager, macOS Keychain, or Linux Secret Service
- Atomic JSON registry writes, backup recovery, delivery history, and per-profile locking
- Native `threading.Thread` workers with Qt signals for responsive encoding and networking
- Batch sizes from 1 to 100 with a user-selected output folder
- H.264 High Profile, YUV420p, fast-start MP4, CRF 20 to 23, normalized metadata
- Standard 720p, 1080p, vertical, square, and landscape renditions
- Conservative mobile sharpening and optional 1 to 2 strength temporal grain
- AAC at 44.1 or 48 kHz plus EBU-style `loudnorm` targeting -16 LUFS
- TikTok OAuth refresh, creator-info query, Direct Post initialization, and chunk upload
- Optional HTTP(S) corporate proxy per channel

## Prerequisites

- Python 3.11+
- FFmpeg and FFprobe on `PATH`
- A registered TikTok developer application
- Login Kit and Content Posting API access
- User-granted `video.publish` authorization

Unaudited TikTok clients are restricted to private visibility. Public production posting requires TikTok review and adherence to its UX, consent, and API policies.

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

### Ubuntu or Debian

```bash
sudo apt update
sudo apt install -y ffmpeg python3-venv libsecret-1-0
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Configure

Keep app credentials out of source control:

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

Enter each user's OAuth access and refresh tokens in Profile Manager. Tokens are saved by `keyring`, not in the registry.

## Run

```bash
python app.py
```

The platform user-data directory contains:

- `pipeline_registry.json`: profiles without secrets, jobs, and delivery timestamps
- `pipeline_registry.json.bak`: rolling recovery copy
- `signaldesk.log`: operational log

## Processing behavior

Every rendition is a normal delivery adaptation. Profiles cycle deterministically through resolution, CRF 20 to 23, 44.1 or 48 kHz audio, a conservative unsharp value, and zero to two strength temporal grain. FFmpeg removes input metadata, writes a clean encoder tag, normalizes loudness, and creates streamable MP4 files.

## Posting behavior

Before a network request, SignalDesk atomically claims the job and re-runs the 23-hour history check. It then refreshes OAuth when needed, queries creator capabilities, initializes a `FILE_UPLOAD` Direct Post, and transfers TikTok-compatible chunks. Successful initialization and upload records the returned `publish_id` and timestamp. Final moderation and publication remain asynchronous on TikTok.

Official documentation:

- https://developers.tiktok.com/doc/content-posting-api-get-started
- https://developers.tiktok.com/doc/content-posting-api-reference-direct-post
- https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide
- https://developers.tiktok.com/doc/oauth-user-access-token-management

## Production hardening

For shared or unattended agency deployment, move OAuth exchange and token custody to a controlled backend, add signed desktop updates, package with PyInstaller, implement final publish-status polling, and add operator audit identities. This desktop build is intended for one authorized operator per workstation.
