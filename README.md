# Architecture Overview

## High-Level Diagram (Mermaid)
```mermaid
flowchart LR
  subgraph Clients
    UI[React Admin]:::c
    Sys[Machine Clients]:::c
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
  classDef DataPlane fill:#f7fee7,stroke:#65a30d;
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

## Component Map
- **Ingress:** Transfer Family (SFTP) → S3 (ingest).  
- **Eventing (default EB):** S3 `ObjectCreated` → SQS `ingest.fifo`.  
- **Routing:** Lambda `router` performs idempotency, job creation, and either starts Step Functions or enqueues to Fargate via `work.fifo`.  
- **Orchestration:** Step Functions drives Lambda tasks (validate, stage, transform, deliver, confirm, archive).  
- **Notifications:** All progress and outcomes publish to SNS topics.  
- **Control Plane:** API Gateway + Lambdas to create/read tenant routes and job status.


---

## Disaster Recovery & Multi-Region

- **Active-Active deployment** across two AWS regions.  
- **S3 Cross-Region Replication (CRR)**: ingest and archive buckets replicate asynchronously.  
- **Multi-Region Transfer Family servers** with Route53 DNS health checks provide seamless SFTP access.  
- **SQS Queues** paired in each region; DLQs enable replay.  
- **Step Functions & Lambdas** deployed in both regions with identical definitions.  
- **DynamoDB Global Tables** provide active-active metadata consistency.  
- **SNS Topics** exist in both regions; subscriptions can be regional or global.  
- **Route53 Failover** ensures APIs and SFTP endpoints remain reachable.  
