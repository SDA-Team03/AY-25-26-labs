# Patterns Relevant to the MZinga Communications Evolution

---

## Patterns for the Monolith Itself

### Anti-Corruption Layer (ACL)

When the external worker starts consuming data from MZinga — whether via the database or the REST API — it will encounter MZinga's internal data model: Payload relationship references (`{ relationTo, value }`), Slate AST rich text, and Payload-specific pagination shapes. The ACL is a translation layer inside the worker that converts MZinga's model into the worker's own domain model. Without it, MZinga's internal conventions leak into the worker and create invisible coupling. If MZinga's schema changes, only the ACL needs updating, not the worker's core logic.

### Facade

Already partially present — `MailUtils.ts` is a thin facade over Nodemailer's `transport.sendMail`. The same pattern should be applied to the delivery channels in the worker: a `CommunicationChannel` interface with concrete implementations for SMTP, Slack, and any future channel. The worker's core logic calls the interface and never knows which transport is underneath.

---

## Patterns for the Migration Phase

### Branch by Abstraction

A companion to the Strangler Fig. Where the Strangler Fig works at the service boundary (routing traffic between old and new), Branch by Abstraction works inside the monolith's codebase. You introduce an abstraction over the capability you want to replace — in this case, an `EmailDispatcher` interface — make the existing SMTP code implement it, then build the new queue-based dispatcher behind the same interface. A feature flag or environment variable switches between them. This lets you test the new path in production with a subset of documents before removing the old implementation entirely. It is safer than directly replacing the hook body.

### Parallel Run

During the migration phase, both the old in-process SMTP sender and the new external worker process the same `Communications` document simultaneously. Their outputs are compared — delivery success, timing, recipient lists — but only one result is used (the old one, until the new one is trusted). This is how you build confidence in the new service without exposing users to its failures. It requires the `status` field and a comparison log, but no user-facing change.

### Feature Toggle (Feature Flag)

Controls which path is active — the in-process hook or the external worker — at runtime without a deployment. In MZinga's context this could be as simple as an environment variable:

```bash
COMMUNICATIONS_USE_EXTERNAL_WORKER=true
```

Combined with Branch by Abstraction, it gives you the ability to roll back instantly if the worker misbehaves in production.

---

## Patterns for the External Worker

### Outbox Pattern

Directly relevant to Step 1 and Step 2. When the `afterChange` hook writes `status: "pending"` to MongoDB, that write and the original document save happen in the same MongoDB operation — but if the worker crashes before reading the pending document, or if the status write fails after the document is saved, you have a consistency gap. The Outbox pattern formalises this: the monolith writes an explicit `outbox` collection entry in the same transaction as the document save. The worker reads from the outbox, processes, and deletes the entry. This guarantees at-least-once delivery without distributed transactions.

### Idempotent Consumer

A direct consequence of at-least-once delivery. If the worker crashes after sending the email but before writing `status: "sent"`, RabbitMQ will redeliver the message and the email will be sent twice. The worker must be idempotent — it checks whether `status` is already `sent` before processing, and uses a deduplication key (the document `id`) to detect redeliveries.

> This is not optional in any reliable messaging system.

### Dead Letter Queue (DLQ)

When a message fails processing repeatedly — for example because a user's email address is malformed or the Slack API is down — it should not block the queue. After a configurable number of retries, RabbitMQ moves the message to a dead letter exchange. The worker team monitors the DLQ, investigates failures, and replays messages manually or automatically after fixing the root cause.

> This is the missing retry and error handling that the current `Communications.ts` hook lacks entirely.

### Competing Consumers

Multiple instances of the worker subscribe to the same RabbitMQ queue. RabbitMQ distributes messages across them. This gives horizontal scalability with no coordination logic in the worker itself — relevant when `sendToAll` generates hundreds of pending communications simultaneously.

---

## Patterns for the Event-Driven Step

### Event Carried State Transfer

In Step 3, the worker receives a RabbitMQ message containing only `doc.id` and then calls `GET /api/communications/:id` to fetch the full document. This is the **Event Notification** sub-pattern — lightweight event, data fetched on demand. The alternative is **Event Carried State Transfer**: the full document payload is embedded in the RabbitMQ message itself (which `WebHooks.ts` lines 82–95 already does — `doc`, `data`, `operation`, `previousDoc` are all included). This eliminates the REST API call entirely, reducing latency and the number of moving parts, at the cost of larger message payloads and the risk of acting on stale data if the document is updated between publish and consume.

### Saga

If sending a communication involves multiple steps that can each fail independently — resolve recipients, render HTML, send SMTP, post to Slack, write status back — a Saga coordinates them as a sequence of compensatable steps. If the Slack post succeeds but the SMTP send fails, the Saga knows which steps to retry or roll back.

> In MZinga's current scope this is likely over-engineering, but it becomes relevant as soon as a single `Communications` document needs to dispatch to multiple channels and partial failure needs to be handled gracefully.

### Event Sourcing *(future consideration)*

Rather than storing only the current `status` of a `Communications` document, store every state transition as an immutable event: `created`, `pending`, `dispatching`, `sent`, `failed`, `retried`. The current state is derived by replaying the events. This gives a complete audit trail of every delivery attempt — who was notified, when, via which channel, and whether it succeeded — which is directly relevant for compliance in enterprise and SaaS contexts.

---

## Patterns for Deployment and Release

These patterns govern how a service moves from a built artifact to a running version in production — and how that transition is made safe, reversible, and observable. They become relevant once the email worker exists as a standalone service (States 1–3) and needs to be updated without disrupting ongoing communications processing.

### Immutable Infrastructure

A container image, once built, is never modified. New requirements or bug fixes produce a new image tag; the old image is replaced, not patched. This is the foundational premise of all Kubernetes deployment strategies — Pods are disposable units that are replaced as a group or individually, never modified in place while running.

For the email worker, immutability means every change produces a new tagged image (`email-worker:1.2.0`, `email-worker:1.3.0`). The image registry becomes the authoritative record of what ran in production at any point in time. Rollback is a re-deploy of the previous tag, not a reversal of a sequence of manual changes — a critical difference when diagnosing production incidents.

### Health Endpoint Monitor

A dedicated HTTP endpoint — conventionally `/health` — that reports whether the service instance is ready to receive traffic. In Kubernetes this is the target of the readiness probe. The critical distinction is between **running** (the process is alive) and **ready** (initialised and able to serve requests correctly). A worker that starts its HTTP server before completing its RabbitMQ connection or before obtaining a valid JWT token is running but not ready.

Without a correct health endpoint, rolling updates and canary releases cannot safely gate traffic: Kubernetes would route requests to a Pod that has started but not yet established its dependencies, causing failures that would not have occurred if the Pod had simply waited another two seconds. The health endpoint is the contract between the service and the orchestrator — the service decides when it is ready, and the infrastructure respects that signal.

### Graceful Shutdown

On receiving a termination signal (`SIGTERM`), the service stops accepting new work, completes in-flight processing, and exits cleanly. In Kubernetes, `terminationGracePeriodSeconds` (default 30 seconds) defines how long the Pod has to complete this sequence before being forcibly killed.

For the email worker this has a concrete consequence: if the worker receives `SIGTERM` while it has already called `PATCH /api/communications/:id` with `status: "processing"` but has not yet sent the email, the document is left in `processing` state indefinitely. The next version of the worker must detect and recover these orphaned documents — adding complexity that would not exist if the original worker had simply finished its current document before exiting. Graceful shutdown eliminates this class of consistency gap.

> Graceful shutdown is the invisible prerequisite for zero-downtime deployment. A service that ignores `SIGTERM` makes every rolling update destructive regardless of the Kubernetes strategy configured.

### Parallel Change (Expand-Contract)

A schema evolution pattern that makes rolling updates and canary releases safe for changes to message formats, database schemas, or API contracts. Instead of replacing the old format with the new one in a single deployment — which would make v1 and v2 simultaneously incompatible and force a Recreate or Blue-Green strategy — the change is decomposed into three sequential deployments:

1. **Expand** — deploy a version that reads and writes both the old and new format. No existing consumer or producer breaks. The queue, the database, and the API accept both shapes.
2. **Migrate** — once all instances are running the expanded version, begin writing the new format exclusively. Old instances can still read it because the expanded version already handled both.
3. **Contract** — once no instances of the old version remain, deploy a final version that drops the old format entirely.

Applied to the email worker: if the RabbitMQ message schema changes from `{ "doc_id": "abc123" }` to `{ "communication_id": "abc123", "tenant": "acme" }`, a direct single-deployment replacement would cause v1 worker Pods — still running during a rolling update — to fail to parse v2 messages. Expand-Contract publishes both keys during the transition window, allowing both versions to consume from the same queue without errors.

> This pattern converts a breaking change — one that requires Recreate (downtime) or Blue-Green (double resources) — into a backwards-compatible change that any strategy can handle safely. The cost is three deployments instead of one and temporary code complexity in the expanded state. The trade-off is almost always worth it when the service handles real user data.

### Dark Launch

A variant of canary release where the new version receives a copy of every production request but its responses are discarded — only internal metrics and logs are observed. Users are never exposed to the new version's output. This eliminates user-facing risk entirely while preserving the ability to test the new version against real production traffic volumes and data shapes.

In a queue-based context — directly relevant to the email worker — dark launch does not require HTTP request duplication infrastructure. The worker subscribes to a shadow copy of the RabbitMQ queue, processes messages with the same logic, but writes results to a comparison log rather than back to the MZinga API. Error rates, processing times, and rendered output can be compared between the shadow run and the live run before any user is affected.

> Dark launch is particularly relevant for the email worker when changing the `slate_to_html` rendering logic: the new renderer can be validated against real `Communications` document bodies, with rendered HTML compared between versions, without sending any emails to real recipients.

---

## Summary Map

| Phase | Pattern | Concern it solves |
|---|---|---|
| Monolith | Anti-Corruption Layer | Prevents MZinga's internal model leaking into the worker |
| Monolith | Facade | Abstracts delivery channel behind a common interface |
| Migration | Branch by Abstraction | Safe in-process switch between old and new dispatcher |
| Migration | Parallel Run | Validates new worker against old path before cutover |
| Migration | Feature Toggle | Runtime switch without redeployment, instant rollback |
| Worker | Outbox Pattern | Guarantees at-least-once delivery without distributed transactions |
| Worker | Idempotent Consumer | Prevents duplicate sends on message redelivery |
| Worker | Dead Letter Queue | Isolates poison messages, enables retry without blocking the queue |
| Worker | Competing Consumers | Horizontal scaling with no coordination logic |
| Event-driven | Event Carried State Transfer | Eliminates REST API call, reduces latency |
| Event-driven | Saga | Coordinates multi-channel dispatch with compensatable steps |
| Event-driven | Event Sourcing | Full audit trail of every delivery attempt |
| Deployment | Immutable Infrastructure | Ensures rollback is a re-deploy of a previous tag, not a reversal of manual changes |
| Deployment | Health Endpoint Monitor | Gates traffic during rolling updates and canary — only ready Pods receive requests |
| Deployment | Graceful Shutdown | Prevents in-flight work loss on Pod termination in any deployment strategy |
| Deployment | Parallel Change (Expand-Contract) | Converts breaking schema or protocol changes into backwards-compatible ones, enabling rolling/canary |
| Deployment | Dark Launch | Tests new version against real production traffic with zero user-facing exposure |

---

**Previous:** [04 — The Strangler Fig Pattern](04-strangler-fig-pattern.md) · **Next:** [05b — Infrastructure Reference](05b-infrastructure-reference.md)
