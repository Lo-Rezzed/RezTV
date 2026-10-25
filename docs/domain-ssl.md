# Domain Name & SSL Certificate Setup

This guide shows how to point a domain to your RezTV server and enable free HTTPS.

## 1. Point your domain to the server

In your domain registrar's DNS settings, create two A records:

- Host / Name: `@` (or leave blank) → your server IP
- Host / Name: `www` → your server IP

Wait a few minutes (sometimes up to a few hours) for DNS to update.

## 2. Install nginx (reverse proxy)

```bash
apt update
apt install -y nginx
```

## 3. Create the nginx configuration

RezTV only listens on `127.0.0.1:8000`, so nginx is the only way in from the internet. Keep the `X-Real-IP` line: login rate limiting uses it to tell visitors apart.

```bash
nano /etc/nginx/sites-available/reztv
```

Paste the following (replace `yourdomain.com` with your real domain):

```nginx
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;

    # Match MAX_UPLOAD_MB in .env (default 2048 MB)
    client_max_body_size 2G;
    proxy_request_buffering off;
    proxy_read_timeout 600s;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

`proxy_read_timeout` covers how long nginx waits for RezTV to answer a request (its default is only 60 seconds). Uploads need it while the file is being received; conversion happens afterwards in the background, so large files don't need a longer timeout for that. **Back up now** also runs in the background and answers at once. **Restore** is the exception: it answers only when the restore has finished, which can take several minutes with a large media folder, so keep `proxy_read_timeout` at `600s` or raise it (for example `1800s`) if restores report "HTTP 504". Reload nginx after changing it (`nginx -t && systemctl reload nginx`).

Enable the site:

```bash
ln -s /etc/nginx/sites-available/reztv /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx
```

## 4. Install a free SSL certificate (Let's Encrypt)

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d yourdomain.com -d www.yourdomain.com
```

Follow the prompts:

1. Enter your email
2. Agree to the terms
3. If asked, choose to redirect HTTP to HTTPS

Certbot configures HTTPS and sets up automatic renewal.

## 5. Test

Visit:

- `https://yourdomain.com`
- `https://yourdomain.com/admin` (asks for the username and password from your `.env`)
- `https://yourdomain.com/channel/1`

You should see a secure padlock in the browser.
