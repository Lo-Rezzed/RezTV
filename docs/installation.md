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

Open `http://your-server-ip:8000/admin`. To put RezTV on your own domain with HTTPS, follow [Domain & SSL](domain-ssl.md).

## Updating

```bash
git pull
docker compose up -d --build
```
