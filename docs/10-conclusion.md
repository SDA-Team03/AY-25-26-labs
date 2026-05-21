# Conclusion: The Full Journey — From Monolith to Scalable Microservice

---

## Overview

The four laboratories in this course follow a single thread: an architectural problem in a real production system, resolved through a sequence of decisions that each introduce new capability and new constraint. The problem is specific — MZinga's synchronous in-process email sending blocks HTTP requests when the recipient list is large — and the resolution is progressive: a feature flag, then an external polling worker, then an API-decoupled worker, then an event-driven worker with horizontal scaling, and at every step a question of how to deploy the change without breaking what already works.

This document looks at the entire journey from the deployment perspective: not what changed architecturally, but how each change could be safely delivered to a running system using the strategies from Lab 4. The answer is different at each step, and the reasons are grounded in the specific coupling between the components at that moment in the evolution.

---

## Part 1 — Deploying the Monolith Change: Blue-Green and the Feature Toggle as a Two-Level Canary

### What Changed

The first change is entirely within `mzinga-apps`. The `afterChange` hook in `Communications.ts` is modified to support a feature flag: when `COMMUNICATIONS_USE_EXTERNAL_WORKER=false` (or absent), the hook behaves exactly as before — it sends email synchronously, blocking the request until every SMTP call completes. When the flag is `true`, the hook only writes `status: "pending"` and returns immediately, leaving the actual delivery to the external worker.

This is a backwards-compatible change at the code level: the old behaviour is preserved by default. But it is still a change to a production monolith that serves real tenants, and it must be deployed without risk.

### Why Blue-Green for the mzinga-apps Deployment

A rolling update would work mechanically — the new mzinga-apps version is backwards compatible — but it introduces a transitional period where some Pods run the new code and some run the old. For most changes this is acceptable. For a change to the communications hook specifically, it is slightly unsettling: if a `Communications` document is created while its HTTP request is routed to an old Pod, it is processed synchronously; if routed to a new Pod (flag off by default), it is also processed synchronously. The behaviour is identical, so the transitional period is harmless. The reason to prefer blue-green here is not technical safety but operational confidence: blue-green lets you deploy the full new version, run smoke tests against it in isolation (the green slot), and verify that the flag mechanism is wired correctly before switching a single real request to it. The old version (blue) continues handling all production traffic during this verification. If anything is wrong — the flag variable is mis-spelled, the hook wiring is broken, the configuration loading has a regression — rollback is a single selector patch back to blue. No re-deploy, no rolling replacement, no waiting.

### The Feature Toggle as a Second-Level Canary

Once the green slot is live and verified, and traffic has been switched to it (flag still off, behaviour still synchronous), the feature flag becomes its own deployment mechanism. Enabling `COMMUNICATIONS_USE_EXTERNAL_WORKER=true` for a specific tenant, or for a percentage of requests via an application-level check, is a canary release that operates entirely below the infrastructure layer. No Kubernetes manifests change. No Pods are restarted.

```
Infrastructure level:  [ mzinga-apps v1 (blue) ] → [ mzinga-apps v2 (green, flag off) ]
                                                      Blue-Green switch ↑

Application level:     [ flag off → synchronous ] → [ flag on for tenant A → async ]
                                                      Feature Toggle canary ↑
```

This two-level approach is particularly valuable because the two rollback mechanisms operate at different speeds and scopes. If the new async path misbehaves for tenant A, disabling the flag for that tenant is an environment variable change — seconds. If there is a deeper regression in the new mzinga-apps version regardless of the flag, rolling back to blue is a selector patch — also seconds, and it restores the old behaviour for everyone simultaneously. The flag gives you fine-grained control over the behavioural rollout; the blue-green infrastructure gives you coarse-grained control over the version rollout. Having both simultaneously means you are never more than one action away from restoring safe behaviour.

---

## Part 2 — Deploying the First Worker (Lab 1): A Clean Slate

### A New Service Has No Previous Version

The Lab 1 DB-coupled worker is a new process that has never existed in production before. Deploying it for the first time is unconstrained: there is no previous version to conflict with, no in-flight state that could be disrupted, and no user traffic that could be routed to it by mistake. A rolling update, a blue-green deploy, or even a simple `kubectl apply` all produce the same outcome. The deployment strategy for the worker itself does not matter here.

What matters is the **sequence** relative to the mzinga-apps flag.

### The Correct Activation Sequence

The mzinga-apps flag and the worker must not be activated simultaneously without verification between them:

1. **Deploy mzinga-apps with the flag available but off** (blue-green, as described above). No documents go to the worker yet — the hook still sends synchronously.
2. **Deploy the worker** and verify it is healthy: it connects to MongoDB, polls successfully, and processes a test document. This can be done against a staging `Communications` entry without touching the feature flag at all.
3. **Enable the feature flag** (Feature Toggle). From this moment, real `Communications` documents begin accumulating with `status: "pending"` and the worker starts processing them.

This sequence decouples three concerns that are easy to conflate: the code deployment of mzinga-apps, the code deployment of the worker, and the behavioural activation of the async path. Each can be verified independently and each has its own rollback mechanism. If the worker has a bug that surfaces only under real document shapes, disabling the flag stops new documents from reaching it immediately — documents already queued as `pending` remain queued until the worker is fixed, but no new ones are added.

---

## Part 3 — The v1-to-v2 Worker Transition: Why Recreate Is the Only Safe Option

### The Concurrent Access Race

Worker v1 (Lab 1) reads `Communications` documents directly from MongoDB using `pymongo`. Worker v2 (Lab 2) reads the same documents via the MZinga REST API (`GET /api/communications?where[status][equals]=pending`). Both workers use the `status` field to claim documents: they find `pending` documents, update the status to `processing`, send the email, then write `sent` or `failed`.

The status field is necessary for correctness, but it is not sufficient to make the two workers safe to run simultaneously. The reason is the read-then-write gap.

Consider what happens during a rolling update where one v1 Pod and one v2 Pod are running at the same time:

1. At time T, both workers execute their poll query. Both observe document X with `status: "pending"`.
2. Worker v1 writes directly to MongoDB: `db.communications.updateOne({ _id: X }, { $set: { status: "processing" } })`.
3. Worker v2 calls `PATCH /api/communications/X` with body `{ "status": "processing" }`. The API executes this write against the same MongoDB instance. It succeeds — it sets the status to `"processing"`, which it already is. No error is returned.
4. Both workers now believe they own document X and proceed to send the email.
5. The recipient receives two identical emails.

The `status` field creates the illusion of mutual exclusion. In reality it provides eventual consistency: the last write wins, but both writers have already passed the point of no return by the time the second write completes. The root issue is that the claim operation — "read pending, write processing" — is not atomic. MongoDB's `findAndModify` (or `findOneAndUpdate`) would provide atomic compare-and-set, but neither worker uses it: v1 performs a separate query and a separate update, and v2 does the same via two separate HTTP calls.

A canary release makes this worse, not better: with nine v1 Pods and one v2 Pod, the probability of a concurrent claim is low but non-zero, and the damage — a duplicate email to a real user — is irreversible.

### Recreate Is the Correct Strategy

The only safe way to transition from v1 to v2 is to ensure they are never running simultaneously. This is precisely what `strategy.type: Recreate` provides: Kubernetes terminates all v1 Pods before creating any v2 Pods.

The downtime window for this transition is:
- v1 Pods receive `SIGTERM` and finish their current document (graceful shutdown)
- A brief gap where no worker is running — `pending` documents accumulate but are not processed
- v2 Pods start, pass their readiness probe, and begin polling

For the email worker, this gap is typically a few seconds to a minute depending on `terminationGracePeriodSeconds` and Pod startup time. During this window, no `Communications` documents are processed — they remain in `status: "pending"` and are picked up by v2 as soon as it starts. No emails are lost, no emails are duplicated, and no data is corrupted. A brief delay in delivery is the acceptable cost of a safe transition.

> The feature flag remains relevant here. Before initiating the Recreate transition, disable `COMMUNICATIONS_USE_EXTERNAL_WORKER` temporarily. During the gap — from the moment v1 Pods terminate until v2 Pods become ready — new `Communications` documents will fall through to the synchronous hook path (flag off), sending email immediately. Once v2 is ready and verified, re-enable the flag. This eliminates the delivery gap entirely, at the cost of one brief flag toggle.

---

## Part 4 — The v2-to-v3 Transition: Coordinating Two Simultaneous Changes

### The Compounding Constraint

The transition from the REST API worker (Lab 2) to the RabbitMQ event-driven worker (Lab 3) is complicated by a fact that the v1-to-v2 transition did not have: **the worker change and the mzinga-apps configuration change are not independent**. Enabling RabbitMQ message publishing in mzinga-apps (`HOOKSURL_COMMUNICATIONS_AFTERCHANGE=rabbitmq`) and deploying the RabbitMQ-consuming worker must be coordinated. If you enable publishing before the consumer is ready, events accumulate in the queue but v2 is still polling via REST — both v2 (polling) and v3 (consuming) may attempt to process the same document. If you deploy v3 before enabling publishing, v3 receives nothing and v2 handles everything — no conflict, but v3 is idle.

The second scenario is the safer one, and it suggests the correct deployment sequence.

### The Dark Deploy Sequence

The correct approach is a variant of the **Dark Launch** pattern: deploy the new service before activating it, verify it in the live environment without user impact, then activate it by switching the configuration.

```
Phase 1: v2 running, v3 deployed but idle
─────────────────────────────────────────
  mzinga-apps (HOOKSURL_COMMUNICATIONS_AFTERCHANGE=pending_status_only)
    │
    └── Worker v2 (REST API polling) → processes documents
    └── Worker v3 (RabbitMQ consumer) → connected, idle, no messages arriving

Phase 2: activate v3, decommission v2
──────────────────────────────────────
  1. Scale Worker v2 to 0 replicas — let it drain current documents
  2. Enable HOOKSURL_COMMUNICATIONS_AFTERCHANGE=rabbitmq in mzinga-apps
     (rolling restart of mzinga-apps Pods, backwards compatible)
  3. Worker v3 begins receiving events → active
```

Step 1 is a `kubectl scale` command. Steps 2 and 3 happen automatically when mzinga-apps Pods restart with the new environment variable. The gap between step 1 (v2 drained) and step 3 (v3 receiving messages) is the mzinga-apps rolling restart — during which new `Communications` documents write `status: "pending"` but no worker processes them. This gap is typically 30–60 seconds as each mzinga-apps Pod restarts one by one.

To eliminate this gap entirely: perform the mzinga-apps rolling restart **before** scaling v2 to 0. During the rolling restart of mzinga-apps, some Pods publish to RabbitMQ and some write `pending` status only. v2 is still running and handles all `pending` documents from the Pods not yet restarted. v3 handles events from the Pods that have already restarted. For this brief overlap to be safe, v2 and v3 must not compete for the same documents — and they do not, because they consume from different channels (REST API poll vs RabbitMQ queue). A document that enters via RabbitMQ is consumed by v3; a document that enters via the pending status (old Pods) is consumed by v2. No race.

> The `status` field provides one more safeguard here: v2 only polls for `status: "pending"` documents. Once v3 picks up a RabbitMQ event and writes `status: "processing"` via the REST API, v2 will not pick up that document on its next poll. The channels are different but the coordination mechanism is shared.

### The mzinga-apps Config Change Is a Rolling Update

Adding `HOOKSURL_COMMUNICATIONS_AFTERCHANGE=rabbitmq` to mzinga-apps' environment is a backwards-compatible change: Pods with the new config publish to RabbitMQ; Pods without it write `pending` status. There is no moment where a Pod becomes unable to serve requests. A rolling update of mzinga-apps is appropriate and sufficient.

---

## Part 5 — Why RabbitMQ Makes Horizontal Scaling Safe

### The Polling Race Is Inherent

Workers v1 and v2 both use a polling model. Every instance of the worker repeatedly queries for `status: "pending"` documents and claims them by writing `status: "processing"`. This works correctly with a single instance, but with multiple instances the claim operation is not atomic: two instances can observe the same document as `pending` before either writes `processing`, and both proceed to send the email.

Making polling safe with multiple instances requires one of:
- Running a single instance only (no horizontal scaling)
- A distributed lock (Redis SETNX, MongoDB findAndModify with a compare-and-set) wrapping the claim operation
- A coordinated lease or leader election so only one instance polls at a time

All three approaches add complexity and operational overhead. The single-instance constraint is the simplest but eliminates the scaling benefit entirely. The distributed lock approaches work but put the coordination burden on the application code.

### Queue Delivery as the Coordination Primitive

Worker v3 receives a RabbitMQ message. RabbitMQ delivers each message to exactly one consumer from the subscribed group. This is not an application-level claim — it is a guarantee provided by the message broker's delivery semantics. Once a message is delivered to consumer A, it becomes invisible to consumer B until consumer A either ACKs (success, message deleted) or NACKs/crashes (message redelivered, but to exactly one other consumer).

```
Polling model (v1, v2):
  MongoDB / REST API → [instance A sees X] → race → [instance B also sees X]
                                                        ↑ application must prevent this

Queue model (v3):
  RabbitMQ → [delivers X to instance A] → [instance A ACKs → X deleted]
  RabbitMQ → [delivers Y to instance B] → [instance B ACKs → Y deleted]
                    ↑ infrastructure prevents any instance from seeing both X and Y
```

With worker v3, scaling from 1 to 10 replicas is a single command:

```sh
kubectl scale deployment/email-worker --replicas=10 -n mzinga
```

All 10 instances subscribe to the same durable queue. RabbitMQ distributes messages across them. Each `Communications` document is processed by exactly one instance. No coordination code is required in the worker, no distributed locks, no leader election. This is the **Competing Consumers** pattern — and it is the architectural reason why the event-driven worker is not merely a different way to receive documents but a qualitatively different deployment model.

The `sendToAll` path in `Communications.ts` (lines 148–172) can generate hundreds of `Communications` documents in a single operation. With worker v1 or v2 running as a single instance, these are processed sequentially — one email every few seconds. With worker v3 running as 10 instances, all 10 consume from the queue in parallel, multiplying throughput tenfold with no code change and no risk of duplication.

> Idempotency remains necessary even with RabbitMQ. If a consumer sends the email but crashes before ACKing, RabbitMQ redelivers the message. The worker must check `status` before sending — if it is already `sent`, skip. This is the **Idempotent Consumer** pattern from the catalogue. RabbitMQ eliminates the concurrent claim race; it does not eliminate the need for idempotency in crash recovery scenarios.

---

## Part 6 — The Full Deployment Timeline

The table below summarises every significant deployment in the four-lab journey, the strategy used, and the architectural reason that strategy is correct at that moment.

| Deployment event | Strategy | Reason |
|---|---|---|
| mzinga-apps v1 → v2 (add feature flag) | **Blue-Green** | Verify new hook wiring in isolation before switching any traffic; instant rollback without re-deploy if flag mechanism is broken |
| Enable `COMMUNICATIONS_USE_EXTERNAL_WORKER` flag | **Feature Toggle** | Application-level canary; rollback is a variable change, not a deployment |
| Lab 1 worker (first deploy) | Any — **Rolling Update** sufficient | New service, no previous version, no conflicting state |
| Lab 1 worker v1 → Lab 2 worker v2 | **Recreate** | v1 (DB) and v2 (API) cannot claim documents atomically; concurrent operation produces duplicate emails |
| Lab 2 worker v2 → Lab 3 worker v3 (dark phase) | **Rolling Update** (new Deployment) | v3 deployed but idle; no conflict with v2 which is still polling; verify v3 connectivity before activating |
| Lab 2 worker v2 decommission | **Scale to 0** | Drain in-flight documents gracefully before activating RabbitMQ publishing |
| mzinga-apps config change (`HOOKSURL_COMMUNICATIONS_AFTERCHANGE=rabbitmq`) | **Rolling Update** | Backwards-compatible config addition; Pods with new config publish to RabbitMQ, Pods without it still write `pending` status |
| Lab 3 worker scale-out (1 → N replicas) | **kubectl scale** | RabbitMQ delivery semantics provide coordination; no application-level change required |

---

## Closing Reflection

The four laboratories demonstrate a principle that is easy to state but difficult to internalise without concrete experience: **deployment strategy is not an afterthought. It is a first-class architectural constraint that must be considered at the same time as the design decision itself.**

The choice to use a shared MongoDB database in Lab 1 is not only a coupling decision — it is a deployment decision. It means that the transition from Lab 1 to Lab 2 cannot be a rolling update. The choice to use a polling model in Labs 1 and 2 is not only a latency decision — it is a scaling decision. It means that horizontal scale-out requires coordination that the application code must provide.

Conversely, the choice to use RabbitMQ in Lab 3 is not only a decoupling decision — it unlocks a deployment capability. The event-driven worker can be scaled to N replicas with no code change and no deployment risk, because the coordination that polling workers must implement explicitly is provided implicitly by the queue's delivery semantics. The architecture of the service and the operational behaviour of its deployments are inseparable.

The patterns from Lab 4 — rolling update, recreate, blue-green, canary — are not a menu to choose from arbitrarily. Each one is a response to a specific set of constraints: whether two versions can coexist, whether the change is backwards compatible, whether resources allow double environments, whether observability is in place to validate a gradual rollout. Understanding the constraints is the skill; the patterns are the vocabulary for expressing the solution.

---

**Previous:** [09 — Lab 4 Step by Step](09-lab4-step-by-step.md)
