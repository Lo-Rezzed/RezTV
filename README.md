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

Then open `http://your-server-ip:8000/admin` and log in with the username and password from your `.env`.

## Documentation

- [Installation](docs/installation.md)
- [Domain & SSL](docs/domain-ssl.md)
- [Preparing videos](docs/preparing-videos.md)
- [User guide](docs/user-guide.md)
- [VPS recommendations](docs/vps-recommendations.md)
- [Disclaimer](docs/disclaimer.md)

## License

MIT, see [LICENSE](LICENSE).
