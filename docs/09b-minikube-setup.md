# Minikube — Installation and Setup Guide

Minikube runs a single-node Kubernetes cluster inside a VM or a container on your local machine. It is the standard tool for learning and developing with Kubernetes locally without needing a cloud provider account.

---

## Prerequisites

You need Docker and `kubectl` before installing minikube. Docker was required from Lab 1 onwards, so it should already be present on your machine. Verify it before proceeding.

### Verify Docker is running

**macOS / Linux / WSL:**

```sh
docker version
docker run --rm hello-world
```

**Windows PowerShell:**

```powershell
docker version
docker run --rm hello-world
```

Both commands must succeed. `docker version` must show both a Client and a Server (daemon) version. `hello-world` must print `Hello from Docker!`.

If either command fails, install Docker before continuing — see [09c — Docker Setup](09c-docker-setup.md).

---

## macOS

### 1 — Install kubectl and minikube

```sh
brew install kubectl
brew install minikube
```

Verify:

```sh
kubectl version --client
minikube version
```

### 2 — Start a cluster

```sh
minikube start --driver=docker --cpus=2 --memory=4096
```

Minikube pulls a Docker image containing the Kubernetes control plane and starts it as a container. The `--driver=docker` flag uses Docker as the virtualisation layer — no separate VM or hypervisor is needed.

### 3 — Verify the cluster

```sh
kubectl cluster-info
kubectl get nodes
```

Expected output:

```
NAME       STATUS   ROLES           AGE   VERSION
minikube   Ready    control-plane   30s   v1.30.x
```

---

## Linux

Tested on Ubuntu 22.04 LTS and Fedora 39.

### 1 — Install kubectl

```sh
curl -LO "https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl
sudo mv kubectl /usr/local/bin/
kubectl version --client
```

### 2 — Install minikube

```sh
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube
minikube version
```

### 3 — Start a cluster

```sh
minikube start --driver=docker --cpus=2 --memory=4096
```

### 4 — Verify the cluster

```sh
kubectl cluster-info
kubectl get nodes
```

---

## Windows — with WSL 2 (Recommended)

Running Kubernetes inside WSL 2 gives you a Linux environment while staying on Windows. All `kubectl` and `minikube` commands below are run from the Ubuntu terminal unless otherwise noted.

### 1 — Verify WSL 2 is active

Open PowerShell and run:

```powershell
wsl --list --verbose
```

The Ubuntu entry must show `VERSION 2`. If WSL is not installed, open PowerShell as Administrator and run `wsl --install`, then reboot.

### 2 — Verify Docker Desktop is integrated with WSL

Inside the Ubuntu terminal:

```sh
docker version
```

The Server section must be present. If the command is not found or shows only a Client, open Docker Desktop → **Settings → Resources → WSL Integration** and enable integration with your Ubuntu distribution, then restart Docker Desktop.

### 3 — Install kubectl and minikube inside WSL

Open the Ubuntu terminal:

```sh
# kubectl
curl -LO "https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl
sudo mv kubectl /usr/local/bin/

# minikube
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube
```

Verify:

```sh
kubectl version --client
minikube version
```

### 4 — Start a cluster (from the Ubuntu terminal)

```sh
minikube start --driver=docker --cpus=2 --memory=4096
```

### 5 — Verify the cluster

```sh
kubectl cluster-info
kubectl get nodes
```

### Accessing services from Windows

When you use `kubectl port-forward` or `minikube service` from the WSL terminal, the port is accessible at `localhost` from both the WSL terminal and the Windows browser. No additional configuration is needed.

---

## Windows — Native (without WSL)

This path runs minikube directly on Windows using Docker Desktop as the driver.

### 1 — Verify Docker Desktop is running

Open Docker Desktop and confirm the whale icon in the system tray shows "Docker Desktop is running". Then open PowerShell and verify:

```powershell
docker version
```

Both Client and Server sections must be present.

### 2 — Install kubectl

```powershell
winget install Kubernetes.kubectl
```

Or download the binary manually:

```powershell
curl.exe -LO "https://dl.k8s.io/release/v1.30.0/bin/windows/amd64/kubectl.exe"
Move-Item .\kubectl.exe C:\Windows\System32\kubectl.exe
```

Verify:

```powershell
kubectl version --client
```

### 3 — Install minikube

```powershell
winget install Kubernetes.minikube
```

Or using Chocolatey:

```powershell
choco install minikube
```

Verify:

```powershell
minikube version
```

### 4 — Start a cluster

```powershell
minikube start --driver=docker --cpus=2 --memory=4096
```

> **Hyper-V alternative:** On Windows Pro/Enterprise you can use `--driver=hyperv` instead of `--driver=docker`. This requires enabling Hyper-V in Windows Features. The Docker driver is simpler and is recommended for this lab.

### 5 — Verify

```powershell
kubectl cluster-info
kubectl get nodes
```

---

## Essential Minikube Commands

| Command | What it does |
|---------|-------------|
| `minikube start` | Start the cluster (uses last config if not specified) |
| `minikube stop` | Stop the cluster without deleting it |
| `minikube delete` | Delete the cluster and all its data |
| `minikube status` | Show the status of the cluster components |
| `minikube dashboard` | Open the Kubernetes web UI in a browser |
| `minikube image load <image>` | Load a locally built Docker image into minikube's image cache |
| `minikube service <name> -n <namespace>` | Open a Service URL in the browser (starts a tunnel) |
| `minikube tunnel` | Create a network tunnel so LoadBalancer Services get a real IP |
| `minikube addons list` | List available add-ons |
| `minikube addons enable <name>` | Enable a minikube add-on (e.g. `ingress`, `metrics-server`) |

---

## Essential kubectl Commands

| Command | What it does |
|---------|-------------|
| `kubectl get pods -n <ns>` | List Pods in a namespace |
| `kubectl get pods -n <ns> -w` | Watch Pod status changes in real time |
| `kubectl get deployments -n <ns>` | List Deployments |
| `kubectl get services -n <ns>` | List Services |
| `kubectl describe pod <name> -n <ns>` | Detailed Pod info including events |
| `kubectl logs <pod> -n <ns>` | Print Pod logs |
| `kubectl logs <pod> -n <ns> -f` | Stream Pod logs |
| `kubectl apply -f <file.yaml>` | Apply a manifest (create or update) |
| `kubectl delete -f <file.yaml>` | Delete resources defined in a manifest |
| `kubectl rollout status deployment/<name> -n <ns>` | Watch a rolling update progress |
| `kubectl rollout undo deployment/<name> -n <ns>` | Roll back to the previous Deployment revision |
| `kubectl set image deployment/<name> <container>=<image> -n <ns>` | Update a container image imperatively |
| `kubectl patch service <name> -n <ns> -p '<json-patch>'` | Patch a Service spec in-place |
| `kubectl port-forward service/<name> <local>:<remote> -n <ns>` | Forward a local port to a Service port |
| `kubectl scale deployment/<name> --replicas=<n> -n <ns>` | Change the replica count |

---

## Cleaning Up After the Lab

Remove all Lab 4 resources without deleting the cluster:

```sh
kubectl delete namespace mzinga-lab4
```

Stop the cluster:

```sh
minikube stop
```

Delete the cluster entirely (removes all data):

```sh
minikube delete
```

---

**Previous:** [09a — Kubernetes Introduction](09a-kubernetes-introduction.md) · **Docker setup (if needed):** [09c — Docker Setup](09c-docker-setup.md) · **Next:** [09 — Lab 4 Step by Step](09-lab4-step-by-step.md)
