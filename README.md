# OCI DRPG Dashboard

A web dashboard for monitoring **OCI Full Stack Disaster Recovery** (DRPG) resources across regions and compartments. It surfaces protection group status, RPO health, DR plans, members, executions, and RTO estimates in a single view.

---

## Features

- Browse all **DR Protection Groups** by region and compartment
- View **RPO status** (last sync time) per protection group
- Inspect **DR Plans** and trigger **pre-checks**
- List **protection group members** (compute, databases, volumes, etc.)
- View **DR plan executions** and their step-by-step details
- Query **RTO estimates** per protection group
- Supports both **Instance Principal** (when running on OCI) and **~/.oci/config** authentication — detected automatically

---

## Architecture

```
┌─────────────────────┐        ┌──────────────────────────┐
│  React + Vite       │  HTTP  │  Flask + Gunicorn        │
│  (frontend/src)     │◄──────►│  (backend/app.py)        │
│  Tailwind CSS       │        │  OCI Python SDK          │
└─────────────────────┘        └──────────────────────────┘
                                          │
                                          ▼
                                   OCI APIs (DRPG,
                                   Identity, Compute…)
```

---

## Local Development

### Prerequisites

- Python 3.9+
- Node.js 18+
- OCI CLI configured (`~/.oci/config`) or running on an OCI instance with Instance Principal

### Backend

```bash
cd backend
pip install -r requirements.txt
python app.py
# Runs on http://localhost:5050
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# Runs on http://localhost:5173
```

The Vite dev server proxies `/api/*` requests to the Flask backend automatically.

---

## Production Deployment (OCI VM — Oracle Linux 9)

### 1. Install dependencies

```bash
sudo dnf install -y git nginx python3 python3-pip
curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash -
sudo dnf install -y nodejs
```

### 2. Clone and build

```bash
git clone git@github.com:raphaelsteixeira/drpgdashboard.git /opt/drpg-dashboard
cd /opt/drpg-dashboard/frontend && npm install && npm run build
cd /opt/drpg-dashboard/backend && pip3 install -r requirements.txt
```

### 3. Systemd service for the backend

Create `/etc/systemd/system/drpg-backend.service`:

```ini
[Unit]
Description=DRPG Dashboard Backend
After=network.target

[Service]
User=opc
WorkingDirectory=/opt/drpg-dashboard/backend
ExecStart=/usr/local/bin/gunicorn -w 4 -b 127.0.0.1:5050 app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now drpg-backend
```

### 4. Nginx

Create `/etc/nginx/conf.d/drpg.conf`:

```nginx
server {
    listen 80;
    server_name _;

    root /opt/drpg-dashboard/frontend/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:5050;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
sudo systemctl enable --now nginx
sudo firewall-cmd --permanent --add-service=http && sudo firewall-cmd --reload
```

### 5. OCI Instance Principal

Create a **Dynamic Group** in OCI IAM for the VM instance and attach a **Policy**:

```
Allow dynamic-group <your-dg-name> to read all-resources in tenancy
```

The backend auto-detects Instance Principal via the OCI metadata endpoint — no `~/.oci/config` needed on the VM.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/regions` | List subscribed OCI regions |
| GET | `/api/compartments?region=` | List compartments in a region |
| GET | `/api/drpgs?region=&compartment_id=` | List DR Protection Groups |
| GET | `/api/drpgs/{id}/plans` | List DR plans for a DRPG |
| GET | `/api/drpgs/{id}/members` | List members of a DRPG |
| GET | `/api/drpgs/{id}/rto` | Get RTO estimate |
| GET | `/api/drpgs/{id}/executions` | List plan executions |
| GET | `/api/executions/{id}` | Get execution details |
| POST | `/api/plans/{id}/precheck` | Trigger a plan pre-check |

---

## License

MIT
