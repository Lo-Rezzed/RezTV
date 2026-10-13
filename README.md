# RezTV

**Open Source TV Station in a Box**

RezTV is a simple, self-hosted platform that lets you create and run your own 24/7 web TV channels directly in the browser.

Upload videos, create channels, schedule continuous playout, and share a clean public player — all from an easy web admin panel.

## Features

- Upload videos (MP4, MOV, MKV, WebM) and animated GIFs, up to 2 GB each
- Upload music (MP3, M4A, AAC, FLAC, WAV, OGG) for channels with a separate audio playlist
- Two channel modes: **Standard** (each video plays with its own sound) or **Separate audio** (a video playlist and a music playlist that loop independently and play together)
- Automatic conversion of every upload to one station format (1080p, 30 fps, H.264/AAC, even volume, silent track added when needed)
- Media folders, with whole-folder adds to a channel
- Create multiple channels
- Drag & drop playlist reordering
- Continuous HLS streaming that restarts itself after a crash or server reboot
- Per-channel status and stream logs in the admin panel
- Clean public player (`/channel/1`)
- Custom Station Name
- Password-protected admin panel with login lockout (no default password)
- Docker-based installation
- Fully open source (MIT License)

## Quick Start (Docker)

```bash
git clone https://github.com/Lo-Rezzed/RezTV.git
cd RezTV
docker compose up -d --build
```

Before running the last command, set your own passwords:

RezTV reads its passwords from a `.env` file that you create. It is never committed to Git.

```bash
cp .env.example .env
openssl rand -hex 24   # run twice, once for each password
nano .env              # paste in your own ADMIN_PASSWORD and POSTGRES_PASSWORD
```

`docker compose` will refuse to start if either password is missing. Use a unique, long password; anyone with the admin password can upload, delete and stream on your station.

> If you change `POSTGRES_PASSWORD` after the database was first created, the existing database keeps the old one. For a fresh install, remove the old volume first: `docker compose down -v` (this deletes all channel and media records).

RezTV only listens on the server itself (`127.0.0.1:8000`), so it is not reachable from the internet until you set up nginx. Follow [Domain & SSL](docs/domain-ssl.md) to put it on your domain with HTTPS, then open `https://yourdomain.com/admin`. To test before nginx is set up, use an SSH tunnel from your own computer: `ssh -L 8000:localhost:8000 root@your-server-ip`, then open `http://localhost:8000/admin`. Log in with the username and password from your `.env`.

## Documentation

- [Installation](docs/installation.md)
- [Domain & SSL](docs/domain-ssl.md)
- [Preparing videos](docs/preparing-videos.md)
- [User guide](docs/user-guide.md)
- [VPS recommendations](docs/vps-recommendations.md)
- [Disclaimer](docs/disclaimer.md)

## License

MIT, see [LICENSE](LICENSE).
