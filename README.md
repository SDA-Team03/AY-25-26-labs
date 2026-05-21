# AY-25-26-labs
Laboratories

## Documentation

Read in order — each document builds on the previous one.

| # | Document | Contents |
|---|---|---|
| 1 | [Laboratory Introduction](docs/01-laboratory-introduction.md) | What MZinga is, why a real system matters, and the four-state architecture journey |
| 2 | [Architecture Evolution: Four States from Monolith to Event-Driven](docs/02-architecture-evolution.md) | Pattern-by-pattern walkthrough of each architectural state with code references |
| 3 | [Communications Email Flow & Decoupling Guide](docs/03-communications-email-flow.md) | Line-by-line walkthrough of the current email flow and the specific code changes to decouple it |
| 4 | [The Strangler Fig Pattern](docs/04-strangler-fig-pattern.md) | Deep dive into the primary migration pattern: origin, mechanics, and limitations |
| 5 | [Supporting Patterns Catalogue](docs/05-supporting-patterns-catalogue.md) | Full catalogue of patterns relevant across all four states |
| 5b | [Infrastructure Reference: MongoDB and RabbitMQ](docs/05b-infrastructure-reference.md) | MongoDB standalone vs replica set, RabbitMQ exchanges, queues, vhosts, and auth |
| 6 | [Lab 1 Step by Step](docs/06-lab1-step-by-step.md) | DB-coupled Python worker, feature flag, status field, end-to-end verification |
| 6b | [Lab 1 Code Snippets](docs/06-lab1-code-snippets.md) | All code snippets for Lab 1 with macOS, Linux, and Windows variants |
| 7 | [Lab 2 Step by Step](docs/07-lab2-step-by-step.md) | REST API worker (core) + event-driven RabbitMQ worker (optional extension) |
| 7b | [Lab 2 Code Snippets](docs/07-lab2-code-snippets.md) | All code snippets for Lab 2 with macOS, Linux, and Windows variants |
| 8 | [Lab 3 Step by Step](docs/08-lab3-step-by-step.md) | Observability: structured logging, OpenTelemetry traces and spans, Prometheus metrics |
| 8b | [Lab 3 Code Snippets](docs/08-lab3-code-snippets.md) | Full instrumented worker with structlog, OpenTelemetry, and Prometheus |
| 9a | [Kubernetes Introduction](docs/09a-kubernetes-introduction.md) | What Kubernetes is, core concepts (Pod, Deployment, Service), and why it matters for deployment strategies |
| 9b | [Minikube Setup](docs/09b-minikube-setup.md) | Install and run minikube on macOS, Linux, Windows WSL, and Windows native (assumes Docker already installed) |
| 9c | [Docker Setup](docs/09c-docker-setup.md) | Install Docker Engine or Docker Desktop on macOS, Linux, Windows WSL, and Windows native — reference if Docker is not already present |
| 9d | [Helm Charts](docs/09d-helm-charts.md) | From plain Kubernetes YAML to Helm: parameterisation, release tracking, application-level rollback, multi-component applications, and deploying MZinga with the official Helm chart |
| 9e | [Kubernetes UI Tools](docs/09e-k8s-ui-tools.md) | K9s (terminal UI) and OpenLens (desktop GUI) — installation on macOS, Linux, and Windows, and how to use them to observe deployments in this lab |
| 9 | [Lab 4 Step by Step](docs/09-lab4-step-by-step.md) | Deployment models: in-place rolling update, blue-green deployment, and canary release with Kubernetes |
| 9c | [Lab 4 Code Snippets](docs/09-lab4-code-snippets.md) | All Kubernetes manifests, Dockerfile, and commands for all three deployment strategies |
| 10 | [Conclusion](docs/10-conclusion.md) | The full journey across all four labs: how each architectural transition constrained the deployment strategy, why Recreate was mandatory for the v1→v2 worker switch, how RabbitMQ unlocks safe horizontal scaling, and a complete deployment timeline |