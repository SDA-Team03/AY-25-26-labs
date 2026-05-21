# Lab 4 — Step by Step: Deployment Models with Kubernetes

**Goal:** Deploy a containerised service to a local Kubernetes cluster and practise four production deployment strategies: in-place rolling update, recreate (replace), blue-green deployment, and canary release. At the end of this lab you can explain the trade-offs of each strategy and choose the right one for a given situation.

This lab operates independently of the MZinga infrastructure. It uses a minimal HTTP service (`webapp`) that reports its version number — this makes the deployment strategies observable with a simple `curl` loop, without requiring a running MZinga stack. The patterns demonstrated here apply directly to deploying any component of the MZinga architecture (the email worker, the MZinga API itself, or any future microservice) to a real Kubernetes cluster.

---

## Prerequisites

- Minikube installed and running — see [09b — Minikube Setup](09b-minikube-setup.md)
- Docker installed and accessible from the terminal
- `kubectl` installed and configured to talk to the minikube cluster (`kubectl get nodes` should return the minikube node as `Ready`)

---

## The Demo Service

The service deployed in this lab (`webapp`) is a minimal Python HTTP server with two endpoints:

| Endpoint | Response |
|----------|----------|
| `GET /` | JSON: `{"version": "...", "color": "...", "hostname": "..."}` |
| `GET /health` | `{"status": "ok"}` — used as the readiness and liveness probe |

Version is injected via the `APP_VERSION` environment variable. The `hostname` field returns the Pod name, which makes it easy to see which Pod handled each request during a canary experiment.

The image is built in two variants:
- `mzinga-webapp:1.0.0` — reports `version: "1.0.0"`, `color: "blue"`
- `mzinga-webapp:2.0.0` — reports `version: "2.0.0"`, `color: "green"`

These simulate a real before/after upgrade scenario.

---

## Step 1 — Build the Container Images

Create the required folder and move into the folder.

**macOS / Linux / WSL:**

```sh
mkdir -p mzinga/lab4-k8s
cd mzinga/lab4-k8s
```

**Windows PowerShell:**

```powershell
New-Item -ItemType Directory -Force -Path mzinga\lab4-k8s
cd mzinga\lab4-k8s
```

### 1.1 — Create a Python script to satisfy the requirements

Create a file named `app.py` inside `mzinga/lab4-k8s/`. The script must implement a minimal HTTP server with two endpoints:

**`GET /`** — returns a JSON response containing three fields: the application version, the application colour, and the hostname of the machine handling the request. Version and colour are read from environment variables (`APP_VERSION` and `APP_COLOR`). The hostname is retrieved programmatically at runtime — Python's standard library exposes a function for this in the `socket` module.

**`GET /health`** — returns a JSON response with a single field indicating the service is healthy. This endpoint is called by Kubernetes every few seconds to decide whether the Pod is ready to receive traffic and whether it is still alive. It must always return HTTP 200 as long as the process is running correctly.

Technical aspects to consider:

- **Standard library only.** Python ships with an `http.server` module that is sufficient for this purpose. Avoid adding Flask or any external framework — the Dockerfile should not need to install dependencies, which keeps the image small and the build fast.
- **Reading environment variables.** Use `os.getenv` to read `APP_VERSION` and `APP_COLOR`. Provide sensible defaults (for example `"1.0.0"` and `"blue"`) so the script works even if the variables are absent.
- **JSON responses.** The `json` module (standard library) serialises Python dicts to JSON strings. The HTTP response must include the `Content-Type: application/json` header so clients parse it correctly.
- **HTTP status codes.** Both endpoints should return status `200 OK`. Any other status code on `/health` will cause Kubernetes to mark the Pod as not ready.
- **Hostname.** In a container environment, `socket.gethostname()` returns the container's hostname, which Kubernetes sets to the Pod name. This is how the lab makes it visible which Pod handled each request during canary and rolling experiments.

> If you need working code to compare against, the full implementation is in [09-lab4-code-snippets.md](09-lab4-code-snippets.md).

### 1.2 — Create a Dockerfile to build the image

Create a file named `Dockerfile` in the same `mzinga/lab4-k8s/` directory. The Dockerfile must produce an image that runs `app.py` and embeds the version and colour values so that building with different arguments produces observably different containers.

Requirements:

- The same Dockerfile must produce both the `1.0.0 / blue` image and the `2.0.0 / green` image. The version and colour values are passed in at build time, not hard-coded in the file.
- The image must expose the port the HTTP server listens on.
- The container must start the Python script automatically when it runs — no manual command needed.

Technical aspects to consider:

- **`ARG` vs `ENV`.** Docker `ARG` declares a build-time variable that is available only during the image build (in `RUN`, `COPY`, and similar instructions). `ENV` declares a variable that persists into the running container and is visible to the process via `os.getenv`. To pass a build argument through to the running container you must transfer it explicitly: `ENV VARIABLE=${BUILD_ARG}`. If you only declare `ARG APP_VERSION`, the Python process will not see `APP_VERSION` at runtime.
- **Base image.** Use `python:3.12-slim` as the base. The full `python:3.12` image is several hundred megabytes larger without offering anything useful for this lab. Avoid Alpine (`python:3.12-alpine`) — it uses musl libc which can cause unexpected behaviour with some Python packages.
- **No dependencies to install.** Because `app.py` uses only the standard library, there is no `requirements.txt` and no `pip install` step. The Dockerfile is short: choose the base image, set the working directory, copy the script, declare the build arguments, set the environment variables, expose the port, and set the entrypoint.
- **Layer caching.** Docker caches each instruction as a layer. Instructions that change rarely (base image selection, working directory) should come before instructions that change often (copying source code). For a single-file project this is a minor concern, but the habit matters for larger images.
- **`EXPOSE`.** The `EXPOSE` instruction documents which port the container listens on. It does not publish the port — that is controlled by Kubernetes Services. Documenting it in the Dockerfile makes the intent visible and is required for some tooling to detect the port automatically.

> If you need a working Dockerfile to compare against, it is in [09-lab4-code-snippets.md](09-lab4-code-snippets.md).

### 1.3 — Build v1 and v2

All commands below run from the `mzinga/lab4-k8s/` directory.

**macOS / Linux / WSL:**

```sh
docker build \
  --build-arg APP_VERSION=1.0.0 \
  --build-arg APP_COLOR=blue \
  -t mzinga-webapp:1.0.0 .

docker build \
  --build-arg APP_VERSION=2.0.0 \
  --build-arg APP_COLOR=green \
  -t mzinga-webapp:2.0.0 .
```

**Windows PowerShell:**

```powershell
docker build `
  --build-arg APP_VERSION=1.0.0 `
  --build-arg APP_COLOR=blue `
  -t mzinga-webapp:1.0.0 .

docker build `
  --build-arg APP_VERSION=2.0.0 `
  --build-arg APP_COLOR=green `
  -t mzinga-webapp:2.0.0 .
```

### 1.4 — Load the Images into Minikube

Minikube runs inside a separate container or VM and does not share the host Docker image cache. You must explicitly load locally built images into it.

**macOS / Linux / WSL:**

```sh
minikube image load mzinga-webapp:1.0.0
minikube image load mzinga-webapp:2.0.0
```

**Windows PowerShell:**

```powershell
minikube image load mzinga-webapp:1.0.0
minikube image load mzinga-webapp:2.0.0
```

Verify the images are present inside minikube:

```sh
minikube image ls | grep mzinga-webapp
```

Expected:

```
docker.io/library/mzinga-webapp:1.0.0
docker.io/library/mzinga-webapp:2.0.0
```

> **Why `imagePullPolicy: Never`?** The Kubernetes manifests in this lab set `imagePullPolicy: Never` on all containers. This tells Kubernetes to use the image already present in the node's local cache (loaded via `minikube image load`) rather than trying to pull it from a registry. Without this setting, Kubernetes would attempt to pull from Docker Hub and fail because these images are not published there.

### 1.5 — Create the Namespace

Create a folder named `k8s/` inside `mzinga/lab4-k8s/`. Inside it, create a file named `namespace.yaml`.

A Namespace is a Kubernetes resource that creates a logical partition within the cluster. All resources in this lab — Deployments, Services, Pods — will be created inside this namespace, keeping them isolated from anything else running on the minikube cluster.

Requirements:

- The file must declare a Kubernetes `Namespace` resource named `mzinga-lab4`.
- This is the name all subsequent `kubectl` commands in this lab will reference with `-n mzinga-lab4`.

Technical aspects to consider:

- Every Kubernetes manifest requires at minimum four top-level fields: `apiVersion`, `kind`, `metadata`, and usually `spec`. A `Namespace` is one of the few resource types that requires no `spec` — the name is the entire definition.
- Core Kubernetes resource types (`Namespace`, `Service`, `Pod`, `ConfigMap`) use `apiVersion: v1`. Workload resources like `Deployment` belong to the `apps` group and use `apiVersion: apps/v1`.
- The `metadata.name` field is the canonical identifier for any Kubernetes resource. For a Namespace, it becomes the namespace name used in every `-n` flag throughout the lab.

> If you need the YAML to compare against, it is in [09-lab4-code-snippets.md](09-lab4-code-snippets.md).

Once the file is ready, apply it and verify:

```sh
kubectl apply -f k8s/namespace.yaml
kubectl get namespace mzinga-lab4
```

---

## Step 2 — Deploy the Initial Service (v1)

Before practising upgrade strategies, establish the baseline: v1 running and healthy.

### 2.1 — Create the Rolling Manifests

Create a directory `k8s/rolling/` and create two YAML files inside it.

**`service.yaml`**

A Service is the stable network endpoint in front of the Pods. Pods are ephemeral — their IP addresses change every time they restart — but the Service IP is stable. Clients connect to the Service, not to individual Pods.

Requirements:

- Kind: `Service`
- A selector that matches the label(s) assigned to Pods by the Deployment
- A port mapping: the Service listens on port `80` and forwards traffic to port `8080` on each Pod (the port `app.py` listens on)

Technical aspects to consider:

- `spec.selector` is how a Service finds its Pods. Any Pod in the same namespace that carries all the listed labels is included in the Service's endpoint list. The key-value pairs here must match exactly what the Deployment places on its Pod template.
- `spec.ports[].port` is the port clients connect to on the Service. `spec.ports[].targetPort` is the port on the container. These can differ — here the Service exposes port 80 while the application uses 8080.
- The default Service type is `ClusterIP`, which makes the Service reachable only within the cluster. This is correct for this lab — external access is handled by `kubectl port-forward`.

**`deployment-v1.yaml`**

A Deployment declares the desired state for a set of identical Pods and manages their lifecycle — creating, replacing, and scaling Pods to match the declared spec.

Requirements:

- Kind: `Deployment`, in the `mzinga-lab4` namespace
- 3 replicas using image `mzinga-webapp:1.0.0` with `imagePullPolicy: Never`
- Environment variables `APP_VERSION: "1.0.0"` and `APP_COLOR: "blue"` injected into the container
- Rolling update strategy with `maxUnavailable: 1` and `maxSurge: 1`
- A readiness probe on `GET /health` — Kubernetes routes traffic to a Pod only once this probe passes
- A liveness probe on `GET /health` — Kubernetes restarts a Pod if this probe begins failing
- Pod labels that match the selector defined in `service.yaml`

Technical aspects to consider:

- `spec.selector.matchLabels` and `spec.template.metadata.labels` must be identical — this is how the Deployment knows which Pods it owns. The Service's `spec.selector` must also reference the same labels.
- The readiness and liveness probes both use `httpGet` against `/health` on the container port (8080). `initialDelaySeconds` gives the container time to start before Kubernetes begins probing; `periodSeconds` controls the check frequency.
- `spec.strategy.type: RollingUpdate` with `rollingUpdate.maxUnavailable` and `rollingUpdate.maxSurge` controls how many Pods may be unavailable or in excess during the update. Setting `maxUnavailable: 1` means no more than one Pod is down at any moment; `maxSurge: 1` means one extra Pod is created before an old one is removed.
- `imagePullPolicy: Never` must be set explicitly on every container in this lab (see the note above in step 1.4).

> If you need the YAML to compare against, both files are in [09-lab4-code-snippets.md](09-lab4-code-snippets.md).

Once both files are ready, apply them:

```sh
kubectl apply -f k8s/rolling/service.yaml
kubectl apply -f k8s/rolling/deployment-v1.yaml
```

### 2.2 — Wait for Pods to Become Ready

**macOS / Linux / WSL:**

```sh
kubectl rollout status deployment/webapp -n mzinga-lab4
```

**Windows PowerShell:**

```powershell
kubectl rollout status deployment/webapp -n mzinga-lab4
```

Expected:

```
deployment "webapp" successfully rolled out
```

### 2.3 — Verify the Service

Open a port-forward to the Service and query it:

**macOS / Linux / WSL:**

```sh
kubectl port-forward service/webapp 8080:80 -n mzinga-lab4 &
curl -s http://localhost:8080/
```

**Windows PowerShell:**

```powershell
Start-Job { kubectl port-forward service/webapp 8080:80 -n mzinga-lab4 }
Start-Sleep 2
curl.exe -s http://localhost:8080/
```

Expected response:

```json
{"version": "1.0.0", "color": "blue", "hostname": "webapp-xxxxxxxxx-xxxxx"}
```

Check that all three Pods are running:

```sh
kubectl get pods -n mzinga-lab4
```

---

## Step 3 — In-Place Rolling Upgrade

### What Is It

A **rolling update** (also called in-place upgrade) replaces Pods one by one with the new version. Kubernetes takes down one old Pod, waits for a new Pod to pass its readiness probe, then takes down another old Pod, and so on — until all Pods are running the new version. At no point is the service fully offline.

This is Kubernetes' default update strategy, controlled by two parameters on the Deployment:

- `maxUnavailable` — the maximum number of Pods that can be unavailable during the update. Setting this to `0` ensures the service never drops below full capacity, but requires at least `maxSurge` additional nodes.
- `maxSurge` — the maximum number of Pods that can be created above the desired replica count during the update. Setting this to `1` means one extra Pod is created before the first old one is removed.

### 3.1 — Start a Traffic Loop (Keep This Terminal Open)

In a separate terminal, run a loop that continuously queries the service. This lets you observe responses from both v1 and v2 during the transition.

**macOS / Linux / WSL:**

```sh
while true; do curl -s http://localhost:8080/ | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['version'], d['hostname'])"; sleep 0.5; done
```

**Windows PowerShell:**

```powershell
while ($true) {
  $r = curl.exe -s http://localhost:8080/ | ConvertFrom-Json
  Write-Host "$($r.version) $($r.hostname)"
  Start-Sleep -Milliseconds 500
}
```

You should see lines like:

```
1.0.0 webapp-7d8b6c9f4-abc12
1.0.0 webapp-7d8b6c9f4-def34
1.0.0 webapp-7d8b6c9f4-ghi56
```

### 3.2 — Create the v2 Deployment and Trigger the Rolling Update

Create `deployment-v2.yaml` in the same `k8s/rolling/` directory.

This manifest has the same structure as `deployment-v1.yaml`. The only differences are the image tag and the environment variable values:

- Image tag: `mzinga-webapp:2.0.0`
- `APP_VERSION`: `"2.0.0"`
- `APP_COLOR`: `"green"`
- `metadata.name` must be **identical** to `deployment-v1.yaml`

Technical aspects to consider:

- When you apply a Deployment manifest whose name already exists in the namespace, Kubernetes updates the existing Deployment's spec rather than creating a second one. If the Pod template changed (image tag, env var), Kubernetes creates a new ReplicaSet and begins replacing Pods according to the rollout strategy configured in the manifest.
- Keeping the same Deployment name is what triggers the update. If you accidentally use a different name, you will create a second independent Deployment rather than upgrading the first.

> The file is in [09-lab4-code-snippets.md](09-lab4-code-snippets.md) if you need it.

Once the file is ready, apply it:

```sh
kubectl apply -f k8s/rolling/deployment-v2.yaml
```

Or update the image imperatively (equivalent):

```sh
kubectl set image deployment/webapp webapp=mzinga-webapp:2.0.0 -n mzinga-lab4
```

### 3.3 — Observe the Rollout

In another terminal, watch the Pod list:

```sh
kubectl get pods -n mzinga-lab4 -w
```

You will see:
- New Pods (with a different hash in their name) entering `Pending` then `ContainerCreating` then `Running`
- Old Pods entering `Terminating`
- The transition happens one Pod at a time, controlled by `maxUnavailable` and `maxSurge`

In the traffic loop terminal, you will see responses switching from `1.0.0` to `2.0.0` as each new Pod becomes ready and starts receiving traffic:

```
1.0.0 webapp-7d8b6c9f4-abc12
2.0.0 webapp-5f9c7b8a3-xyz99   ← new Pod receiving traffic
1.0.0 webapp-7d8b6c9f4-def34
2.0.0 webapp-5f9c7b8a3-xyz99
```

During this period, both versions are live simultaneously. This is the key trade-off of the rolling strategy.

### 3.4 — Verify Completion

```sh
kubectl rollout status deployment/webapp -n mzinga-lab4
curl -s http://localhost:8080/
```

All responses should now show `2.0.0`.

### 3.5 — Roll Back

Kubernetes keeps a history of Deployment revisions. To return to v1:

```sh
kubectl rollout undo deployment/webapp -n mzinga-lab4
kubectl rollout status deployment/webapp -n mzinga-lab4
```

Observe the traffic loop: it transitions back to `1.0.0` through the same rolling mechanism.

### Pros and Cons — Rolling Update

**Pros:**
- Zero additional infrastructure cost — no extra replicas required beyond `maxSurge` (one temporary Pod)
- Built into Kubernetes with no additional tooling
- Automatic rollback via `kubectl rollout undo`
- Gradual exposure — if the new version crashes immediately, only some Pods are affected before Kubernetes pauses the rollout

**Cons:**
- **Both versions are live simultaneously during the transition.** If the new version has a different database schema, message format, or API contract, requests may be routed to either version — causing inconsistency
- Traffic split is not controlled — you cannot direct only internal users to the new version
- Rollback requires re-running a full rolling replacement (takes the same time as the original update)
- If `maxUnavailable` is `0` and the new version hangs on the readiness probe, the rollout stalls indefinitely

**When to choose rolling update:**
- The change is backwards compatible (same API contract, same message format, no schema changes)
- You do not need to test the new version on a subset of traffic before full rollout
- Simplicity and low operational overhead are more important than fine-grained traffic control

---

## Step 4 — Recreate (Replace) Strategy

### What Is It

The `Recreate` strategy terminates **all** existing Pods simultaneously before creating any Pods running the new version. Unlike `RollingUpdate`, there is no overlap period: the service goes completely offline from the moment the last old Pod is terminated until the first new Pod passes its readiness probe.

This is the appropriate strategy when v1 and v2 **cannot coexist**. Typical situations:

- **Destructive schema migration.** v2 drops or renames a database column that v1 actively reads. Running both versions simultaneously would cause v1 to fail on every request until it is fully gone — corrupted state or cascading errors.
- **Exclusive resource ownership.** The service holds a distributed lock, a licensed hardware allocation, or a singleton file that only one active version can hold. Attempting to start v2 while v1 still owns the resource would either fail or force v1 to relinquish it unexpectedly.
- **Incompatible queue message format.** The service consumes a queue where v1 and v2 interpret the same messages differently. Mixed consumption — some Pods on v1, some on v2 — produces unpredictable and potentially irreversible results.
- **Incompatible internal protocol.** v1 and v2 speak different wire protocol versions to a shared dependency (e.g. a gRPC server that dropped v1's protocol in the new release). Mixed Pods would split traffic between working and failing protocol versions.

In all these cases, the guarantee that only one version ever runs simultaneously is worth accepting a planned downtime window. The alternative that eliminates the downtime — blue-green (Step 5) — requires running both environments simultaneously, which these scenarios explicitly forbid.

### 4.1 — Clean Up Rolling Resources

```sh
kubectl delete -f k8s/rolling/deployment-v1.yaml
kubectl delete -f k8s/rolling/service.yaml
```

Kill any running port-forward:

**macOS / Linux / WSL:**

```sh
pkill -f "kubectl port-forward"
```

**Windows PowerShell:**

```powershell
Stop-Job -Name *
```

### 4.2 — Create the Recreate Manifests and Deploy v1

Create a directory `k8s/recreate/` and create two YAML files inside it.

**`service.yaml`**

The Service for the Recreate scenario is functionally identical to `k8s/rolling/service.yaml` — same selector, same port mapping. You may copy it directly.

**`deployment-v1.yaml`**

This Deployment is structurally the same as `k8s/rolling/deployment-v1.yaml` with one critical difference: the update strategy.

Requirements:

- Same image (`mzinga-webapp:1.0.0`), replicas (3), namespace, environment variables, probes, and pod labels as the rolling v1 Deployment
- `metadata.name` must be `webapp` — the same name used in all other steps
- Strategy must be `type: Recreate`

Technical aspects to consider:

- `strategy.type: Recreate` requires no additional fields. Unlike `RollingUpdate`, there is no `rollingUpdate` stanza — the strategy type itself is the entire configuration.
- When this Deployment is updated, Kubernetes terminates all existing Pods before creating any new ones. There is no overlap period, which is why the service goes offline during the transition.

> The files are in [09-lab4-code-snippets.md](09-lab4-code-snippets.md) if you need them.

Once both files are ready, apply them and verify v1 is serving:

```sh
kubectl apply -f k8s/recreate/service.yaml
kubectl apply -f k8s/recreate/deployment-v1.yaml
kubectl rollout status deployment/webapp -n mzinga-lab4
```

Port-forward and verify v1 is serving:

```sh
kubectl port-forward service/webapp 8080:80 -n mzinga-lab4 &
curl -s http://localhost:8080/
```

Expected: `{"version": "1.0.0", "color": "blue", ...}`

### 4.3 — Start a Traffic Loop

In a separate terminal, run a request loop that prints a timestamp and handles connection failures explicitly. Unlike the rolling update loop, you will observe a hard gap — several consecutive failures — during the transition instead of a gradual version mix.

**macOS / Linux / WSL:**

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

**Windows PowerShell:**

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

### 4.4 — Create the v2 Recreate Deployment and Observe the Downtime

Create `deployment-v2.yaml` in `k8s/recreate/`.

Requirements:

- Same structure as `k8s/recreate/deployment-v1.yaml` — including `strategy.type: Recreate`
- Updated image tag (`mzinga-webapp:2.0.0`), `APP_VERSION` (`"2.0.0"`), and `APP_COLOR` (`"green"`)
- `metadata.name` must be identical to `deployment-v1.yaml` — this is what triggers the Recreate replacement of v1

> The file is in [09-lab4-code-snippets.md](09-lab4-code-snippets.md) if you need it.

In another terminal, start watching Pods:

```sh
kubectl get pods -n mzinga-lab4 -w
```

Apply the v2 Deployment:

```sh
kubectl apply -f k8s/recreate/deployment-v2.yaml
```

In the Pod-watch terminal you will see all three v1 Pods enter `Terminating` simultaneously — Kubernetes issues the graceful shutdown signal to all of them at once. No new v2 Pods are created until every v1 Pod has fully terminated.

In the traffic loop terminal, you will see a clear downtime window with a sharp before-and-after boundary:

```
10:24:01 1.0.0 webapp-7d8b6c9f4-abc12
10:24:01 1.0.0 webapp-7d8b6c9f4-def34
10:24:02 [NO RESPONSE — service down]    ← v1 Pods terminating
10:24:02 [NO RESPONSE — service down]
10:24:03 [NO RESPONSE — service down]    ← v2 Pods not yet ready
10:24:07 2.0.0 webapp-5f9c7b8a3-xyz99   ← all traffic now on v2
10:24:07 2.0.0 webapp-5f9c7b8a3-uvw88
```

The downtime duration equals: old Pod graceful shutdown time (`terminationGracePeriodSeconds`, default 30 s, but short for this toy service) + new Pod start time + readiness probe initial delay. In production services with longer startup sequences this window can extend to minutes.

### 4.5 — Verify the New Version

```sh
kubectl rollout status deployment/webapp -n mzinga-lab4
curl -s http://localhost:8080/
```

Expected: `{"version": "2.0.0", "color": "green", ...}`

### 4.6 — Roll Back

Rolling back with `Recreate` incurs the same downtime as the original update — there is no shortcut:

```sh
kubectl rollout undo deployment/webapp -n mzinga-lab4
kubectl rollout status deployment/webapp -n mzinga-lab4
```

Observe the traffic loop: another downtime gap, then responses from `1.0.0`. This is the fundamental cost difference between Recreate and blue-green: blue-green rollback is a one-second selector patch; Recreate rollback is another full replace cycle with the same downtime window.

### Pros and Cons — Recreate

**Pros:**
- **Guarantees only one version runs at any point** — the only viable strategy when v1 and v2 truly cannot coexist
- Simple to configure: a single field change in the Deployment spec (`strategy.type: Recreate`)
- Predictable cutover point — the transition moment is well defined and visible in the event log
- No residual old Pods that could interfere with the new version's exclusive resources
- Minimal extra resource cost — never more than the usual replica count

**Cons:**
- **Planned downtime is inevitable** — there is always a gap between all old Pods terminating and the first new Pod becoming ready
- Downtime scales with `terminationGracePeriodSeconds` and application startup time — can be minutes for slow-starting services
- All-or-nothing: no ability to validate the new version before it receives 100% of traffic
- Rollback incurs the same downtime again
- Users must either be informed of the maintenance window or requests must be queued externally

**When to choose recreate:**
- v1 and v2 genuinely cannot coexist (destructive schema change, exclusive resource, incompatible protocol)
- A maintenance window exists and downtime is acceptable to stakeholders
- Blue-green is not feasible because the resource that v2 needs exclusively cannot even be initialised while v1 holds it
- The service is internal or low-traffic enough that a brief outage has minimal user impact

---

## Step 5 — Blue-Green Deployment

### What Is It

In a **blue-green deployment**, two complete environments run in parallel:
- **Blue** — the current production version (v1)
- **Green** — the new version (v2), deployed and verified before receiving any user traffic

The Service selector points at one environment at a time. Switching traffic is a single atomic operation — one patch to the Service — with no intermediate state where both versions are serving user requests simultaneously.

```
Before switch:
  Service (selector: slot=blue) → Blue Pods (v1)
                                   Green Pods (v2)  ← idle, warmed up, tested

After switch:
  Service (selector: slot=green) → Green Pods (v2)
                                    Blue Pods (v1)  ← idle, kept for instant rollback
```

**Blue-green vs Recreate for breaking changes:** both guarantee that only one version serves traffic at any moment. The difference is that blue-green pre-starts v2 while v1 is still running (in isolated Deployments, never receiving traffic), then switches atomically — achieving zero downtime. This is only possible when v2 can be started and warmed up in parallel with v1. If the incompatibility prevents even starting v2 alongside v1 (e.g. an exclusive distributed lock that v2 tries to acquire at startup), Recreate is the only option.

### 5.1 — Clean Up Recreate Resources

Before starting, remove the Recreate Deployment and Service (the blue-green ones use different Deployment names to avoid conflicts):

```sh
kubectl delete -f k8s/recreate/deployment-v2.yaml
kubectl delete -f k8s/recreate/service.yaml
```

If you still have a port-forward running, kill it:

**macOS / Linux / WSL:**

```sh
pkill -f "kubectl port-forward"
```

**Windows PowerShell:**

```powershell
Stop-Job -Name *
```

### 5.2 — Create the Blue-Green Manifests

Create a directory `k8s/blue-green/` and create three YAML files inside it.

**`blue-deployment.yaml`**

Requirements:

- Named `webapp-blue` (in the `mzinga-lab4` namespace)
- 3 replicas, image `mzinga-webapp:1.0.0`, `APP_VERSION: "1.0.0"`, `APP_COLOR: "blue"`, `imagePullPolicy: Never`
- Readiness and liveness probes on `/health`
- Pod labels must include `app: webapp` **and** `slot: blue`

**`green-deployment.yaml`**

Requirements:

- Named `webapp-green`
- 3 replicas, image `mzinga-webapp:2.0.0`, `APP_VERSION: "2.0.0"`, `APP_COLOR: "green"`, `imagePullPolicy: Never`
- Same probes as blue
- Pod labels must include `app: webapp` **and** `slot: green`

**`service.yaml`**

Requirements:

- Selector must include **both** `app: webapp` **and** `slot: blue`
- Port mapping: `80` → `8080`

Technical aspects to consider:

- The `slot` label is the switching mechanism. By including it in the Service selector, the Service matches only Pods whose `slot` value matches. Pods from `webapp-blue` carry `slot: blue`; Pods from `webapp-green` carry `slot: green`. At any moment the Service routes traffic to exactly one set of Pods.
- If the Service selector contained only `app: webapp`, it would match all Pods from both Deployments simultaneously — making this a canary-style split rather than a blue-green switch.
- The two Deployments use different names (`webapp-blue`, `webapp-green`) and are never modified after creation. The traffic switch is made entirely by patching the Service selector.

> The files are in [09-lab4-code-snippets.md](09-lab4-code-snippets.md) if you need them.

Once all three files are ready, apply them and wait for both Deployments to be ready:

```sh
kubectl apply -f k8s/blue-green/blue-deployment.yaml
kubectl apply -f k8s/blue-green/green-deployment.yaml
kubectl apply -f k8s/blue-green/service.yaml
```

Wait for both Deployments to be ready:

```sh
kubectl rollout status deployment/webapp-blue -n mzinga-lab4
kubectl rollout status deployment/webapp-green -n mzinga-lab4
```

### 5.3 — Verify the Active Slot

The Service initially points at blue. Start a port-forward and verify:

```sh
kubectl port-forward service/webapp 8080:80 -n mzinga-lab4 &
curl -s http://localhost:8080/
```

Expected: `{"version": "1.0.0", "color": "blue", ...}`

### 5.4 — Verify Green Before Switching

Test the green Deployment directly (bypassing the Service) by port-forwarding to one of its Pods:

**macOS / Linux / WSL:**

```sh
GREEN_POD=$(kubectl get pods -n mzinga-lab4 -l slot=green -o jsonpath='{.items[0].metadata.name}')
kubectl port-forward pod/$GREEN_POD 8081:8080 -n mzinga-lab4 &
curl -s http://localhost:8081/
```

**Windows PowerShell:**

```powershell
$GREEN_POD = kubectl get pods -n mzinga-lab4 -l slot=green -o jsonpath='{.items[0].metadata.name}'
Start-Job { kubectl port-forward pod/$GREEN_POD 8081:8080 -n mzinga-lab4 }
Start-Sleep 2
curl.exe -s http://localhost:8081/
```

Expected: `{"version": "2.0.0", "color": "green", ...}` — the green environment is ready and tested, but not yet serving user traffic.

Kill the green Pod port-forward when done.

### 5.5 — Switch Traffic to Green

The switch is a single patch to the Service selector:

```sh
kubectl patch service webapp -n mzinga-lab4 \
  -p '{"spec":{"selector":{"app":"webapp","slot":"green"}}}'
```

Immediately query the Service:

```sh
curl -s http://localhost:8080/
```

Expected: `{"version": "2.0.0", "color": "green", ...}`. The switch is instantaneous — no rolling transition, no downtime gap.

If you run the traffic loop from Step 3.1, all responses switch from v1 to v2 at the same moment. There is no period where both versions are live in the Service.

### 5.6 — Instant Rollback

If the green version causes issues, revert by switching the selector back:

```sh
kubectl patch service webapp -n mzinga-lab4 \
  -p '{"spec":{"selector":{"app":"webapp","slot":"blue"}}}'
curl -s http://localhost:8080/
```

Expected: `{"version": "1.0.0", "color": "blue", ...}`. Rollback takes under a second — no downtime, no re-deploy cycle.

### Pros and Cons — Blue-Green

**Pros:**
- **Zero traffic to the new version until you explicitly switch** — both versions are never serving user traffic simultaneously
- **Instant rollback** — one patch command returns to the previous version with no delay and no downtime
- Safe for breaking changes when v2 can be initialised in parallel with v1: database migrations can be run while green is idle, then traffic switched after migration completes
- The new version is fully warmed up and tested before it receives any user traffic
- No risk of the new version destabilising the old version (completely isolated Deployments)

**Cons:**
- **Double resource usage** — both environments run at full capacity simultaneously. For a 10-replica Deployment, you run 20 replicas during the transition
- The switch is all-or-nothing — you cannot direct 10% of traffic to green to validate it at production scale before full cutover
- Cannot be used when the incompatibility prevents starting v2 while v1 is running (use Recreate in that case)
- Slightly higher operational complexity: you manage two Deployments per service instead of one

**When to choose blue-green:**
- The change includes a breaking API or schema change, but v2 can be started in parallel with v1 without conflict
- You need instant, reliable, zero-downtime rollback
- You need to perform smoke tests on the new version at full replica count before it receives user traffic
- Resource cost of running two full environments is acceptable

---

## Step 6 — Canary Release

### What Is It

A **canary release** (named after the "canary in a coal mine" — an early warning system) routes a controlled fraction of production traffic to the new version while the majority still runs on the stable version. This allows you to observe the new version's behaviour on real traffic — error rates, latency, business metrics — before committing to a full rollout.

In Kubernetes, the simplest canary implementation uses **two Deployments with a shared Service**. The Service selector matches Pods from both Deployments. Traffic is distributed proportionally to the number of ready Pods:

```
10 total Pods: 9 stable (v1) + 1 canary (v2) → ~10% of traffic to canary

Gradually increase canary replicas:
  9 stable + 1 canary → 10% canary
  7 stable + 3 canary → 30% canary
  5 stable + 5 canary → 50% canary
  0 stable + 10 canary → 100% (promotion complete)
```

### 6.1 — Clean Up Blue-Green Resources

```sh
kubectl delete -f k8s/blue-green/
```

If you have a port-forward running, kill it:

**macOS / Linux / WSL:**

```sh
pkill -f "kubectl port-forward"
```

**Windows PowerShell:**

```powershell
Stop-Job -Name *
```

### 6.2 — Create the Canary Manifests

Create a directory `k8s/canary/` and create three YAML files inside it.

**`stable-deployment.yaml`**

Requirements:

- Named `webapp-stable`
- **9 replicas**, image `mzinga-webapp:1.0.0`, `APP_VERSION: "1.0.0"`, `APP_COLOR: "blue"`, `imagePullPolicy: Never`
- Readiness and liveness probes on `/health`
- Pod labels must include `app: webapp` and `track: stable`

**`canary-deployment.yaml`**

Requirements:

- Named `webapp-canary`
- **1 replica**, image `mzinga-webapp:2.0.0`, `APP_VERSION: "2.0.0"`, `APP_COLOR: "green"`, `imagePullPolicy: Never`
- Same probes as stable
- Pod labels must include `app: webapp` and `track: canary`

**`service.yaml`**

Requirements:

- Selector must include **only** `app: webapp` — it must **not** include `track`
- Port mapping: `80` → `8080`

Technical aspects to consider:

- The canary mechanism relies on the Service matching Pods from both Deployments at once. By selecting only `app: webapp`, both `webapp-stable` Pods and `webapp-canary` Pods are included in the Service's endpoint list simultaneously. Traffic is distributed in proportion to the number of ready Pods: with 9 stable + 1 canary, approximately 10% of requests reach the canary.
- This is the key structural difference from blue-green: the blue-green Service adds a second label (`slot`) to its selector to isolate exactly one Deployment; the canary Service intentionally omits any distinguishing label so both Deployments receive traffic.
- The `track` label exists on the Pods but is not used by the Service. It is useful for monitoring — `kubectl get pods -l track=canary` shows only the canary Pods — but does not affect routing.
- The 9:1 replica ratio is what produces the ~10% canary traffic fraction. You will increase this ratio progressively in step 6.5.

> The files are in [09-lab4-code-snippets.md](09-lab4-code-snippets.md) if you need them.

Once all three files are ready, apply them and wait for both Deployments:

```sh
kubectl apply -f k8s/canary/service.yaml
kubectl apply -f k8s/canary/stable-deployment.yaml
kubectl apply -f k8s/canary/canary-deployment.yaml
```

Wait for both Deployments:

```sh
kubectl rollout status deployment/webapp-stable -n mzinga-lab4
kubectl rollout status deployment/webapp-canary -n mzinga-lab4
```

### 6.3 — Verify the Traffic Split

Start a port-forward:

```sh
kubectl port-forward service/webapp 8080:80 -n mzinga-lab4 &
```

Run 20 requests and count responses by version:

**macOS / Linux / WSL:**

```sh
for i in $(seq 1 20); do
  curl -s http://localhost:8080/ | python3 -c "import sys,json; print(json.load(sys.stdin)['version'])"
done | sort | uniq -c
```

**Windows PowerShell:**

```powershell
$results = @()
1..20 | ForEach-Object {
  $r = curl.exe -s http://localhost:8080/ | ConvertFrom-Json
  $results += $r.version
}
$results | Group-Object | Select-Object Count, Name
```

With 9 stable + 1 canary = 10 Pods, you expect approximately 18 responses from `1.0.0` and 2 from `2.0.0`. The exact count varies because Kubernetes' load balancing is not precisely round-robin across all Pods.

```
 18 1.0.0
  2 2.0.0
```

### 6.4 — Observe Per-Pod Routing

Each response includes the `hostname` field (the Pod name), which lets you see exactly which Pod served each request. The canary Pod names contain `webapp-canary-`:

**macOS / Linux / WSL:**

```sh
for i in $(seq 1 10); do
  curl -s http://localhost:8080/ | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"{d['version']} {d['hostname']}\")"
done
```

### 6.5 — Gradually Increase the Canary

If the canary is behaving well (low error rate, acceptable latency), increase its share:

```sh
# Increase canary to ~30%: 7 stable + 3 canary = 10 total
kubectl scale deployment/webapp-stable --replicas=7 -n mzinga-lab4
kubectl scale deployment/webapp-canary --replicas=3 -n mzinga-lab4

# Increase to ~50%
kubectl scale deployment/webapp-stable --replicas=5 -n mzinga-lab4
kubectl scale deployment/webapp-canary --replicas=5 -n mzinga-lab4
```

Run the 20-request test again after each change to confirm the proportion shifts.

### 6.6 — Promote: Full Rollout to v2

Once you are confident, scale stable to 0 and canary to the full desired replica count:

```sh
kubectl scale deployment/webapp-stable --replicas=0 -n mzinga-lab4
kubectl scale deployment/webapp-canary --replicas=10 -n mzinga-lab4
```

All traffic is now on v2.

### 6.7 — Abort: Rollback the Canary

If the canary shows problems (errors, latency spikes), remove it entirely and return to stable:

```sh
kubectl scale deployment/webapp-canary --replicas=0 -n mzinga-lab4
kubectl scale deployment/webapp-stable --replicas=10 -n mzinga-lab4
```

All traffic returns to v1 immediately. The canary Deployment still exists but has 0 replicas — you can delete it when ready.

### Pros and Cons — Canary Release

**Pros:**
- **Controlled exposure** — you choose what fraction of users sees the new version
- **Production validation** — the new version is tested under real traffic, not synthetic load
- **Fast, targeted rollback** — scale the canary to 0; stable absorbs all traffic within seconds
- Reduces the blast radius of a bad release: only canary users are affected before you abort
- Can be combined with feature flags or session stickiness (with an ingress controller) for more precise targeting

**Cons:**
- **Both versions are live simultaneously** — same as rolling update, this is unsafe for breaking schema or API changes
- Traffic proportion is coarse-grained by replica count — you cannot achieve 1% without a very large number of total replicas (or an ingress controller with weighted routing)
- Requires observability to be useful: without metrics comparing error rates and latency between stable and canary, you are flying blind
- More complex to manage: two Deployments, manual scaling progression, decision criteria for promotion
- Session stickiness requires an ingress controller (not covered in this lab) — basic Kubernetes Services do not guarantee a user always hits the same Pod

**When to choose canary:**
- You have observability in place (metrics, traces) and can measure whether the new version is behaving correctly
- The change is backwards compatible (safe for two versions to be live simultaneously)
- You want to validate performance or business metrics at real production scale before full rollout
- The risk of the change is high enough to justify the operational complexity

---

## Step 7 — Strategy Comparison and Decision Framework

### Side-by-Side Comparison

| Factor | Rolling Update | Recreate | Blue-Green | Canary |
|--------|---------------|---------|------------|--------|
| **Both versions live simultaneously** | Yes, during transition | **No — never** | No | Yes, during transition |
| **Downtime** | Near-zero (with readinessProbe) | **Yes — planned** | Zero | Zero |
| **Rollback mechanism** | `kubectl rollout undo` | `kubectl rollout undo` | Patch Service selector | Scale canary to 0 |
| **Rollback speed** | Minutes (re-rolls all Pods) | **Minutes + downtime** | Seconds | Seconds |
| **Extra resource cost** | `maxSurge` Pods only (~10%) | **None** | 2× full replica count | Proportional to canary size |
| **Traffic control** | None (Kubernetes decides) | None | Binary: all-or-nothing | Granular: by replica ratio |
| **Breaking changes safe?** | No | **Yes — with downtime** | Yes — zero downtime | No |
| **v2 must start alongside v1?** | Yes | **No** | Yes | Yes |
| **Requires observability** | No | No | No | Yes (to make promotion decision) |
| **Operational complexity** | Low | **Low** | Medium | Medium-High |
| **Time to full rollout** | Minutes | Minutes | Immediate after switch | Hours to days (progressive) |

### Constraints That Drive the Choice

**Database or schema changes:**
The most important constraint. If v2 adds a non-nullable column, renames a field, or changes a message format, v1 and v2 cannot run simultaneously or data corruption/errors occur.
- If v2 can be started while v1 is still running (e.g. a column is added but not yet required by v1): use **blue-green** — migrate the schema while green is idle, switch, decommission blue
- If v2 cannot start alongside v1 (e.g. v2 drops a column v1 requires, causing v1 errors the moment the migration runs): use **Recreate** — terminate v1 first, migrate, start v2
- Never use rolling update or canary for any breaking schema change

**v2 cannot even initialise alongside v1:**
This is the critical constraint that distinguishes Recreate from Blue-Green. If v2 attempts to acquire an exclusive lock, port, or resource at startup, and v1 holds it, v2 will fail to start. Blue-Green cannot work in this scenario because it requires v2 to warm up fully before traffic is switched. Recreate is the only option.

**Rollback time requirement:**
If an outage costs thousands of euros per minute, rollback speed matters:
- **Blue-green** offers the fastest, most reliable rollback with zero downtime (one command, one second)
- **Canary** rollback is also fast (scale to 0) and zero-downtime, but requires you to have detected the problem first
- **Rolling update** rollback re-runs the full rolling replacement — minutes, not seconds, but no downtime
- **Recreate** rollback is a full replace cycle — minutes plus another full downtime window

**Observability maturity:**
Canary is only valuable if you can measure whether the canary is behaving correctly. Without metrics comparing error rates and latency between stable and canary, you gain no safety from the canary approach. If your service lacks the instrumentation from Lab 3, canary is no better than a rolling update with extra steps.

**Resource budget:**
If your cluster runs at high utilisation, blue-green may not be feasible — it requires double the replicas during the transition. Rolling update has minimal overhead (`maxSurge`). Canary scales proportionally. Recreate uses no extra resources at all.

**Traffic volume:**
For statistically meaningful canary validation, you need enough traffic hitting the canary to detect anomalies. At 10% canary on a service handling 100 requests per minute, only 10 requests per minute hit the canary — a statistically weak signal. At 100,000 requests per minute, 10% gives you a strong signal within seconds. If traffic is low, blue-green with thorough pre-switch testing may be more effective.

**Team experience:**
Rolling update is built into Kubernetes and requires no additional tooling or procedures. Recreate adds one field change and a maintenance window procedure. Blue-green requires managing two Deployments and a manual switch procedure. Canary requires two Deployments, a progressive scaling procedure, and defined promotion criteria. Start with rolling update, introduce Recreate when you have a breaking change and a maintenance window, graduate to blue-green when you need zero downtime for breaking changes, and introduce canary when you have the observability to act on its signals.

---

## What You Have Built

| Strategy | Kubernetes mechanism | Resources created |
|----------|---------------------|-------------------|
| Rolling update | `strategy.type: RollingUpdate` with `maxUnavailable` and `maxSurge` | 1 Deployment, 1 Service |
| Recreate | `strategy.type: Recreate` | 1 Deployment, 1 Service |
| Blue-green | Two Deployments, Service `selector` patched between `slot: blue` and `slot: green` | 2 Deployments, 1 Service |
| Canary | Two Deployments sharing one Service selector (`app: webapp` only) | 2 Deployments, 1 Service |

| Concept practised | How |
|-------------------|-----|
| Readiness probe gates traffic | Observed during rolling update — no traffic to new Pod until `/health` returns 200 |
| Simultaneous version coexistence | Observed during rolling update and canary — both versions respond in the same request stream |
| Planned downtime window | Observed during recreate — all Pods terminate before any new Pod starts |
| Atomic traffic switch | Observed during blue-green — single patch, no in-between state, no downtime |
| Traffic proportion by replica count | Observed during canary — 20 requests showed ~10% to v2 |
| Rollback procedures | Practised `rollout undo`, selector patch, and replica scale-to-zero |

---

## Optional Extension — Move Lab 3 to Kubernetes with Helm

The deployment strategies in this lab were demonstrated with a simple stateless webapp. The real system — the Lab 3 observable email worker, mzinga-apps, MongoDB, RabbitMQ, Redis, and Jaeger — can be moved to Kubernetes following the same principles, but with a more practical tool: **Helm**.

Instead of maintaining separate YAML files for every service and component, Helm packages the entire Lab 3 stack as a single chart. One `helm install` command starts everything. One `helm upgrade` promotes a new worker version. One `helm rollback` reverts the entire stack — not just one Deployment — to a previous consistent state.

**[09d — Helm Charts](09d-helm-charts.md)** walks through:

- Converting `docker-compose-simplified.yml` into a Helm chart
- Building the email-worker Docker image and loading it into minikube
- Handling credentials as Kubernetes Secrets rather than values
- Service discovery: how docker-compose hostnames (`database`, `messagebus`) become Kubernetes Service names (`{{ .Release.Name }}-mongodb`, `{{ .Release.Name }}-rabbitmq`)
- Installing, upgrading, and rolling back the full Lab 3 stack
- Scaling worker replicas via a single values override

This extension brings together the architectural journey (monolith → polling worker → event-driven worker) and the deployment tooling (YAML → Helm) into a single runnable system on your local Kubernetes cluster.

---

## Clean Up

Remove all Lab 4 resources:

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

Deleting the namespace removes all resources within it (Deployments, ReplicaSets, Pods, Services). The namespace deletion may take up to 30 seconds as Kubernetes terminates all Pods gracefully.

---

**Previous:** [09b — Minikube Setup](09b-minikube-setup.md) · **Code snippets:** [09b — Lab 4 Code Snippets](09-lab4-code-snippets.md)
