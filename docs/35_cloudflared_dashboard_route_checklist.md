# Cloudflared Dashboard Route Checklist

Practical checklist for wiring `ISP Manager` behind an existing or newly installed Cloudflare Tunnel.

## Purpose

Use this checklist when:

- the Ubuntu server already has `cloudflared`
- you want to preserve an existing `cloudflared.service`
- you want the public hostname to route to `ISP Manager` safely

This checklist assumes:

- `ISP Manager` is deployed at `/opt/ispmanager`
- Gunicorn listens on `127.0.0.1:8193`
- Nginx listens on `127.0.0.1:8080` in Cloudflared mode
- Django `APP_BASE_URL` is your real public HTTPS hostname

Replace `app.example.com` below with your real production hostname.

## Server-Side Precheck

Run these on the Ubuntu server:

```bash
command -v cloudflared
cloudflared --version
sudo systemctl status cloudflared
sudo systemctl status ispmanager-web
sudo systemctl status ispmanager-scheduler
sudo systemctl status nginx
curl -I http://127.0.0.1:8080
curl -I http://127.0.0.1:8193
```

Healthy expected state:

- `cloudflared` is installed, or you know it needs a fresh install
- `ispmanager-web` is running
- `ispmanager-scheduler` is running
- `nginx` is running
- `http://127.0.0.1:8080` responds locally

Important:

- do not point Cloudflare Tunnel directly to `127.0.0.1:8193`
- terminate at local Nginx first
- keep `/opt/libreqos` untouched

## Required Django Environment

Confirm `/etc/ispmanager/ispmanager.env` contains:

```env
DEBUG=False
APP_BASE_URL=https://app.example.com
ALLOWED_HOSTS=app.example.com,localhost,127.0.0.1
CORS_ALLOWED_ORIGINS=https://app.example.com
CSRF_TRUSTED_ORIGINS=https://app.example.com
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_SSL_REDIRECT=True
SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO,https
DISABLE_SCHEDULER=1
```

Then restart the app services:

```bash
sudo systemctl restart ispmanager-web
sudo systemctl restart ispmanager-scheduler
```

## Cloudflare Dashboard Checklist

Go to:

- `Cloudflare Dashboard`
- `Networking`
- `Tunnels`

Then:

1. Open the tunnel you want to use.
2. Confirm whether this is an existing shared tunnel or a dedicated new tunnel for `ISP Manager`.
3. Under `Routes`, choose `Add route`.
4. Select `Published application`.
5. Set the public hostname:
   - hostname: `app`
   - domain: `example.com`
6. Set the service URL:
   - `http://127.0.0.1:8080`
7. Save the route.

Expected result:

- public hostname `app.example.com`
- local origin `http://127.0.0.1:8080`

## If `cloudflared.service` Already Exists

If the server already has a working `cloudflared.service`:

- do not reinstall it blindly
- do not overwrite its token automatically
- do not assume it is dedicated to `ISP Manager`

Instead:

1. preserve the existing service
2. add or update the published application route in the dashboard
3. verify the route targets `http://127.0.0.1:8080`
4. restart `cloudflared` only if configuration changes require it

Useful check:

```bash
sudo systemctl status cloudflared
sudo journalctl -u cloudflared -n 100 --no-pager
```

## If `cloudflared` Is Not Installed Yet

Fresh install flow:

1. create or copy the tunnel token from Cloudflare
2. install `cloudflared`
3. install the system service with the token
4. start the service
5. add the published application route to `http://127.0.0.1:8080`

Typical service install command:

```bash
sudo cloudflared service install <TUNNEL_TOKEN>
sudo systemctl enable --now cloudflared
```

## DNS and Hostname Check

Confirm the public hostname resolves through Cloudflare and is tied to the tunnel route you created.

What you want:

- one public hostname for the app
- the hostname is proxied by Cloudflare
- the route belongs to the correct tunnel

## Post-Route Validation

After saving the route, test:

```bash
curl -I https://app.example.com
```

Then validate in browser:

- landing page loads
- admin login works
- dashboard works
- subscriber list works
- billing snapshot pages work
- router pages work

## Common Mistakes to Avoid

- pointing the tunnel directly to `127.0.0.1:8193`
- using `http://127.0.0.1:8080` in `APP_BASE_URL`
- leaving `APP_BASE_URL` as `http`
- forgetting `SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO,https`
- running scheduler inside Gunicorn instead of the separate scheduler service
- reinstalling `cloudflared` over an existing service without checking what else uses it

## Troubleshooting Shortlist

If the public hostname returns `502`:

```bash
curl -I http://127.0.0.1:8080
sudo systemctl status cloudflared
sudo journalctl -u cloudflared -n 100 --no-pager
sudo systemctl status ispmanager-web
sudo journalctl -u ispmanager-web -n 100 --no-pager
```

If login or forms fail with CSRF:

- check `APP_BASE_URL`
- check `CSRF_TRUSTED_ORIGINS`
- check `SECURE_PROXY_SSL_HEADER`
- confirm Nginx sends `X-Forwarded-Proto https` in Cloudflared mode

## Final Recommendation

For `ISP Manager`, the cleanest Cloudflare Tunnel route is:

- public hostname: `https://app.example.com`
- tunnel origin: `http://127.0.0.1:8080`
- Nginx upstream: `http://127.0.0.1:8193`

That keeps the deployment private, clean, and aligned with the current production architecture.
