# Deploying to AWS (single EC2 + S3/CloudFront)

Architecture: one CloudFront distribution serves the React build from S3 and
proxies `/api/*` to an EC2 box running FastAPI. Same origin for app + API, so
**no CORS in production** and **HTTPS for free** (no domain purchase needed).

```
Browser ──HTTPS──> CloudFront
                     ├── default  ──> S3 (React build)
                     └── /api/*   ──> EC2 (HTTP: nginx ─> uvicorn)
                                        └── /var/lib/waiverwire/waiverwire.db
```

Phase 0 (code prep) is already done in the repo:
- `frontend/src/api.ts` uses a relative `/api` base (`VITE_API_BASE` overrides it).
- `frontend/vite.config.ts` proxies `/api` → `localhost:8000` for `npm run dev`.
- `waiverwire/api.py` reads extra CORS origins from `ALLOWED_ORIGINS`.
- `.env.example`, `requirements.txt`, and the `deploy/` service+nginx files exist.

---

## Backend — EC2

1. Launch **Amazon Linux 2023**, **t3.micro**, 8–20 GB gp3. Security group: SSH
   (22) from your IP only, HTTP (80) from anywhere. Do **not** expose 8000.
2. SSH in (EC2 Instance Connect works — allow SSH from the instance-connect
   range or temporarily `0.0.0.0/0`) and set up. The app lives on the `frontend`
   branch, so clone that branch explicitly:
   ```bash
   sudo dnf install -y python3.11 python3.11-pip git nginx
   sudo git clone -b frontend <REPO_URL> /opt/waiverwire
   sudo chown -R ec2-user:ec2-user /opt/waiverwire
   cd /opt/waiverwire
   python3.11 -m venv venv
   ./venv/bin/pip install -r requirements.txt
   ./venv/bin/pip install -e .
   sudo mkdir -p /var/lib/waiverwire && sudo chown ec2-user /var/lib/waiverwire
   ```
3. Create `/opt/waiverwire/.env` from `.env.example`. **Set a real `AUTH_SECRET`**
   (`python -c "import secrets; print(secrets.token_hex(32))"`), your
   `GEMINI_API_KEY`, and `USERS_DB=/var/lib/waiverwire/waiverwire.db`. Then
   `chmod 600 /opt/waiverwire/.env`.
4. Install the backend service:
   ```bash
   sudo cp deploy/waiverwire.service /etc/systemd/system/
   sudo systemctl daemon-reload && sudo systemctl enable --now waiverwire
   ```
5. Install the nginx `/api` proxy. Amazon Linux's nginx ships its own default
   server block in `/etc/nginx/nginx.conf`, so we drop just the `/api` location
   into `default.d/` (which that server `include`s) rather than adding a second
   full server block (which collides on `default_server` and 404s):
   ```bash
   sudo cp deploy/nginx.conf /etc/nginx/default.d/waiverwire.conf
   sudo rm -f /etc/nginx/conf.d/waiverwire.conf   # remove any old full-server copy
   sudo nginx -t && sudo systemctl enable --now nginx
   sudo systemctl reload nginx
   ```
6. Verify (from the box, then from your laptop against the public DNS):
   ```bash
   curl http://127.0.0.1:8000/api/me   # backend directly
   curl http://localhost/api/me        # through nginx
   ```
   `{"detail":"Not authenticated"}` (HTTP 401) means the auth gate is live =
   success. `journalctl -u waiverwire -f` shows backend logs.

> **RAM:** t3.micro is 1 GB; polars + a season of nflverse data can be tight.
> If uvicorn gets OOM-killed, add swap:
> ```bash
> sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
> sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
> echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
> ```
> or move up to t3.small.

---

## Frontend — S3 + CloudFront

1. Build locally (relative `/api` base needs no env var):
   ```bash
   cd frontend && npm ci && npm run build   # -> frontend/dist/
   ```
2. Create a **private** S3 bucket (keep Block Public Access ON) and upload the
   **contents** of `frontend/dist/` (so `index.html` sits at the bucket root, not
   under a `dist/` prefix). Either drag-and-drop `index.html` + the `assets/`
   folder in the S3 console, or with the CLI:
   ```bash
   aws s3 sync frontend/dist "s3://<YOUR_BUCKET>" --delete
   ```
3. Create a **CloudFront distribution**:
   - **Origin A** = the S3 bucket, with **Origin Access Control (OAC)**. After
     creating, apply the **bucket policy** CloudFront generates (banner → Copy
     policy, or Origins → edit origin → Copy policy) to the bucket's Permissions.
   - **Default root object** = `index.html`.
   - **Origin B** = create a second origin: custom origin = the EC2 **public
     DNS**, protocol **HTTP only**, port **80**.
   - **Default behavior** → Origin A (S3), Viewer protocol **Redirect HTTP→HTTPS**.
   - **Add behavior** path `/api/*` → Origin B:
     - **Allowed HTTP methods:** `GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE`
       (default GET/HEAD only would break login/signup/chat, which are POST).
     - **Cache policy: CachingDisabled.**
     - **Origin request policy: AllViewer** (forwards the `Authorization` header).
   - **Custom error responses**: map **403** and **404** → response page
     `/index.html`, HTTP code **200** (SPA deep-link routing).
   - Apply the generated S3 bucket policy CloudFront offers (grants OAC read).
4. Open the distribution's `https://dxxxx.cloudfront.net` URL — that's the app.

---

## Redeploys

- **Frontend:** `npm run build` → `aws s3 sync frontend/dist s3://<BUCKET> --delete`
  → CloudFront **invalidation** (`/*`).
- **Backend:** `cd /opt/waiverwire && git pull && ./venv/bin/pip install -r requirements.txt && sudo systemctl restart waiverwire`.

## Backups (SQLite)

Nightly cron on the box:
```bash
sqlite3 /var/lib/waiverwire/waiverwire.db ".backup /tmp/w.db" \
  && aws s3 cp /tmp/w.db "s3://<BACKUP_BUCKET>/waiverwire-$(date +%F).db"
```

## Later — weekly automation
EventBridge Scheduler → Lambda (or a cron on this EC2) → SNS SMS for the Tuesday
text. Note: SNS SMS starts in a **sandbox** — verify the destination number and
request a spending limit / sandbox exit first.
