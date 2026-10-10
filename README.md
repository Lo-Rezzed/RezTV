# RezTV

**Open Source TV Station in a Box**

RezTV is a simple, self-hosted platform that lets you create and run your own 24/7 web TV channels directly in the browser.

Upload videos, create channels, schedule continuous playout, and share a clean public player — all from an easy web admin panel.

## Features

- Upload and manage video files
- Create multiple channels
- Drag & drop playlist reordering
- Continuous HLS streaming
- Clean public player (`/channel/1`)
- Custom Station Name
- Password-protected admin panel
- Docker-based installation
- Fully open source (MIT License)

## Quick Start (Docker)

```bash
git clone https://github.com/Lo-Rezzed/RezTV.git
cd RezTV
docker compose up -d --build
