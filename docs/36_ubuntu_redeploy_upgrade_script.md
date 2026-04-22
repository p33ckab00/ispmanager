# Ubuntu Redeploy and Upgrade Script

Guide for updating an already deployed Ubuntu production instance without using the fresh-install script again.

## Purpose

Use this workflow when:

- `ISP Manager` is already deployed at `/opt/ispmanager`
- PostgreSQL is already prepared
- `/etc/ispmanager/ispmanager.env` already exists
- you want to deploy a newer version of the code safely

This is for:

- code updates
- dependency updates
- migrations
- static file refresh

This is not for:

- first-time server setup
- replacing PostgreSQL with a new cluster
- rebuilding Cloudflared from scratch

## Script

The redeploy script is:

- `deploy/redeploy_ubuntu_update.sh`

## What the script does

The script will:

1. verify that an existing deployment is present
2. preserve `/opt/libreqos`
3. back up the current app code and config
4. stage the new repo contents from the repo clone you run it from
5. update `/opt/ispmanager`
6. reuse the existing environment file
7. reuse or rebuild the virtualenv depending on the option you choose
8. run:
   - `migrate`
   - `collectstatic`
   - `check`
9. restart:
   - `ispmanager-web`
   - `ispmanager-scheduler`
   - `nginx`

It does not:

- overwrite `/etc/ispmanager/ispmanager.env`
- touch `/opt/libreqos`
- overwrite an existing `cloudflared.service`
- import local SQLite state

## Recommended Usage

On the Ubuntu server:

```bash
cd /tmp
git clone <your-repo-url> ispmanager-update
cd ispmanager-update
git checkout <branch-or-tag-you-want>
```

Run the redeploy:

```bash
sudo bash deploy/redeploy_ubuntu_update.sh
```

## Optional Environment Variables

Useful toggles:

- `REBUILD_VENV=1`
  - recreate the Python virtual environment from scratch
- `PRESERVE_MEDIA=1`
  - keep `/opt/ispmanager/media` intact

Example:

```bash
sudo REBUILD_VENV=1 bash deploy/redeploy_ubuntu_update.sh
```

## Backup Behavior

The script stores a backup snapshot under:

- `/opt/backups/ispmanager/redeploy-<timestamp>/`

This backup includes:

- current app code snapshot
- environment file copy
- service file copies
- Nginx site copy

## Validation After Redeploy

Run:

```bash
sudo systemctl status ispmanager-web
sudo systemctl status ispmanager-scheduler
sudo systemctl status nginx
curl -I http://127.0.0.1:8193
```

If using Cloudflared:

```bash
curl -I http://127.0.0.1:8080
sudo systemctl status cloudflared
```

Then validate in browser:

- landing page
- admin login
- dashboard
- subscribers
- billing snapshots
- accounting pages
- routers pages

## Rollback Basics

If the redeploy is bad:

1. stop the web and scheduler services
2. restore the backup snapshot from `/opt/backups/ispmanager/redeploy-<timestamp>/`
3. restore app code into `/opt/ispmanager`
4. restore env/service/nginx files if needed
5. restart services

## Recommended Operational Habit

For live Ubuntu production:

- use `install_ubuntu_fresh.sh` only for first deployment
- use `redeploy_ubuntu_update.sh` for future application updates
- treat Cloudflared as shared infrastructure unless it is truly dedicated to `ISP Manager`
