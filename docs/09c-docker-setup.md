# Docker — Installation Guide

This document covers installing Docker on all platforms supported by this laboratory. If you completed Labs 1–3, Docker is almost certainly already installed and working — check that first before following any installation steps.

---

## Step 0 — Check Whether Docker Is Already Installed

Run the following commands. If both succeed, Docker is ready and you can skip the rest of this document.

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

### What to look for

`docker version` must show both a **Client** section and a **Server** section. A Client-only response means the Docker daemon is not running — start Docker Desktop or the Docker service and try again.

```
Client: Docker Engine - Community
 Version:           26.1.4
 ...

Server: Docker Engine - Community
 Engine:
  Version:          26.1.4
  ...
```

`docker run --rm hello-world` must end with:

```
Hello from Docker!
This message shows that your installation appears to be working correctly.
```

If either command fails, follow the installation instructions for your platform below.

---

## macOS — Docker Desktop

Docker Desktop is the standard way to run Docker on macOS. It includes the Docker Engine, Docker CLI, Docker Compose, and a GUI.

### Install

1. Download Docker Desktop for Mac from the [Docker website](https://www.docker.com/products/docker-desktop/).
   - Choose **Apple Silicon** (M1/M2/M3/M4) or **Intel** depending on your Mac.
2. Open the downloaded `.dmg`, drag Docker to Applications, and launch it.
3. Complete the onboarding wizard. Docker Desktop will ask for your system password the first time to install a helper tool.
4. Wait for the whale icon in the menu bar to show a steady state (not animated). Click it — the status should say "Docker Desktop is running".

### Verify

```sh
docker version
docker run --rm hello-world
```

### Notes

- Docker Desktop includes its own bundled `kubectl`. You can use it, but installing `kubectl` independently via Homebrew (as described in [09b — Minikube Setup](09b-minikube-setup.md)) gives you explicit version control.
- Docker Desktop requires macOS 12 (Monterey) or later.
- On Apple Silicon, Docker Desktop runs an x86_64 Linux VM via Rosetta/QEMU when needed. Images built locally will be `linux/arm64` by default; add `--platform linux/amd64` to `docker build` if you need to target an amd64 registry.

---

## Linux — Docker Engine

On Linux, the recommended installation is **Docker Engine** (the daemon + CLI), not Docker Desktop. Docker Desktop for Linux exists but adds a UI layer that is not needed for this laboratory.

The steps below are for **Ubuntu 22.04 LTS / 24.04 LTS** and compatible Debian-based distributions. For Fedora/RHEL, substitute `dnf` commands where noted.

### Remove any old versions

If a previous installation exists under the name `docker`, `docker-engine`, or `docker.io`, remove it first:

```sh
sudo apt-get remove docker docker-engine docker.io containerd runc
```

### Install via the official apt repository

```sh
# Add Docker's GPG key and repository
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker Engine and Docker Compose plugin
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

### Run Docker without sudo

Add your user to the `docker` group. This takes effect in new shell sessions:

```sh
sudo usermod -aG docker $USER
```

Apply the change to your current session without logging out:

```sh
newgrp docker
```

### Verify

```sh
docker version
docker run --rm hello-world
```

### Fedora / RHEL / Rocky Linux

Replace the apt steps with:

```sh
sudo dnf -y install dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo
sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
newgrp docker
```

### Start the Docker service automatically on boot

```sh
sudo systemctl enable docker
sudo systemctl start docker
```

---

## Windows — WSL 2 Path (Recommended)

On Windows, the recommended setup for this laboratory is **Docker Desktop with WSL 2 integration**. This makes Docker available inside the WSL Ubuntu terminal, where all Lab 4 commands run.

### Step 1 — Ensure WSL 2 is installed

Open PowerShell as Administrator:

```powershell
wsl --install
```

If WSL is already present, this is a no-op. Reboot if prompted. Confirm the version:

```powershell
wsl --list --verbose
```

The Ubuntu entry must show `VERSION 2`. If it shows `VERSION 1`, upgrade it:

```powershell
wsl --set-version Ubuntu 2
```

### Step 2 — Install Docker Desktop

1. Download [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/).
2. Run the installer. When asked, ensure **"Use WSL 2 instead of Hyper-V"** is checked.
3. After installation, launch Docker Desktop from the Start menu and wait for it to reach a running state (whale icon in the system tray, tooltip "Docker Desktop is running").

### Step 3 — Enable WSL integration

In Docker Desktop:

1. Open **Settings** (gear icon, top right).
2. Go to **General** — confirm "Use the WSL 2 based engine" is enabled.
3. Go to **Resources → WSL Integration** — enable integration for your Ubuntu distribution.
4. Click **Apply & Restart**.

### Step 4 — Verify from the Ubuntu terminal

Open the Ubuntu terminal and run:

```sh
docker version
docker run --rm hello-world
```

Both must succeed. If `docker` is not found, restart the Ubuntu terminal after enabling WSL integration in Docker Desktop.

### Verify from PowerShell (optional)

Docker Desktop also exposes the CLI on Windows:

```powershell
docker version
```

---

## Windows — Native (without WSL)

If you are not using WSL, Docker Desktop still provides a fully functional Docker environment on Windows natively.

### Install

1. Download [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/).
2. Run the installer. On the configuration screen:
   - If you **do** have Hyper-V enabled (Windows Pro/Enterprise): both options work; leave the defaults.
   - If you **do not** have Hyper-V: ensure "Use WSL 2 instead of Hyper-V" is selected, then install WSL 2 first (see the WSL section above).
3. Reboot when prompted.
4. Launch Docker Desktop from the Start menu and wait for the whale icon in the system tray to reach a running state.

### Verify

```powershell
docker version
docker run --rm hello-world
```

### Notes

- Docker Desktop for Windows requires Windows 10 version 1903 (build 18362) or later, or Windows 11.
- The WSL 2 backend is strongly preferred over Hyper-V for performance and compatibility.
- Docker Desktop must be **running** (not just installed) before any `docker` command works. If you see "error during connect: ... pipe/docker_engine", open Docker Desktop from the Start menu and wait for it to finish starting.

---

## Docker Compose

All previous labs used `docker compose` (the Compose V2 plugin, not the standalone `docker-compose` binary). Verify it is available:

```sh
docker compose version
```

Expected:

```
Docker Compose version v2.x.x
```

- **macOS**: included with Docker Desktop.
- **Linux**: included if you installed `docker-compose-plugin` via apt/dnf (see above). If missing: `sudo apt-get install docker-compose-plugin`.
- **Windows**: included with Docker Desktop.

---

**Back to:** [09b — Minikube Setup](09b-minikube-setup.md)
