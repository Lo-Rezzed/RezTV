Domain Name & SSL Certificate Setup
This guide shows how to point a domain to your RezTV server and enable free HTTPS.

1. Point your domain to the server
In your domain registrar’s DNS settings, create an A record:

Host / Name: @ (or leave blank) → points to your server IP
Host / Name: www → points to your server IP
Wait a few minutes (sometimes up to a few hours) for DNS to update.

2. Install Nginx (Reverse Proxy)
bash
apt update
apt install -y nginx
3. Create Nginx configuration

RezTV only listens on `127.0.0.1:8000`, so nginx is the only way in from the internet. Keep the `X-Real-IP` line: login rate limiting uses it to tell visitors apart.

bash
nano /etc/nginx/sites-available/reztv
Paste the following (replace yourdomain.com with your real domain):

nginx
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
Enable the site:

bash
ln -s /etc/nginx/sites-available/reztv /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx
4. Install free SSL certificate (Let's Encrypt)
bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d yourdomain.com -d www.yourdomain.com
Follow the prompts:

Enter your email
Agree to the terms
Choose option 2 (Redirect HTTP to HTTPS)
Certbot will automatically configure HTTPS and set up auto-renewal.

5. Test
Visit:

https://yourdomain.com
https://yourdomain.com/admin
https://yourdomain.com/channel/1
You should see a secure padlock in the browser.
