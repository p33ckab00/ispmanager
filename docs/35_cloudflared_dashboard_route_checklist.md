# Cloudflared Checking and Route Checklist

Practical checklist for wiring `ISP Manager` behind an existing or newly installed Cloudflare Tunnel, with separate flows for:

- servers that already have a real public domain
- servers that do not yet have a usable domain and must be checked locally first

## Purpose

Use this checklist when:

- the Ubuntu server already has `cloudflared`
- you want to preserve an existing `cloudflared.service`
- you want the public hostname to route to `ISP Manager` safely
- or you want a localhost-first validation flow before exposing the app publicly

This checklist assumes:

- `ISP Manager` is deployed at `/opt/ispmanager`
- Gunicorn listens on `127.0.0.1:8193`
- Nginx listens on `127.0.0.1:8080` in Cloudflared mode
- Django `APP_BASE_URL` is your real public HTTPS hostname

Replace `app.example.com` below with your real production hostname.

## Two Supported Checking Paths

### Path A: Domain already exists

Use this when:

- your domain is already active in Cloudflare
- you already know the public hostname you want, such as `fsehub.qzz.io`
- you are ready to connect the hostname to the tunnel route

### Path B: No domain yet, localhost first

Use this when:

- the server is not yet ready for public hostname exposure
- DNS is not yet prepared
- you want to verify the app, Nginx, Gunicorn, PostgreSQL, and scheduler locally first

Important:

- `localhost` mode is a validation path, not the final public production path
- Cloudflare Tunnel published routes still require a real hostname
- if there is no domain yet, do local server-side checks first and add the tunnel route later

## Common Server-Side Precheck

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

## Path A: Checklist if a Real Domain Already Exists

Use this path for example with:

- `fsehub.qzz.io`
- `app.example.com`
- any real Cloudflare-managed hostname

### Required Django Environment

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

### Cloudflare Dashboard Checklist

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

### Domain and Public Route Check

Confirm:

- the hostname exists in Cloudflare
- the hostname is proxied through the tunnel
- the route belongs to the correct tunnel
- the route points to `http://127.0.0.1:8080`

### Public Validation

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

## Path B: Checklist if No Domain Is Ready Yet

Use this path when:

- there is no real public hostname yet
- you only want to prove the application stack is working locally
- you want to finish app installation before attaching a Cloudflare route

### Localhost or loopback-only goal

In this phase, your goal is only to confirm:

- PostgreSQL is healthy
- Gunicorn is serving Django
- Nginx can proxy to Gunicorn
- scheduler runs correctly

### Recommended local checks

Run:

```bash
sudo systemctl status postgresql --no-pager
sudo systemctl status ispmanager-web --no-pager
sudo systemctl status ispmanager-scheduler --no-pager
sudo systemctl status nginx --no-pager
curl -I http://127.0.0.1:8193
curl -I http://127.0.0.1:8080
```

Expected:

- `127.0.0.1:8193` responds from Gunicorn
- `127.0.0.1:8080` responds from Nginx
- app services remain healthy after restart

### Environment guidance without a real domain

If you are not attaching the app to a real hostname yet, keep your checks local.

For local-only verification, the important thing is that the stack runs and responds on loopback.

You can inspect the env file with:

```bash
sudo grep -E 'APP_BASE_URL|ALLOWED_HOSTS|CSRF_TRUSTED_ORIGINS|SECURE_PROXY_SSL_HEADER|DISABLE_SCHEDULER' /etc/ispmanager/ispmanager.env
```

Practical note:

- if no public hostname exists yet, do not treat the deployment as fully production-ready
- complete the domain and route setup later using Path A

### Optional local browser access through SSH tunnel

If you want to view the local site from your own machine before a public domain exists, you can forward the local Nginx port over SSH:

```bash
ssh -L 8080:127.0.0.1:8080 user@your-server-ip
```

Then on your own machine open:

```text
http://127.0.0.1:8080
```

This is only for temporary validation.

### When to switch from localhost mode to domain mode

Move to Path A only when:

- your final domain is ready in Cloudflare
- you know which hostname you want to use
- you are ready to map that hostname to the tunnel route

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

## Common Mistakes to Avoid

- pointing the tunnel directly to `127.0.0.1:8193`
- using `http://127.0.0.1:8080` in `APP_BASE_URL`
- leaving `APP_BASE_URL` as `http`
- forgetting `SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO,https`
- running scheduler inside Gunicorn instead of the separate scheduler service
- reinstalling `cloudflared` over an existing service without checking what else uses it
- treating localhost-only checks as if the public deployment is already finished

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

If you are still in localhost-first mode and cannot reach the app:

```bash
curl -I http://127.0.0.1:8193
curl -I http://127.0.0.1:8080
sudo systemctl status ispmanager-web --no-pager
sudo systemctl status nginx --no-pager
sudo journalctl -u ispmanager-web -n 100 --no-pager
sudo journalctl -u nginx -n 50 --no-pager
```

## Final Recommendation

For `ISP Manager`, the cleanest Cloudflare Tunnel route is:

- public hostname: `https://app.example.com`
- tunnel origin: `http://127.0.0.1:8080`
- Nginx upstream: `http://127.0.0.1:8193`

That keeps the deployment private, clean, and aligned with the current production architecture.

If no domain is ready yet:

- finish the localhost checks first
- confirm the app stack is healthy on `127.0.0.1`
- only then attach a real hostname through Cloudflare Tunnel
