# Installation Guide

## Requirements

- A Linux VPS (Ubuntu 22.04 or 24.04 recommended)
- Docker and Docker Compose installed
- At least 2 CPU cores and 4 GB RAM (more recommended for multiple channels)

## Install Docker (Ubuntu)

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Optional: let your user run Docker without `sudo` (log out and back in afterwards):

```bash
sudo usermod -aG docker $USER
```

## Download RezTV

```bash
git clone https://github.com/Lo-Rezzed/RezTV.git
cd RezTV
```

## Set your passwords (required)

RezTV reads its passwords from a `.env` file that you create. It is never committed to Git.

```bash
cp .env.example .env
openssl rand -hex 24   # run twice, once for each password
nano .env              # paste in your own ADMIN_PASSWORD and POSTGRES_PASSWORD
```

`docker compose` will refuse to start if either password is missing. Use a unique, long password; anyone with the admin password can upload, delete and stream on your station.

> If you change `POSTGRES_PASSWORD` after the database was first created, the existing database keeps the old one. For a fresh install, remove the old volume first: `docker compose down -v` (this deletes all channel and media records).

## Start RezTV

```bash
docker compose up -d --build
docker compose ps        # both reztv-db and reztv-backend should be "running"
```

RezTV only listens on the server itself (`127.0.0.1:8000`), so it is not reachable from the internet until you set up nginx. Follow [Domain & SSL](domain-ssl.md) to put it on your domain with HTTPS, then open `https://yourdomain.com/admin`. To test before nginx is set up, use an SSH tunnel from your own computer: `ssh -L 8000:localhost:8000 root@your-server-ip`, then open `http://localhost:8000/admin`.

## Security settings

- RezTV will not start if `ADMIN_PASSWORD` is missing (there is no default password).
- After 5 wrong logins from one address within 15 minutes, that address is locked out for 15 minutes. Change with `LOGIN_MAX_FAILURES` and `LOGIN_WINDOW_SECONDS` in `.env`.
- Uploads: MP4, MOV, MKV and WebM only, up to 2 GB by default. Change the limit with `MAX_UPLOAD_MB` in `.env` (and `client_max_body_size` in nginx to match). Every upload is checked with ffprobe and rejected if it isn't a readable video.
- The media library list is only visible to the admin and never shows server file paths.

## Updating

```bash
git pull
docker compose up -d --build
```

Code changes only take effect after the rebuild (the server no longer auto-reloads code). Channels need **Start Stream** pressed again after an update.
