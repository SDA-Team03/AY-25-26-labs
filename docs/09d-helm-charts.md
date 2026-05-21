# Helm Charts — From docker-compose to Managed Kubernetes Releases

Helm is the standard package manager for Kubernetes. It solves a class of problems that raw YAML manifests leave open: parameterisation, release tracking, application-level rollback, and describing a system composed of multiple interdependent services as a single deployable unit.

Official documentation: [helm.sh/docs](https://helm.sh/docs/)

---

## The Limits of Plain YAML at Scale

The manifests written in Lab 4 work correctly for a single scenario on a local minikube cluster. The moment you try to manage a multi-component system — the full Lab 3 stack with mzinga-apps, the email worker, MongoDB, RabbitMQ, Redis, and Jaeger — the limitations of plain YAML become concrete.

**No parameterisation.** The image tag `lab3-email-worker:1.0.0` is hardcoded in the Deployment. Promoting to v2 means editing the file. The MongoDB connection string is repeated in the mzinga-apps Deployment and potentially in other manifests — change it once and you will miss the other occurrences.

**No release identity.** `kubectl apply -f k8s/` applies a set of files. Kubernetes tracks the state of individual resources, but nothing tracks "which version of this stack is currently deployed". There is no history, no diff, and no way to ask what changed between the last deployment and this one without diffing YAML by hand.

**No application-level rollback.** `kubectl rollout undo deployment/email-worker` reverts one Deployment. If the upgrade also changed a ConfigMap, a Secret, or updated a connection string in mzinga-apps — those changes remain. Rolling back the entire system to a consistent previous state requires re-applying every manifest from an earlier point in time.

**No composition.** The Lab 3 system requires six components, each with their own Kubernetes resources, startup ordering, and cross-component configuration. Deploying all of them means applying multiple directories in the correct order with no built-in concept that these resources belong together as a single application.

Helm addresses all four of these problems with a single abstraction: the **chart**.

---

## Core Concepts

### Chart

A **chart** is a collection of files that describe a related set of Kubernetes resources. A chart for the full Lab 3 system contains Deployments, Services, and configuration for every component — including references to community charts for standard infrastructure like MongoDB and RabbitMQ.

### Release

A **release** is a named instance of a chart deployed to a cluster. Installing the chart as `mzinga-lab3` creates a release with that name. Every Kubernetes resource created by the release is tagged with that name. The release is the scope for all Helm operations — upgrade, rollback, uninstall.

### Values

**Values** are the configurable inputs to a chart, defined in `values.yaml` and overridable at install or upgrade time. Where a plain manifest has `image: lab3-email-worker:1.0.0` hardcoded, a Helm template has `image: {{ .Values.emailWorker.image.repository }}:{{ .Values.emailWorker.image.tag }}`. The actual value comes from `values.yaml`, from a per-environment override file, or from a `--set` flag on the command line.

### Templates

**Templates** are YAML files in `templates/` that contain Go template directives. Helm renders them by substituting values and evaluating logic, producing valid Kubernetes manifests.

### Repository

A **repository** is an HTTP server that hosts packaged charts. `helm repo add bitnami https://charts.bitnami.com/bitnami` registers the Bitnami repository. `helm install` can then reference `bitnami/mongodb` without downloading any YAML locally. This is how community charts for standard infrastructure are consumed — rather than writing MongoDB YAML from scratch, you declare it as a dependency.

---

## The Lab 3 Stack

The full Lab 3 system, currently described by `docker-compose-simplified.yml`, consists of:

| Component | docker-compose service name | Image | Port(s) |
|-----------|----------------------------|-------|---------|
| MZinga CMS | `mzinga` | `newesissrl.azurecr.io/mzinga/payload/gh/backoffice:0.9.3` | 3000 |
| Email worker | _(run directly)_ | locally built from `lab3-worker-observable/` | 8000 (Prometheus) |
| MongoDB | `database` | `percona/percona-server-mongodb:8.0.20-8` | 27017 |
| RabbitMQ | `messagebus` | `rabbitmq:4.2.5-management-alpine` | 5672, 15672 |
| Redis | `cache` | `redis:8.6.2-alpine` | 6379 |
| Jaeger | `jaeger` | `jaegertracing/all-in-one:latest` | 4317, 4318, 16686 |

### Hostname Translation: docker-compose → Kubernetes

In docker-compose, services reach each other by their service name (`database`, `messagebus`, `cache`, `jaeger`). In Kubernetes, services reach each other by their Kubernetes Service name. When Helm installs a release named `mzinga-lab3`, it prefixes each resource with the release name:

| docker-compose hostname | Kubernetes Service name |
|------------------------|------------------------|
| `database` | `mzinga-lab3-mongodb` |
| `messagebus` | `mzinga-lab3-rabbitmq` |
| `cache` | `mzinga-lab3-redis-master` |
| `jaeger` | `mzinga-lab3-jaeger` |
| `mzinga` | `mzinga-lab3-mzinga-apps` |

This translation must be reflected in every environment variable that contains a hostname — `MONGODB_URI`, `RABBITMQ_URL`, `REDIS_URI`, `OTEL_EXPORTER_OTLP_ENDPOINT`, and the worker's `MZINGA_URL`. Helm templates make this automatic: the release name is available as `{{ .Release.Name }}`, so connection strings are constructed as `mongodb://{{ .Release.Name }}-mongodb:27017/mzinga` and always match the actual Service name.

---

## Chart Structure

The Lab 3 Helm chart follows this directory layout:

```
mzinga-lab3/
├── Chart.yaml                        # chart metadata and dependencies
├── values.yaml                       # default configuration values
├── templates/
│   ├── _helpers.tpl                  # shared template helpers
│   ├── secrets.yaml                  # Kubernetes Secret for credentials
│   ├── mzinga-apps-deployment.yaml
│   ├── mzinga-apps-service.yaml
│   ├── email-worker-deployment.yaml
│   ├── email-worker-service.yaml     # exposes Prometheus metrics port
│   ├── jaeger-deployment.yaml
│   └── jaeger-service.yaml
└── charts/                           # populated by helm dependency update
    ├── mongodb-15.x.x.tgz
    ├── rabbitmq-14.x.x.tgz
    └── redis-19.x.x.tgz
```

MongoDB, RabbitMQ, and Redis are declared as **chart dependencies** — Bitnami publishes maintained charts for all three, so the Lab 3 chart does not need to write their Deployments and Services from scratch. mzinga-apps, the email worker, and Jaeger have no community chart equivalent and are defined in the `templates/` directory.

---

## `Chart.yaml`

```yaml
apiVersion: v2
name: mzinga-lab3
description: MZinga Lab 3 — observable email worker with full infrastructure stack
type: application
version: 1.0.0        # chart version — increment when the chart itself changes
appVersion: "0.9.3"   # mzinga-apps version — informational, shown in helm list

dependencies:
  - name: mongodb
    version: "15.x.x"
    repository: "https://charts.bitnami.com/bitnami"
    alias: mongodb
  - name: rabbitmq
    version: "14.x.x"
    repository: "https://charts.bitnami.com/bitnami"
    alias: rabbitmq
  - name: redis
    version: "19.x.x"
    repository: "https://charts.bitnami.com/bitnami"
    alias: redis
```

After creating this file, download the dependency charts:

```sh
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update
helm dependency update ./mzinga-lab3
```

This populates the `charts/` directory with the downloaded `.tgz` files.

---

## Build the Email Worker Image for minikube

The email worker is not published to any registry — it is the Python code from `mzinga/lab3-worker-observable/`. Before installing the chart, build the image and make it available inside minikube.

### `Dockerfile` (create in `mzinga/lab3-worker-observable/`)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY worker.py .
CMD ["python", "-u", "worker.py"]
```

### Build and load

```sh
# Build the image using Docker
docker build -t lab3-email-worker:1.0.0 ./mzinga/lab3-worker-observable/

# Load it into minikube's image store
minikube image load lab3-email-worker:1.0.0
```

The `imagePullPolicy: Never` setting in the email-worker Deployment tells Kubernetes to use the locally loaded image rather than attempting to pull from a registry. mzinga-apps uses an image from the Azure Container Registry and does not need this override.

---

## `values.yaml`

All configurable values — image tags, replica counts, connection strings, resource limits — live in `values.yaml`. Sensitive credentials are **not** placed here (see the Secrets section below).

```yaml
# ─── mzinga-apps ─────────────────────────────────────────────────────────────

mzingaApps:
  image:
    repository: newesissrl.azurecr.io/mzinga/payload/gh/backoffice
    tag: "0.9.3"
    pullPolicy: IfNotPresent  # pull once, cache on node
  replicaCount: 1
  service:
    port: 3000
  env:
    tenantId: "mzinga"
    payloadSecret: "change-me-for-production"
    corsConfigs: "*"

# ─── email-worker ─────────────────────────────────────────────────────────────

emailWorker:
  image:
    repository: lab3-email-worker
    tag: "1.0.0"
    pullPolicy: Never          # locally built — never attempt a registry pull
  replicaCount: 1
  service:
    prometheusPort: 8000
  env:
    otlpServiceName: "email-worker"
    smtpHost: "mailhog"        # replace with real SMTP host if available
    smtpPort: "1025"

# ─── jaeger ───────────────────────────────────────────────────────────────────

jaeger:
  image:
    repository: jaegertracing/all-in-one
    tag: "latest"
    pullPolicy: IfNotPresent
  service:
    uiPort: 16686
    otlpGrpcPort: 4317
    otlpHttpPort: 4318

# ─── Bitnami MongoDB sub-chart ────────────────────────────────────────────────
# See https://artifacthub.io/packages/helm/bitnami/mongodb for all options

mongodb:
  auth:
    enabled: false             # no authentication for the lab
  persistence:
    enabled: false             # no persistent volume needed for local dev

# ─── Bitnami RabbitMQ sub-chart ───────────────────────────────────────────────

rabbitmq:
  auth:
    username: "mzinga"
    password: "mzinga"         # override with --set for real environments
  persistence:
    enabled: false

# ─── Bitnami Redis sub-chart ──────────────────────────────────────────────────

redis:
  auth:
    enabled: false
  master:
    persistence:
      enabled: false
```

---

## Secrets

Credentials that grant access to real systems must not be committed to version control. The email worker needs two: `MZINGA_EMAIL` and `MZINGA_PASSWORD` — the service account it uses to authenticate with the MZinga REST API.

In Kubernetes, these are stored in a `Secret` object. The `templates/secrets.yaml` template creates the Secret, but the actual values are provided at install time via `--set`, not stored in `values.yaml`.

### `templates/secrets.yaml`

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: {{ .Release.Name }}-worker-credentials
  namespace: {{ .Release.Namespace }}
type: Opaque
stringData:
  mzinga-email: {{ required "emailWorker.credentials.email is required" .Values.emailWorker.credentials.email | quote }}
  mzinga-password: {{ required "emailWorker.credentials.password is required" .Values.emailWorker.credentials.password | quote }}
```

The `required` function causes `helm install` to fail with a clear error if the credential values are not provided — preventing an accidental deployment with empty credentials.

The Secret is referenced in the email-worker Deployment using `secretKeyRef`:

```yaml
env:
  - name: MZINGA_EMAIL
    valueFrom:
      secretKeyRef:
        name: {{ .Release.Name }}-worker-credentials
        key: mzinga-email
  - name: MZINGA_PASSWORD
    valueFrom:
      secretKeyRef:
        name: {{ .Release.Name }}-worker-credentials
        key: mzinga-password
```

The credentials are passed at install time using `--set` (never committed to any file):

```sh
helm install mzinga-lab3 ./mzinga-lab3 \
  --namespace mzinga \
  --create-namespace \
  --set emailWorker.credentials.email="worker@example.com" \
  --set emailWorker.credentials.password="yourpassword"
```

---

## Key Templates

### `templates/mzinga-apps-deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}-mzinga-apps
  namespace: {{ .Release.Namespace }}
spec:
  replicas: {{ .Values.mzingaApps.replicaCount }}
  selector:
    matchLabels:
      app: {{ .Release.Name }}-mzinga-apps
  template:
    metadata:
      labels:
        app: {{ .Release.Name }}-mzinga-apps
    spec:
      containers:
        - name: mzinga-apps
          image: "{{ .Values.mzingaApps.image.repository }}:{{ .Values.mzingaApps.image.tag }}"
          imagePullPolicy: {{ .Values.mzingaApps.image.pullPolicy }}
          ports:
            - containerPort: {{ .Values.mzingaApps.service.port }}
          env:
            - name: MONGODB_URI
              value: "mongodb://{{ .Release.Name }}-mongodb:27017/mzinga"
            - name: RABBITMQ_URL
              value: "amqp://{{ .Values.rabbitmq.auth.username }}:{{ .Values.rabbitmq.auth.password }}@{{ .Release.Name }}-rabbitmq:5672"
            - name: REDIS_URI
              value: "redis://{{ .Release.Name }}-redis-master:6379"
            - name: OTEL_EXPORTER_OTLP_ENDPOINT
              value: "http://{{ .Release.Name }}-jaeger:4318"
            - name: OTEL_SERVICE_NAME
              value: "mzinga-apps"
            - name: TENANT
              value: {{ .Values.mzingaApps.env.tenantId | quote }}
            - name: PAYLOAD_SECRET
              value: {{ .Values.mzingaApps.env.payloadSecret | quote }}
            - name: CORS_CONFIGS
              value: {{ .Values.mzingaApps.env.corsConfigs | quote }}
          readinessProbe:
            httpGet:
              path: /api/healthz
              port: {{ .Values.mzingaApps.service.port }}
            initialDelaySeconds: 15
            periodSeconds: 10
```

Notice how every hostname uses `{{ .Release.Name }}-<service>`: this always resolves to the Kubernetes Service created by the same Helm release, regardless of what namespace or name the release is installed under. There is no hardcoded `database` or `messagebus`.

### `templates/email-worker-deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}-email-worker
  namespace: {{ .Release.Namespace }}
spec:
  replicas: {{ .Values.emailWorker.replicaCount }}
  selector:
    matchLabels:
      app: {{ .Release.Name }}-email-worker
  template:
    metadata:
      labels:
        app: {{ .Release.Name }}-email-worker
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: {{ .Values.emailWorker.service.prometheusPort | quote }}
    spec:
      containers:
        - name: email-worker
          image: "{{ .Values.emailWorker.image.repository }}:{{ .Values.emailWorker.image.tag }}"
          imagePullPolicy: {{ .Values.emailWorker.image.pullPolicy }}
          ports:
            - containerPort: {{ .Values.emailWorker.service.prometheusPort }}
              name: metrics
          env:
            - name: MZINGA_URL
              value: "http://{{ .Release.Name }}-mzinga-apps:{{ .Values.mzingaApps.service.port }}"
            - name: MZINGA_EMAIL
              valueFrom:
                secretKeyRef:
                  name: {{ .Release.Name }}-worker-credentials
                  key: mzinga-email
            - name: MZINGA_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: {{ .Release.Name }}-worker-credentials
                  key: mzinga-password
            - name: SMTP_HOST
              value: {{ .Values.emailWorker.env.smtpHost | quote }}
            - name: SMTP_PORT
              value: {{ .Values.emailWorker.env.smtpPort | quote }}
            - name: OTEL_EXPORTER_OTLP_ENDPOINT
              value: "http://{{ .Release.Name }}-jaeger:4318"
            - name: OTEL_SERVICE_NAME
              value: {{ .Values.emailWorker.env.otlpServiceName | quote }}
            - name: PROMETHEUS_PORT
              value: {{ .Values.emailWorker.service.prometheusPort | quote }}
```

### `templates/jaeger-deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}-jaeger
  namespace: {{ .Release.Namespace }}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {{ .Release.Name }}-jaeger
  template:
    metadata:
      labels:
        app: {{ .Release.Name }}-jaeger
    spec:
      containers:
        - name: jaeger
          image: "{{ .Values.jaeger.image.repository }}:{{ .Values.jaeger.image.tag }}"
          imagePullPolicy: {{ .Values.jaeger.image.pullPolicy }}
          ports:
            - containerPort: {{ .Values.jaeger.service.uiPort }}
            - containerPort: {{ .Values.jaeger.service.otlpGrpcPort }}
            - containerPort: {{ .Values.jaeger.service.otlpHttpPort }}
          env:
            - name: COLLECTOR_OTLP_ENABLED
              value: "true"
```

### Services

Each component needs a corresponding Service. The pattern is the same for all of them:

```yaml
# templates/mzinga-apps-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ .Release.Name }}-mzinga-apps
  namespace: {{ .Release.Namespace }}
spec:
  selector:
    app: {{ .Release.Name }}-mzinga-apps
  ports:
    - port: {{ .Values.mzingaApps.service.port }}
      targetPort: {{ .Values.mzingaApps.service.port }}
```

The Service name `{{ .Release.Name }}-mzinga-apps` is exactly the hostname that the email-worker's `MZINGA_URL` and mzinga-apps' own readiness probe expect. Template and network configuration stay consistent by construction.

---

## Preview Before Installing

Render all templates locally without touching the cluster:

```sh
helm template mzinga-lab3 ./mzinga-lab3 \
  --namespace mzinga \
  --set emailWorker.credentials.email="worker@example.com" \
  --set emailWorker.credentials.password="test"
```

This prints the fully rendered YAML to stdout. Use it to verify that hostnames are correct, image tags are substituted, and secrets are referenced (not inlined).

---

## Install the Chart

Start minikube if it is not already running:

```sh
minikube start
```

Install the chart as a release named `mzinga-lab3`:

```sh
helm install mzinga-lab3 ./mzinga-lab3 \
  --namespace mzinga \
  --create-namespace \
  --set emailWorker.credentials.email="worker@example.com" \
  --set emailWorker.credentials.password="yourpassword" \
  --timeout 5m \
  --wait
```

`--wait` blocks until all Pods in the release are ready (or the timeout is reached). If any Pod fails to start, Helm reports the failure immediately.

Watch all Pods come up:

```sh
kubectl get pods -n mzinga -w
```

Once all Pods are `Running`, port-forward to verify mzinga-apps:

```sh
kubectl port-forward service/mzinga-lab3-mzinga-apps 3000:3000 -n mzinga &
curl http://localhost:3000/api/healthz
```

Port-forward to the Jaeger UI:

```sh
kubectl port-forward service/mzinga-lab3-jaeger 16686:16686 -n mzinga &
# Open http://localhost:16686 in a browser
```

---

## Upgrade: Deploy a New Worker Version

When you modify `worker.py` and want to deploy the update, the workflow is:

1. **Rebuild the image with a new tag:**

```sh
docker build -t lab3-email-worker:1.1.0 ./mzinga/lab3-worker-observable/
minikube image load lab3-email-worker:1.1.0
```

2. **Upgrade the release with the new tag:**

```sh
helm upgrade mzinga-lab3 ./mzinga-lab3 \
  --namespace mzinga \
  --set emailWorker.image.tag=1.1.0 \
  --set emailWorker.credentials.email="worker@example.com" \
  --set emailWorker.credentials.password="yourpassword" \
  --atomic \
  --timeout 3m
```

`--atomic` instructs Helm to watch the upgrade and automatically roll back the entire release to the previous revision if any resource does not reach a ready state within the timeout.

3. **Inspect the release history:**

```sh
helm history mzinga-lab3 -n mzinga
```

```
REVISION  UPDATED                   STATUS     CHART           APP VERSION  DESCRIPTION
1         2025-01-15 10:00:00 UTC   superseded mzinga-lab3-1.0.0  0.9.3    Install complete
2         2025-01-15 10:20:00 UTC   deployed   mzinga-lab3-1.0.0  0.9.3    Upgrade complete
```

4. **Roll back if needed:**

```sh
helm rollback mzinga-lab3 1 -n mzinga
```

Helm restores the release to revision 1 — re-renders all templates with revision 1's values, computes the diff against the current state, and applies the changes. Every resource in the release reverts, not just the email-worker Deployment. The release becomes revision 3 (Helm appends to history).

This is the advantage over `kubectl rollout undo deployment/email-worker`: the Helm rollback is application-scoped, not resource-scoped. If the upgrade also changed a ConfigMap or a Secret reference, the rollback restores those too.

---

## Scaling the Worker

One of the architectural conclusions from the lab sequence is that the event-driven worker (Lab 3) can scale horizontally without coordination code, because RabbitMQ's delivery semantics ensure each message reaches exactly one consumer. With Helm, scaling is a single values override:

```sh
helm upgrade mzinga-lab3 ./mzinga-lab3 \
  --namespace mzinga \
  --set emailWorker.replicaCount=5 \
  --set emailWorker.credentials.email="worker@example.com" \
  --set emailWorker.credentials.password="yourpassword"
```

All 5 worker instances subscribe to the same RabbitMQ queue. Helm records the replica count change in the release history, so scaling back to 1 is a rollback to the previous revision.

---

## Essential Helm Commands

| Command | What it does |
|---------|-------------|
| `helm create <name>` | Scaffold a new chart with example templates |
| `helm dependency update <chart>` | Download declared chart dependencies into `charts/` |
| `helm template <release> <chart>` | Render templates locally without installing |
| `helm lint <chart>` | Validate chart structure and template syntax |
| `helm install <release> <chart>` | Install a chart as a new release |
| `helm upgrade <release> <chart>` | Upgrade an existing release |
| `helm upgrade --install <release> <chart>` | Install if not present, upgrade if it is |
| `helm upgrade --atomic <release> <chart>` | Upgrade with automatic rollback on failure |
| `helm list -n <namespace>` | List releases in a namespace |
| `helm status <release> -n <namespace>` | Show the current state of a release |
| `helm history <release> -n <namespace>` | Show revision history |
| `helm rollback <release> <revision>` | Roll back to a specific revision |
| `helm get values <release> -n <namespace>` | Show the values used for the current revision |
| `helm uninstall <release> -n <namespace>` | Delete a release and all its resources |
| `helm repo add <name> <url>` | Register a chart repository |
| `helm repo update` | Refresh the local repository index |

---

## Deploying MZinga with the Official Helm Chart

The MZinga project publishes an official Helm chart that packages the full application stack. The chart repository is maintained at:

**[github.com/mzinga-io/helm-charts](https://github.com/mzinga-io/helm-charts)**

To deploy MZinga to a Kubernetes cluster using the official chart:

```sh
# Add the MZinga chart repository
helm repo add mzinga https://mzinga-io.github.io/helm-charts
helm repo update

# Install MZinga
helm install mzinga mzinga/mzinga \
  --namespace mzinga \
  --create-namespace \
  -f my-values.yaml
```

The official chart encodes the recommended configuration for the full stack and provides a documented `values.yaml` covering image tags, resource limits, ingress configuration, and infrastructure connection strings.

---

## Further Reading

- [Helm Documentation](https://helm.sh/docs/) — full reference including the chart template guide, built-in objects, and function list
- [Chart Template Guide](https://helm.sh/docs/chart_template_guide/) — in-depth walkthrough of Go templating in Helm charts
- [Artifact Hub](https://artifacthub.io/) — the public index of community Helm charts, where Bitnami publishes MongoDB, RabbitMQ, and Redis charts
- [MZinga Helm Charts](https://github.com/mzinga-io/helm-charts) — the official chart repository for deploying the MZinga CMS

---

**Previous:** [09c — Docker Setup](09c-docker-setup.md) · **Next:** [09 — Lab 4 Step by Step](09-lab4-step-by-step.md)
