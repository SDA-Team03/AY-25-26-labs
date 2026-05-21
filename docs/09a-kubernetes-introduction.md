# Kubernetes — Introduction

---

## What Kubernetes Is

Kubernetes (often abbreviated **K8s**) is an open source **container orchestration platform** originally developed at Google and donated to the Cloud Native Computing Foundation (CNCF) in 2014. Its job is to automate the deployment, scaling, networking, and self-healing of containerised workloads across a cluster of machines.

Where Docker solves the problem of running a single container on a single machine, Kubernetes solves the problem of running many containers across many machines — keeping them alive, distributing traffic across them, replacing them when they crash, and updating them without downtime.

For this laboratory, the most important thing to understand about Kubernetes is not its full feature set, but the small subset of its primitives that govern **how services are deployed and updated**. That is where the interesting architectural decisions live.

---

## The Problem Kubernetes Solves

Consider what happens when you deploy the email worker from Lab 3 in production:

- You need multiple instances for fault tolerance and throughput
- When you push a bug fix, you need to update all instances without dropping any in-flight processing
- If the new version is broken, you need to roll back within seconds, not minutes
- If traffic spikes, you need to add instances without restarting everything
- If a machine dies, the instances on it must restart automatically on healthy machines

Doing this with plain Docker and shell scripts is possible but fragile. Kubernetes provides a declarative API where you describe the **desired state** — "I want three replicas of this container image" — and the system continuously reconciles reality towards that description. You stop thinking about individual containers and start thinking about workloads.

---

## Core Concepts

### Pod

The **Pod** is the smallest deployable unit in Kubernetes. A Pod wraps one or more containers that share a network namespace (same IP address and port space) and a set of storage volumes. In practice, most Pods contain exactly one container.

Every Pod has a unique IP address within the cluster, but that IP is ephemeral — it changes when the Pod is replaced. You never address Pods directly in production; you address Services (see below).

```
Pod
├── Container (your app)
│   ├── Ports
│   └── Environment variables
├── Volumes (shared storage)
└── Lifecycle hooks
```

### Deployment

A **Deployment** is a higher-level object that manages a set of identical Pods. You tell the Deployment:

- Which container image to run
- How many replicas you want
- How to perform updates (strategy: `RollingUpdate` or `Recreate`)
- Health check configuration (readiness and liveness probes)

The Deployment creates and manages a **ReplicaSet** (an object that ensures a specific number of Pod replicas are running at all times). When you update the Deployment's pod template (e.g. change the image tag), Kubernetes creates a new ReplicaSet with the new spec and gradually migrates traffic from the old to the new — this is the rolling update.

```
Deployment (desired state: 3 replicas of image v1)
└── ReplicaSet-a (3/3 ready)
    ├── Pod-1 (Running, image: myapp:1.0.0)
    ├── Pod-2 (Running, image: myapp:1.0.0)
    └── Pod-3 (Running, image: myapp:1.0.0)
```

After updating the image to v2:

```
Deployment (desired state: 3 replicas of image v2)
├── ReplicaSet-a (0/3, scaling down)
└── ReplicaSet-b (3/3 ready, scaling up)
    ├── Pod-4 (Running, image: myapp:2.0.0)
    ├── Pod-5 (Running, image: myapp:2.0.0)
    └── Pod-6 (Running, image: myapp:2.0.0)
```

### Service

A **Service** provides a stable network endpoint in front of a dynamic set of Pods. Pods come and go; the Service IP (called a ClusterIP) stays fixed. The Service uses a **selector** — a set of key-value labels — to identify which Pods should receive traffic. Kubernetes' built-in load balancer (kube-proxy) distributes connections across all matching Pods.

```
Service (selector: app=webapp)
    ↓  routes traffic to
├── Pod-1 (label: app=webapp)
├── Pod-2 (label: app=webapp)
└── Pod-3 (label: app=webapp)
```

The Service selector is the mechanism that makes **blue-green deployment** and **canary releases** possible with plain Kubernetes: you add or remove a label from the selector to route traffic to a different set of Pods.

### Namespace

A **Namespace** is a virtual partition of a Kubernetes cluster. Resources in different namespaces are isolated from each other by name — you can have a `webapp` Deployment in the `staging` namespace and a different `webapp` Deployment in the `production` namespace without conflict. This lab uses a dedicated `mzinga-lab4` namespace to keep all resources isolated and easy to clean up.

### ConfigMap and Secret

A **ConfigMap** holds non-sensitive configuration data as key-value pairs. A **Secret** holds sensitive data (passwords, tokens) in base64-encoded form. Both can be injected into Pods as environment variables or mounted as files. In this lab, environment variables are defined directly in the Deployment spec for simplicity — in a production cluster you would extract them into ConfigMaps and Secrets.

### Readiness and Liveness Probes

These are health checks that Kubernetes runs against every Pod:

- **Readiness probe** — determines whether a Pod should receive traffic. A Pod that fails its readiness probe is removed from the Service's endpoint list. During a rolling update, Kubernetes waits for a new Pod to pass its readiness probe before terminating an old one. Without a readiness probe, a new Pod receives traffic as soon as it starts, which may be before the application is initialised.

- **Liveness probe** — determines whether a Pod should be restarted. A Pod that fails its liveness probe repeatedly is killed and restarted by the kubelet. This enables automatic recovery from deadlocks and hangs.

Both probes are defined on the container and can use HTTP GET, TCP socket, or command execution.

---

## Cluster Architecture

A Kubernetes cluster has two logical tiers:

### Control Plane

The control plane hosts the Kubernetes API and the controllers that implement the reconciliation loops. In a minikube cluster, the entire control plane runs on a single VM or Docker container.

| Component | Role |
|-----------|------|
| **API Server** | The entry point for all cluster operations. `kubectl` sends requests here. |
| **etcd** | Distributed key-value store. The only source of truth for cluster state. |
| **Scheduler** | Assigns Pods to nodes based on resource availability and constraints. |
| **Controller Manager** | Runs the reconciliation loops: Deployment controller, ReplicaSet controller, Service controller, etc. |

### Worker Nodes

Worker nodes run the actual workloads. Each node runs:

| Component | Role |
|-----------|------|
| **kubelet** | Agent that ensures the containers described in Pod specs are running and healthy. |
| **kube-proxy** | Manages iptables rules to implement Service routing on this node. |
| **Container runtime** | Runs containers (Docker, containerd, or CRI-O). |

In a minikube cluster there is typically one node that acts as both the control plane and the worker. In production, control plane and worker nodes are separate machines.

---

## Declarative Configuration

Kubernetes resources are described in **YAML manifests**. A manifest declares what you want, not how to achieve it:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: webapp
spec:
  replicas: 3
  selector:
    matchLabels:
      app: webapp
  template:
    metadata:
      labels:
        app: webapp
    spec:
      containers:
      - name: webapp
        image: myapp:1.0.0
        ports:
        - containerPort: 8080
```

You apply a manifest with `kubectl apply -f manifest.yaml`. Kubernetes computes the difference between the current state and the declared state and makes the necessary changes. Applying the same manifest twice is safe — it is idempotent.

This declarative model is what makes deployment strategies tractable: switching from blue to green is as simple as patching one field in a Service manifest and applying it. Kubernetes handles the rest.

---

## How This Relates to the MZinga Architecture Journey

Labs 1–3 focused on **how** to structure and instrument a service: extracting the email worker from the monolith, decoupling it via REST and events, and instrumenting it with OpenTelemetry.

Lab 4 focuses on **how** to deploy and update that service in production. The architectural decisions shift from code structure to operational strategy:

- How do you update the worker when the new version may be incompatible with messages already in the queue?
- How do you test a new version on production traffic without exposing all users to a potential regression?
- How do you roll back in under a minute if a deployment introduces a latency spike?

These are not Kubernetes-specific questions. They are questions that any production system must answer. Kubernetes provides the primitives to implement the answers. The deployment strategies you will practise in this lab — in-place rolling update, blue-green deployment, and canary release — are the standard patterns used to answer them.

---

**Next:** [09b — Minikube Setup](09b-minikube-setup.md) · [09 — Lab 4 Step by Step](09-lab4-step-by-step.md)
