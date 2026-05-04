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
- Password-protected access via `APP_PASSWORD` environment variable
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
APP_PASSWORD=secret python app.py
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

## Fresh Deployment on OCI VM (Oracle Linux 9)

### 1. Prerequisites in OCI Console

**a) Dynamic Group** — allows the VM to call OCI APIs without a config file:
- Go to Identity → Dynamic Groups → Create
- Rule: `ANY {instance.id = 'ocid1.instance.oc1...'}`  
  (or by compartment: `ALL {instance.compartment.id = 'ocid1.compartment.oc1...'}`)

**b) Policy** — grant the dynamic group access:
```
Allow dynamic-group <dg-name> to read all-resources in tenancy
```

**c) Security List / NSG** — open port 80 inbound:
- VCN → Subnet → Security List → Add Ingress Rule
- Source CIDR: `0.0.0.0/0`, Protocol: TCP, Port: 80

---

### 2. Provision the VM

- Shape: `VM.Standard.E4.Flex` (1 OCPU, 6 GB RAM minimum)
- Image: **Oracle Linux 9**
- Attach the Dynamic Group created above

---

### 3. Connect and install system dependencies

```bash
ssh opc@<vm-public-ip>

# Install Node.js 20, Python, Nginx, Git
curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash -
sudo dnf install -y git nginx python3 python3-pip nodejs

# Verify Node version (must be 18+)
node --version
```

---

### 4. Clone the repository

```bash
sudo git clone https://github.com/raphaelsteixeira/drpgdashboard.git /opt/drpg-dashboard
sudo chown -R opc:opc /opt/drpg-dashboard
```

---

### 5. Build the frontend

```bash
cd /opt/drpg-dashboard/frontend
npm install
npm run build
```

---

### 6. Install Python dependencies

```bash
cd /opt/drpg-dashboard/backend
pip3 install -r requirements.txt

# Find where gunicorn was installed
which gunicorn
```

---

### 7. Create the systemd service

```bash
GUNICORN_PATH=$(which gunicorn)

sudo tee /etc/systemd/system/drpg-backend.service << EOF
[Unit]
Description=DRPG Dashboard Backend
After=network.target

[Service]
User=opc
WorkingDirectory=/opt/drpg-dashboard/backend
ExecStart=${GUNICORN_PATH} -w 4 -b 127.0.0.1:5050 app:app
Environment="APP_PASSWORD=your-secret-password"
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now drpg-backend
sudo systemctl status drpg-backend
```

> Replace `your-secret-password` with your chosen password. Users will be prompted for it on first access.

---

### 8. Configure Nginx

```bash
sudo tee /etc/nginx/nginx.conf << 'EOF'
user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log;
pid /var/run/nginx.pid;

include /usr/share/nginx/modules/*.conf;

events {
    worker_connections 1024;
}

http {
    log_format  main  '$remote_addr - $remote_user [$time_local] "$request" '
                      '$status $body_bytes_sent "$http_referer" '
                      '"$http_user_agent"';

    access_log  /var/log/nginx/access.log  main;

    sendfile            on;
    tcp_nopush          on;
    keepalive_timeout   65;
    types_hash_max_size 4096;

    include             /etc/nginx/mime.types;
    default_type        application/octet-stream;

    server {
        listen       80;
        listen       [::]:80;
        server_name  _;

        root /opt/drpg-dashboard/frontend/dist;
        index index.html;

        location / {
            try_files $uri $uri/ /index.html;
        }

        location /api/ {
            proxy_pass         http://127.0.0.1:5050;
            proxy_http_version 1.1;
            proxy_set_header   Host              $host;
            proxy_set_header   X-Real-IP         $remote_addr;
            proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
            proxy_read_timeout 120s;
        }

        location ~* \.(js|css|png|jpg|ico|svg|woff2?)$ {
            expires 1y;
            add_header Cache-Control "public, immutable";
        }

        error_page 404 /index.html;
    }
}
EOF

sudo nginx -t
sudo systemctl enable --now nginx
```

---

### 9. Open the firewall

```bash
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --reload
```

---

### 10. Verify

```bash
# Backend running?
sudo systemctl status drpg-backend

# Nginx running?
sudo systemctl status nginx

# App responding?
curl http://localhost
```

Open `http://<vm-public-ip>` in your browser — you will be prompted for the password set in `APP_PASSWORD`.

---

### Updating the app

```bash
cd /opt/drpg-dashboard
git pull origin main
cd frontend && npm install && npm run build
sudo systemctl restart drpg-backend
```

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth` | Authenticate with password, returns session token |
| GET | `/api/regions` | List subscribed OCI regions |
| GET | `/api/compartments?region=` | List compartments in a region |
| GET | `/api/drpgs?region=&compartment_id=` | List DR Protection Groups |
| GET | `/api/drpgs/{id}/plans` | List DR plans for a DRPG |
| GET | `/api/drpgs/{id}/members` | List members of a DRPG |
| GET | `/api/drpgs/{id}/rto` | Get RTO estimate |
| GET | `/api/drpgs/{id}/executions` | List plan executions |
| GET | `/api/executions/{id}` | Get execution details |
| POST | `/api/plans/{id}/precheck` | Trigger a plan pre-check |

> All endpoints except `/api/auth` require `Authorization: Bearer <token>` header when `APP_PASSWORD` is set.

---

## License

MIT
