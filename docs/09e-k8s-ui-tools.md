# Kubernetes UI Tools — K9s and OpenLens

Raw `kubectl` commands are sufficient for everything in this lab, but two tools make it significantly easier to observe what is happening inside the cluster during rolling updates, Recreate cycles, blue-green switches, and canary experiments: **K9s** and **OpenLens**.

Both tools read from the same `~/.kube/config` file that `minikube start` writes automatically. No additional cluster configuration is required — once minikube is running, open either tool and your cluster appears immediately.

---

## K9s — Terminal UI

K9s is a terminal-based interface for Kubernetes. It runs inside a terminal window and provides a real-time, keyboard-driven view of every resource in the cluster — Pods, Deployments, Services, logs, events — without typing `kubectl get` commands repeatedly.

It is particularly useful during this lab for watching Pod states change in real time while a deployment strategy is running, and for tailing logs from multiple Pods simultaneously.

Official site and source: [github.com/derailed/k9s](https://github.com/derailed/k9s)

### Installation

**macOS**

```sh
brew install k9s
```

**Linux**

If Homebrew is installed on Linux:

```sh
brew install k9s
```

Without Homebrew, download the pre-built binary from the [K9s releases page](https://github.com/derailed/k9s/releases). Choose the archive matching your architecture (`Linux_amd64.tar.gz` for most systems, `Linux_arm64.tar.gz` for ARM):

```sh
# Example for amd64 — replace the version with the latest release
curl -Lo k9s.tar.gz https://github.com/derailed/k9s/releases/latest/download/k9s_Linux_amd64.tar.gz
tar -xzf k9s.tar.gz k9s
sudo mv k9s /usr/local/bin/
k9s version
```

**Windows**

With winget:

```powershell
winget install k9s
```

With Scoop:

```powershell
scoop install k9s
```

Without a package manager, download `k9s_Windows_amd64.zip` from the [releases page](https://github.com/derailed/k9s/releases), extract it, and place `k9s.exe` somewhere on your `PATH`.

### Starting K9s

With minikube running, launch K9s from any terminal:

```sh
k9s
```

K9s opens directly to the Pod list for the default namespace. To start in a specific namespace:

```sh
k9s -n mzinga-lab4
```

### Navigating K9s

K9s is entirely keyboard-driven. The most important keys for this lab:

| Key / Command | Action |
|---------------|--------|
| `:pod` | Switch to the Pod resource view |
| `:deploy` | Switch to the Deployment resource view |
| `:svc` | Switch to the Service resource view |
| `:event` | View cluster events (useful for seeing why a Pod failed) |
| `0` | Show resources across all namespaces |
| `/` | Filter the current list by name |
| `Enter` | Drill into the selected resource |
| `l` | Stream logs from the selected Pod |
| `s` | Open a shell (`exec`) into the selected container |
| `d` | Describe the selected resource (equivalent to `kubectl describe`) |
| `Ctrl+D` | Delete the selected resource |
| `Ctrl+Z` | Kill the selected Pod (forces immediate termination) |
| `?` | Show all available shortcuts for the current view |
| `Esc` | Go back / cancel |
| `q` | Quit K9s |

During a rolling update or a Recreate transition, navigate to `:pod -n mzinga-lab4` and watch Pods cycle through `Pending → ContainerCreating → Running → Terminating` in real time without running `kubectl get pods -w` manually.

---

## OpenLens — Desktop GUI

OpenLens is a desktop application that provides a full graphical interface for Kubernetes. It shows the same information as K9s but in a point-and-click GUI with charts, resource editors, and integrated log viewers across multiple Pods simultaneously.

OpenLens is the open-source community fork of the Lens IDE, maintained at [github.com/MuhammedKalkan/OpenLens](https://github.com/MuhammedKalkan/OpenLens). The original Lens product moved to a commercial model; OpenLens provides the same core functionality under an open licence.

### Installation

**macOS**

```sh
brew install --cask openlens
```

Or download the `.dmg` installer from the [OpenLens releases page](https://github.com/MuhammedKalkan/OpenLens/releases). Open the `.dmg`, drag OpenLens to Applications, and launch it. macOS may show a security warning on first launch — open System Settings → Privacy & Security and click **Open Anyway**.

**Linux**

Download the appropriate package from the [OpenLens releases page](https://github.com/MuhammedKalkan/OpenLens/releases):

- `.AppImage` — works on any distribution without installation. Mark it executable and run it:

  ```sh
  chmod +x OpenLens-*.AppImage
  ./OpenLens-*.AppImage
  ```

- `.deb` — install on Debian, Ubuntu, and derivatives:

  ```sh
  sudo dpkg -i OpenLens-*.deb
  ```

- `.rpm` — install on Fedora, RHEL, and derivatives:

  ```sh
  sudo rpm -i OpenLens-*.rpm
  ```

**Windows**

Download the `.exe` installer from the [OpenLens releases page](https://github.com/MuhammedKalkan/OpenLens/releases) and run it. The installer does not require administrator privileges and adds OpenLens to the Start Menu.

### Connecting to Minikube

OpenLens reads `~/.kube/config` on startup. Since `minikube start` writes the minikube cluster context to that file automatically, OpenLens detects the cluster without any manual configuration.

On first launch:

1. Click **Catalog** in the left sidebar — the minikube cluster appears in the list.
2. Click on it to connect. The cluster overview opens showing node status, Pod count, and resource usage.

If the cluster does not appear, click the **+** button and select **Sync kubeconfig** to force a re-read of `~/.kube/config`.

### Key Features for This Lab

**Workloads view**

Navigate to **Workloads → Pods** (filtered to the `mzinga-lab4` namespace) to watch Pod status during deployments. The table updates in real time — you can observe the Recreate strategy terminating all Pods simultaneously, or a rolling update replacing them one by one, without running any commands.

**Deployment rollout status**

**Workloads → Deployments** shows each Deployment's desired vs. ready replica count. During a rolling update you can see the replica count tick up and down as new Pods come online and old ones are removed.

**Logs**

Click any Pod and select the **Logs** tab to stream its stdout. The log viewer supports multi-container Pods and lets you switch between containers in the same Pod without closing the panel.

**Shell access**

Click any running Pod and select **Shell** to open an interactive terminal inside the container — the graphical equivalent of `kubectl exec -it`.

**Service and selector inspection**

Navigate to **Network → Services** and click a Service to see its selector and the list of Pods currently in its endpoint set. This is useful for verifying that the blue-green selector switch worked correctly — after patching the Service, the endpoint list should immediately show only the green Pods.

---

## Which Tool to Use

| | K9s | OpenLens |
|---|---|---|
| **Interface** | Terminal (TUI) | Desktop application (GUI) |
| **Best for** | Fast keyboard-driven navigation, watching live state during deployments | Exploring resources visually, browsing logs across multiple Pods, editing YAML in a form |
| **Resource usage** | Minimal | Higher (Electron application) |
| **Works over SSH** | Yes — runs in any terminal | No |
| **Learning curve** | Moderate — requires learning keyboard shortcuts | Low — familiar point-and-click interface |

Both tools are useful at different moments. K9s is faster for watching a deployment roll out because it stays in the terminal alongside the traffic loop. OpenLens is better for exploration — understanding how Services connect to Pods, reading logs from multiple Pods, or inspecting a resource you have not seen before.

---

**Previous:** [09d — Helm Charts](09d-helm-charts.md) · **Next:** [09 — Lab 4 Step by Step](09-lab4-step-by-step.md)
