
---

# Architecture Overview

**Date:** {today}
**Status:** Draft for Architecture Review
**Owners:** Platform Engineering / Cloud Architecture

---

## 1. Purpose

This page provides a **high-level architecture overview** of the Enterprise File Transfer (EFT) platform.
It introduces the main control plane and data plane components, their interactions, and the **Active-Active DR design** across AWS regions.

---

## 2. High-Level Architecture

```mermaid
flowchart LR
  subgraph Clients
    UI[React Admin Portal]:::c
    Sys[Machine Clients (APIs)]:::c
  end

  subgraph ControlPlane
    APIGW[API Gateway]:::cp
    CFG[Lambda: config_service]:::fn
    STS[Lambda: status_service]:::fn
    DDB[(DynamoDB: config/jobs/runs/keys)]:::db
    SNS((SNS: events/success/failure)):::sns
  end

  subgraph DataPlane
    TF[AWS Transfer Family (SFTP)]:::svc
    S3I[(S3 Ingest)]:::s3
    EB((EventBridge default)):::eb
    QI[[SQS ingest.fifo]]:::q
    RL[Lambda: router]:::fn
    SFN[[Step Functions Orchestration]]:::sfn
    QW[[SQS work.fifo]]:::q
    ECS[ECS Fargate Worker]:::svc
    S3A[(S3 Archive)]:::s3
  end

  UI -->|routes/jobs| APIGW --> CFG --> DDB
  APIGW --> STS --> DDB
  TF --> S3I --> EB -->|rule:ObjectCreated| QI --> RL --> SFN
  RL -->|large| QW --> ECS --> SNS
  RL -->|all statuses| SNS
  SFN -->|task statuses| SNS
  SFN --> S3A

  classDef cp fill:#e7f0ff,stroke:#3b82f6;
  classDef c fill:#fff7ed,stroke:#fb923c;
  classDef svc fill:#fef2f2,stroke:#ef4444;
  classDef s3 fill:#ecfeff,stroke:#06b6d4;
  classDef q fill:#f1f5f9,stroke:#475569;
  classDef fn fill:#eef2ff,stroke:#6366f1;
  classDef db fill:#f5f3ff,stroke:#7c3aed;
  classDef sfn fill:#f0fdf4,stroke:#22c55e;
  classDef sns fill:#fff1f2,stroke:#f43f5e;
  classDef eb fill:#fef9c3,stroke:#eab308;
```

---

## 3. Component Overview

| Layer             | Component               | Description                                                                  |
| ----------------- | ----------------------- | ---------------------------------------------------------------------------- |
| **Clients**       | React Admin Portal      | Self-service UI for onboarding, route management, and monitoring             |
|                   | Machine Clients (APIs)  | Automated integrations using API Gateway                                     |
| **Control Plane** | API Gateway             | Exposes control APIs securely                                                |
|                   | Config Service (Lambda) | Manages tenant routes in DynamoDB                                            |
|                   | Status Service (Lambda) | Queries job status from DynamoDB                                             |
|                   | DynamoDB                | Stores config, jobs, and idempotency keys                                    |
|                   | SNS Topics              | Publishes events, success, and failure notifications                         |
| **Data Plane**    | Transfer Family (SFTP)  | Managed ingress for partner uploads                                          |
|                   | S3 Ingest               | Landing zone for files; encrypted and CRR enabled                            |
|                   | EventBridge             | Detects `ObjectCreated` and routes to SQS                                    |
|                   | SQS ingest.fifo         | Ordered, deduplicated job events                                             |
|                   | Router Lambda           | Routes jobs → Step Functions or ECS                                          |
|                   | Step Functions          | Orchestrates job pipeline (validate → stage → transform → deliver → archive) |
|                   | SQS work.fifo           | Queue for large jobs needing ECS                                             |
|                   | ECS Fargate Worker      | Processes large file jobs                                                    |
|                   | S3 Archive              | Long-term storage with lifecycle policies                                    |

---

## 4. Disaster Recovery & Multi-Region

* **Active-Active Deployment** across Region A and Region B.
* **S3 Cross-Region Replication (CRR):** Ingest + archive buckets replicate between regions.
* **DynamoDB Global Tables:** Multi-region job/config metadata sync.
* **Multi-Region Transfer Family Servers:** SFTP ingress in both regions.
* **Route53 Failover:** Health checks direct traffic to healthy region.
* **SNS Topics:** Regional, with cross-region subscriptions for resiliency.
* **Targets:** RPO = 0, RTO < 15 minutes.

---

## 5. Design Principles

* **Event-Driven:** Object-created events flow asynchronously.
* **Idempotent:** Lambdas and Step Functions safe for retries.
* **Decoupled:** Control plane APIs separate from data plane.
* **Observable:** Metrics, logs, dashboards, SNS notifications.
* **Resilient:** Active-Active deployment ensures business continuity.


