# CaptionAI TikTok Studio

CaptionAI TikTok Studio is a desktop app for managing TikTok accounts and publishing videos with AI-generated English captions.

It uses:

- TikTok Content Posting API
- OAuth 2.0 PKCE flow
- Groq AI for caption generation
- PySide6 desktop UI
- OS keychain for secret storage when available

---

## Features

- Add and manage multiple TikTok profiles
- TikTok OAuth 2.0 authorization via browser
- PKCE-based secure login flow
- Automatic access token refresh
- Groq AI caption generation
- English viral caption prompts
- Video preview before publishing
- Privacy level selection
- Comment / Duet / Stitch controls
- Content disclosure options
- Branded content support
- Chunked TikTok video upload
- Publish status polling
- Local logs
- OS keychain secret storage with local fallback if keychain is unavailable

---

## Requirements

- Python 3.10 or newer
- TikTok Developer App
- TikTok Content Posting API enabled
- Groq API key
- Desktop OS: Windows, macOS or Linux

Python packages:

```text
PySide6
requests
keyring
platformdirs
opencv-python
