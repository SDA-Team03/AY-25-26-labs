# Lab 4 — Code Snippets

This file is the code companion to [09-lab4-step-by-step.md](09-lab4-step-by-step.md). It contains all Kubernetes manifests, the application source, and the Dockerfile — complete and ready to apply.

All files are located in `mzinga/lab4-k8s/`.

---

## Application — `app.py`

The demo HTTP service. Version and colour are injected via environment variables at runtime.

```python
import json
import os
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer

VERSION = os.getenv("APP_VERSION", "1.0.0")
APP_COLOR = os.getenv("APP_COLOR", "blue")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress default Apache-style access log

    def do_GET(self):
        if self.path == "/health":
            self._respond(200, {"status": "ok"})
        elif self.path == "/":
            self._respond(200, {
                "version": VERSION,
                "color": APP_COLOR,
                "hostname": socket.gethostname(),
                "message": f"Hello from version {VERSION}",
            })
        else:
            self._respond(404, {"error": "not found"})

    def _respond(self, status: int, body: dict):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("", port), Handler)
    print(f"Listening on :{port} — version={VERSION} color={APP_COLOR}", flush=True)
    server.serve_forever()
```

---

## Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY app.py .

ARG APP_VERSION=1.0.0
ARG APP_COLOR=blue

ENV APP_VERSION=${APP_VERSION}
ENV APP_COLOR=${APP_COLOR}
ENV PORT=8080

EXPOSE 8080

CMD ["python", "app.py"]
```

---

## Step 1 — Build Images and Load into Minikube

**macOS / Linux / WSL:**

```sh
cd mzinga/lab4-k8s

docker build --build-arg APP_VERSION=1.0.0 --build-arg APP_COLOR=blue  -t mzinga-webapp:1.0.0 .
docker build --build-arg APP_VERSION=2.0.0 --build-arg APP_COLOR=green -t mzinga-webapp:2.0.0 .

minikube image load mzinga-webapp:1.0.0
minikube image load mzinga-webapp:2.0.0

minikube image ls | grep mzinga-webapp
```

**Windows PowerShell:**

```powershell
cd mzinga\lab4-k8s

docker build --build-arg APP_VERSION=1.0.0 --build-arg APP_COLOR=blue  -t mzinga-webapp:1.0.0 .
docker build --build-arg APP_VERSION=2.0.0 --build-arg APP_COLOR=green -t mzinga-webapp:2.0.0 .

minikube image load mzinga-webapp:1.0.0
minikube image load mzinga-webapp:2.0.0

minikube image ls | Select-String "mzinga-webapp"
```

---

## Namespace — `k8s/namespace.yaml`

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: mzinga-lab4
```

Apply:

```sh
kubectl apply -f k8s/namespace.yaml
```

---

## Rolling Update — `k8s/rolling/`

### `service.yaml`

```yaml
apiVersion: v1
kind: Service
metadata:
  name: webapp
  namespace: mzinga-lab4
spec:
  selector:
    app: webapp
  ports:
    - port: 80
      targetPort: 8080
```

### `deployment-v1.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: webapp
  namespace: mzinga-lab4
  labels:
    app: webapp
spec:
  replicas: 3
  selector:
    matchLabels:
      app: webapp
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1
      maxSurge: 1
  template:
    metadata:
      labels:
        app: webapp
        version: v1
    spec:
      containers:
        - name: webapp
          image: mzinga-webapp:1.0.0
          imagePullPolicy: Never
          ports:
            - containerPort: 8080
          env:
            - name: APP_VERSION
              value: "1.0.0"
            - name: APP_COLOR
              value: "blue"
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 2
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests:
              cpu: "50m"
              memory: "32Mi"
            limits:
              cpu: "100m"
              memory: "64Mi"
```

### `deployment-v2.yaml`

Identical to `deployment-v1.yaml` except for the image tag and environment variables:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: webapp
  namespace: mzinga-lab4
  labels:
    app: webapp
spec:
  replicas: 3
  selector:
    matchLabels:
      app: webapp
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1
      maxSurge: 1
  template:
    metadata:
      labels:
        app: webapp
        version: v2
    spec:
      containers:
        - name: webapp
          image: mzinga-webapp:2.0.0
          imagePullPolicy: Never
          ports:
            - containerPort: 8080
          env:
            - name: APP_VERSION
              value: "2.0.0"
            - name: APP_COLOR
              value: "green"
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 2
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests:
              cpu: "50m"
              memory: "32Mi"
            limits:
              cpu: "100m"
              memory: "64Mi"
```

### Apply and Operate

```sh
# Initial deploy
kubectl apply -f k8s/rolling/service.yaml
kubectl apply -f k8s/rolling/deployment-v1.yaml
kubectl rollout status deployment/webapp -n mzinga-lab4

# Port-forward
kubectl port-forward service/webapp 8080:80 -n mzinga-lab4 &

# Verify v1
curl -s http://localhost:8080/

# Trigger rolling update to v2
kubectl apply -f k8s/rolling/deployment-v2.yaml

# Watch rollout
kubectl get pods -n mzinga-lab4 -w

# Roll back to v1
kubectl rollout undo deployment/webapp -n mzinga-lab4
kubectl rollout status deployment/webapp -n mzinga-lab4
```

---

## Recreate (Replace) Strategy — `k8s/recreate/`

The only difference from the rolling manifests is `strategy.type: Recreate`. There are no `rollingUpdate` parameters — Kubernetes terminates all Pods at once before starting any new ones.

### `service.yaml`

```yaml
apiVersion: v1
kind: Service
metadata:
  name: webapp
  namespace: mzinga-lab4
spec:
  selector:
    app: webapp
  ports:
    - port: 80
      targetPort: 8080
```

### `deployment-v1.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: webapp
  namespace: mzinga-lab4
  labels:
    app: webapp
spec:
  replicas: 3
  selector:
    matchLabels:
      app: webapp
  strategy:
    type: Recreate      # all old Pods terminate before any new Pod starts
  template:
    metadata:
      labels:
        app: webapp
        version: v1
    spec:
      containers:
        - name: webapp
          image: mzinga-webapp:1.0.0
          imagePullPolicy: Never
          ports:
            - containerPort: 8080
          env:
            - name: APP_VERSION
              value: "1.0.0"
            - name: APP_COLOR
              value: "blue"
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 2
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests:
              cpu: "50m"
              memory: "32Mi"
            limits:
              cpu: "100m"
              memory: "64Mi"
```

### `deployment-v2.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: webapp
  namespace: mzinga-lab4
  labels:
    app: webapp
spec:
  replicas: 3
  selector:
    matchLabels:
      app: webapp
  strategy:
    type: Recreate      # all old Pods terminate before any new Pod starts
  template:
    metadata:
      labels:
        app: webapp
        version: v2
    spec:
      containers:
        - name: webapp
          image: mzinga-webapp:2.0.0
          imagePullPolicy: Never
          ports:
            - containerPort: 8080
          env:
            - name: APP_VERSION
              value: "2.0.0"
            - name: APP_COLOR
              value: "green"
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 2
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests:
              cpu: "50m"
              memory: "32Mi"
            limits:
              cpu: "100m"
              memory: "64Mi"
```

### Apply and Operate

```sh
# Deploy v1 with Recreate strategy
kubectl apply -f k8s/recreate/service.yaml
kubectl apply -f k8s/recreate/deployment-v1.yaml
kubectl rollout status deployment/webapp -n mzinga-lab4

# Port-forward
kubectl port-forward service/webapp 8080:80 -n mzinga-lab4 &
curl -s http://localhost:8080/
# → {"version": "1.0.0", "color": "blue", ...}

# Trigger the update — observe the downtime window in the traffic loop
kubectl apply -f k8s/recreate/deployment-v2.yaml

# Watch all old Pods terminate simultaneously, then new Pods start
kubectl get pods -n mzinga-lab4 -w

# Verify v2
curl -s http://localhost:8080/
# → {"version": "2.0.0", "color": "green", ...}

# Roll back (incurs same downtime again)
kubectl rollout undo deployment/webapp -n mzinga-lab4
kubectl rollout status deployment/webapp -n mzinga-lab4
```

**Traffic loop — macOS / Linux / WSL** (run in a separate terminal before triggering the update):

```sh
while true; do
  response=$(curl -s --max-time 1 http://localhost:8080/ 2>/dev/null)
  if [ -z "$response" ]; then
    echo "$(date +%H:%M:%S) [NO RESPONSE — service down]"
  else
    echo "$(date +%H:%M:%S) $(echo $response | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['version'], d['hostname'])")"
  fi
  sleep 0.5
done
```

**Traffic loop — Windows PowerShell:**

```powershell
while ($true) {
  try {
    $r = curl.exe -s --max-time 1 http://localhost:8080/ | ConvertFrom-Json
    Write-Host "$(Get-Date -Format 'HH:mm:ss') $($r.version) $($r.hostname)"
  } catch {
    Write-Host "$(Get-Date -Format 'HH:mm:ss') [NO RESPONSE — service down]"
  }
  Start-Sleep -Milliseconds 500
}
```

Expected output during the update:

```
10:24:01 1.0.0 webapp-7d8b6c9f4-abc12
10:24:01 1.0.0 webapp-7d8b6c9f4-def34
10:24:02 [NO RESPONSE — service down]
10:24:02 [NO RESPONSE — service down]
10:24:03 [NO RESPONSE — service down]
10:24:07 2.0.0 webapp-5f9c7b8a3-xyz99
10:24:07 2.0.0 webapp-5f9c7b8a3-uvw88
```

---

## Blue-Green Deployment — `k8s/blue-green/`

### `service.yaml`

```yaml
apiVersion: v1
kind: Service
metadata:
  name: webapp
  namespace: mzinga-lab4
spec:
  selector:
    app: webapp
    slot: blue        # change to "green" to switch all traffic to the green deployment
  ports:
    - port: 80
      targetPort: 8080
```

### `blue-deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: webapp-blue
  namespace: mzinga-lab4
  labels:
    app: webapp
    slot: blue
spec:
  replicas: 3
  selector:
    matchLabels:
      app: webapp
      slot: blue
  template:
    metadata:
      labels:
        app: webapp
        slot: blue
        version: v1
    spec:
      containers:
        - name: webapp
          image: mzinga-webapp:1.0.0
          imagePullPolicy: Never
          ports:
            - containerPort: 8080
          env:
            - name: APP_VERSION
              value: "1.0.0"
            - name: APP_COLOR
              value: "blue"
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 2
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests:
              cpu: "50m"
              memory: "32Mi"
            limits:
              cpu: "100m"
              memory: "64Mi"
```

### `green-deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: webapp-green
  namespace: mzinga-lab4
  labels:
    app: webapp
    slot: green
spec:
  replicas: 3
  selector:
    matchLabels:
      app: webapp
      slot: green
  template:
    metadata:
      labels:
        app: webapp
        slot: green
        version: v2
    spec:
      containers:
        - name: webapp
          image: mzinga-webapp:2.0.0
          imagePullPolicy: Never
          ports:
            - containerPort: 8080
          env:
            - name: APP_VERSION
              value: "2.0.0"
            - name: APP_COLOR
              value: "green"
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 2
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests:
              cpu: "50m"
              memory: "32Mi"
            limits:
              cpu: "100m"
              memory: "64Mi"
```

### Apply and Operate

```sh
# Deploy both environments
kubectl apply -f k8s/blue-green/service.yaml
kubectl apply -f k8s/blue-green/blue-deployment.yaml
kubectl apply -f k8s/blue-green/green-deployment.yaml
kubectl rollout status deployment/webapp-blue  -n mzinga-lab4
kubectl rollout status deployment/webapp-green -n mzinga-lab4

# Port-forward and verify blue is active
kubectl port-forward service/webapp 8080:80 -n mzinga-lab4 &
curl -s http://localhost:8080/
# → {"version": "1.0.0", "color": "blue", ...}

# Test green directly via a pod port-forward
GREEN_POD=$(kubectl get pods -n mzinga-lab4 -l slot=green -o jsonpath='{.items[0].metadata.name}')
kubectl port-forward pod/$GREEN_POD 8081:8080 -n mzinga-lab4 &
curl -s http://localhost:8081/
# → {"version": "2.0.0", "color": "green", ...}

# Switch traffic to green (atomic, zero downtime)
kubectl patch service webapp -n mzinga-lab4 \
  -p '{"spec":{"selector":{"app":"webapp","slot":"green"}}}'
curl -s http://localhost:8080/
# → {"version": "2.0.0", "color": "green", ...}

# Roll back (instant, zero downtime)
kubectl patch service webapp -n mzinga-lab4 \
  -p '{"spec":{"selector":{"app":"webapp","slot":"blue"}}}'
curl -s http://localhost:8080/
# → {"version": "1.0.0", "color": "blue", ...}
```

**Windows PowerShell equivalents:**

```powershell
# Test green directly
$GREEN_POD = kubectl get pods -n mzinga-lab4 -l slot=green -o jsonpath='{.items[0].metadata.name}'
Start-Job { kubectl port-forward pod/$GREEN_POD 8081:8080 -n mzinga-lab4 }
Start-Sleep 2
curl.exe -s http://localhost:8081/

# Switch to green
kubectl patch service webapp -n mzinga-lab4 `
  -p '{\"spec\":{\"selector\":{\"app\":\"webapp\",\"slot\":\"green\"}}}'

# Roll back to blue
kubectl patch service webapp -n mzinga-lab4 `
  -p '{\"spec\":{\"selector\":{\"app\":\"webapp\",\"slot\":\"blue\"}}}'
```

---

## Canary Release — `k8s/canary/`

### `service.yaml`

```yaml
apiVersion: v1
kind: Service
metadata:
  name: webapp
  namespace: mzinga-lab4
spec:
  selector:
    app: webapp      # intentionally omits "track" — matches both stable and canary pods
  ports:
    - port: 80
      targetPort: 8080
```

### `stable-deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: webapp-stable
  namespace: mzinga-lab4
  labels:
    app: webapp
    track: stable
spec:
  replicas: 9        # 9 stable + 1 canary = ~10% canary traffic
  selector:
    matchLabels:
      app: webapp
      track: stable
  template:
    metadata:
      labels:
        app: webapp
        track: stable
        version: v1
    spec:
      containers:
        - name: webapp
          image: mzinga-webapp:1.0.0
          imagePullPolicy: Never
          ports:
            - containerPort: 8080
          env:
            - name: APP_VERSION
              value: "1.0.0"
            - name: APP_COLOR
              value: "blue"
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 2
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests:
              cpu: "50m"
              memory: "32Mi"
            limits:
              cpu: "100m"
              memory: "64Mi"
```

### `canary-deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: webapp-canary
  namespace: mzinga-lab4
  labels:
    app: webapp
    track: canary
spec:
  replicas: 1        # 1 canary + 9 stable = ~10% canary traffic; scale up to promote
  selector:
    matchLabels:
      app: webapp
      track: canary
  template:
    metadata:
      labels:
        app: webapp
        track: canary
        version: v2
    spec:
      containers:
        - name: webapp
          image: mzinga-webapp:2.0.0
          imagePullPolicy: Never
          ports:
            - containerPort: 8080
          env:
            - name: APP_VERSION
              value: "2.0.0"
            - name: APP_COLOR
              value: "green"
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 2
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests:
              cpu: "50m"
              memory: "32Mi"
            limits:
              cpu: "100m"
              memory: "64Mi"
```

### Apply and Operate

```sh
# Deploy
kubectl apply -f k8s/canary/service.yaml
kubectl apply -f k8s/canary/stable-deployment.yaml
kubectl apply -f k8s/canary/canary-deployment.yaml
kubectl rollout status deployment/webapp-stable -n mzinga-lab4
kubectl rollout status deployment/webapp-canary -n mzinga-lab4

# Port-forward
kubectl port-forward service/webapp 8080:80 -n mzinga-lab4 &
```

**Verify traffic split — macOS / Linux / WSL:**

```sh
for i in $(seq 1 20); do
  curl -s http://localhost:8080/ | python3 -c "import sys,json; print(json.load(sys.stdin)['version'])"
done | sort | uniq -c
```

**Verify traffic split — Windows PowerShell:**

```powershell
$results = @()
1..20 | ForEach-Object {
  $r = curl.exe -s http://localhost:8080/ | ConvertFrom-Json
  $results += $r.version
}
$results | Group-Object | Select-Object Count, Name
```

Expected: approximately 18 × `1.0.0`, 2 × `2.0.0`.

**Progressive promotion:**

```sh
# ~30% canary
kubectl scale deployment/webapp-stable --replicas=7 -n mzinga-lab4
kubectl scale deployment/webapp-canary --replicas=3 -n mzinga-lab4

# ~50% canary
kubectl scale deployment/webapp-stable --replicas=5 -n mzinga-lab4
kubectl scale deployment/webapp-canary --replicas=5 -n mzinga-lab4

# Full promotion to v2
kubectl scale deployment/webapp-stable --replicas=0  -n mzinga-lab4
kubectl scale deployment/webapp-canary --replicas=10 -n mzinga-lab4
```

**Abort canary (instant rollback):**

```sh
kubectl scale deployment/webapp-canary --replicas=0  -n mzinga-lab4
kubectl scale deployment/webapp-stable --replicas=10 -n mzinga-lab4
```

---

## Clean Up

**macOS / Linux / WSL:**

```sh
pkill -f "kubectl port-forward"
kubectl delete namespace mzinga-lab4
```

**Windows PowerShell:**

```powershell
Stop-Job -Name *
kubectl delete namespace mzinga-lab4
```

---

**Previous:** [09 — Lab 4 Step by Step](09-lab4-step-by-step.md)
