# Domain Name & SSL Certificate Setup

This guide shows how to point a domain to your RezTV server and enable free HTTPS.

## 1. Point your domain to the server

In your domain registrar’s DNS settings, create an **A record**:

- Host / Name: `@` (or leave blank) → points to your server IP
- Host / Name: `www` → points to your server IP

Wait a few minutes (sometimes up to a few hours) for DNS to update.

## 2. Install Nginx (Reverse Proxy)

```bash
apt update
apt install -y nginx
