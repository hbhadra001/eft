

# Executive Summary – Enterprise File Transfer (EFT)

**Date:** {today}
**Status:** Draft for Architecture Review
**Owners:** Platform Engineering / Cloud Architecture

---

## 1. Purpose

The Enterprise File Transfer (EFT) platform is designed to provide a **secure, scalable, and resilient** service for managing partner and internal file exchanges.
This summary highlights the **business drivers**, **goals**, **non-goals**, and **expected outcomes**.

---

## 2. Business Drivers

* Increasing number of partner integrations with inconsistent onboarding processes.
* Compliance requirements for encryption, auditability, and retention.
* Need for high availability and **Active-Active DR** to support business-critical file flows.
* Operational efficiency: reduce manual provisioning and monitoring.

---

## 3. Goals

* **Self-Service Onboarding**: Partners configure routes, delivery targets, and transforms via UI/API.
* **Security & Compliance**: End-to-end encryption, IAM-based controls, CloudTrail/Audit support.
* **Reliability & Scale**: Handle thousands of daily jobs with predictable latency and fault tolerance.
* **Observability**: Metrics, logs, dashboards, and SNS notifications for transparency.
* **Resilience**: Multi-region Active-Active DR strategy with S3 CRR, DynamoDB Global Tables, and Route53 failover.

---

## 4. Non-Goals

* Building custom SFTP or proprietary messaging services (we leverage AWS Transfer Family, SQS, SNS).
* Developing custom IAM/SSO solutions (integrate with existing identity providers instead).
* Providing deep analytics or ML-based enrichment in this phase (planned for future).
* Replacing enterprise ETL tools (scope limited to secure file transfer).

---

## 5. Expected Outcomes

* **Unified EFT Platform**: Standardized onboarding and file transfer model across the enterprise.
* **Reduced Operational Burden**: Automation of provisioning and monitoring.
* **Improved Partner Experience**: Faster onboarding, reliable delivery, proactive notifications.
* **Audit & Compliance Ready**: End-to-end traceability and policy enforcement.
* **Future-Proof Architecture**: Extensible for additional use cases like file transformations and analytics.

---

## 6. Success Metrics

* Partner onboarding completed in **< 1 business day**.
* ≥ **99.9% availability** over 30 days.
* **P95 job latency ≤ 10 minutes** (for ≤ 2GB files).
* **Zero data loss**, leveraging S3 durability and CRR.
* 100% of jobs logged and retrievable via DynamoDB.

---

## 7. Next Steps

* Pilot onboarding with selected partners.
* Conduct DR failover testing.
* Finalize operations playbooks.
* Committee approval for production rollout.

---

# Enterprise File Transfer (EFT) — Executive Summary
**Date:** 2025-09-03  
**Status:** Draft for Architecture Review  
**Owners:** Platform Eng / Data Eng  
**Repo:** `cfs-enterprise-sns.zip` (attach/upload in Confluence or host in Git)  

## TL;DR
We propose a serverless, event‑driven EFT platform on AWS. Files land in S3 via AWS Transfer Family (SFTP). 
S3 events flow through the **default EventBridge bus** into **SQS (ingest.fifo)**. A lightweight **Router Lambda** starts a **Step Functions** orchestration for normal jobs or enqueues large jobs to **ECS Fargate**.  
All lifecycle and progress notifications publish to **SNS** (no custom EventBridge bus).

## Goals
- Self‑service onboarding of partners/tenants and routes.
- Reliable, auditable, encrypted file movement and transformations.
- Operate at scale with strong idempotency and backpressure.
- Minimal operational surface (managed, serverless‑first).

## Non‑Goals
- Building a custom identity provider for SFTP. (Use Transfer Family service-managed users, can extend later.)
- Building a custom queueing/messaging layer beyond SQS/SNS.

## Key Decisions
- **No custom EventBridge bus**; keep default bus only for S3→SQS.  
- **SNS for notifications** (events/success/failure topics).  
- **Router Lambda** triggers orchestration (instead of EventBridge Pipes or SQS→SFN direct).  
- **KMS everywhere** and strict least-privilege IAM.

## Outcomes & SLAs (targets)
- Availability: ≥ 99.9% (SLO).  
- End‑to‑end latency (ingest → confirm): P95 ≤ 10 min for ≤ 2 GB; large files go to Fargate.  
- RPO = 0 (S3 durable storage); RTO ≤ 1h (IaC redeploy + managed services).

