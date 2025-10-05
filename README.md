Perfect — let’s now move to the **C3 (Component) level**, where we dive *inside each main container* (Angular SPA, API Gateway + Lambda, and DynamoDB).

This view shows **how your system’s major internal building blocks interact**, while still hiding code details (those belong in C4).

---

# C3 — Components (Inside the Major Containers)

---

## 🧭 Overview

At C3, your system contains **three core functional containers**:

1. **Angular SPA (Front-End)** – client application for all user personas.
2. **API Tier (API Gateway + Lambda)** – backend APIs implementing business logic.
3. **Data Layer (DynamoDB Global Tables)** – persistent onboarding metadata store.

Each container’s components and interactions are shown below.

---

## 1️⃣ Angular SPA (served from NGINX on ECS)

```
+-----------------------------------------------------------------------------------+
| Angular Single Page Application (SPA) – Self-Serve Onboarding Portal              |
|-----------------------------------------------------------------------------------|
| Components:                                                                      |
|                                                                                   |
|  +--------------------+   +------------------+   +------------------------------+ |
|  | UI Components      |   | Router & Guards  |   | Validation & Form Service   | |
|  | - Onboarding Form  |   | - AuthGuard      |   | - Input sanitization        | |
|  | - Request List     |   | - Route Resolver |   | - Error handling            | |
|  | - Request Detail   |   | - Role-based Nav |   | - Data shaping for API      | |
|  +---------+----------+   +---------+--------+   +---------------+-------------+ |
|            |                        |                            |               |
|            v                        v                            v               |
|  +-------------------+   +-------------------+   +------------------------------+ |
|  | Okta SDK          |   | HTTP Interceptor  |   | ApiService (REST client)    | |
|  | @okta/okta-angular|   | - Adds Bearer JWT |   | - createRequest()           | |
|  | - PKCE Login Flow |   | - Logs requests   |   | - getRequest()              | |
|  | - Token Mgmt      |   | - Retry logic     |   | - listRequests()            | |
|  +---------+----------+   +------------------+   +---------------+-------------+ |
|            |                                                       |             |
|            v                                                       v             |
|  +--------------------------------------------------------------------------------+
|  | External Interaction:                                                         |
|  |  - Calls Okta OIDC endpoints for Auth (authorize/token/revoke)                |
|  |  - Sends HTTPS requests to API Gateway with Authorization: Bearer <token>     |
|  |  - Reads config.json for base URLs per environment                            |
|  +--------------------------------------------------------------------------------+
|                                                                                   |
| Notes:                                                                            |
| - Role-based access controlled via Okta groups (onboarding-admin/viewer).         |
| - Uses Angular environment configs (dev/test/prod) to point to correct API.       |
| - Strict CSP limits connections to Okta + API only.                               |
+-----------------------------------------------------------------------------------+
```

### Key Interactions

* **Customer / Internal Ops → UI Components** → submit forms / view requests.
* **RouterGuard** checks authentication before navigating to protected routes.
* **Okta SDK** handles PKCE flow and stores tokens.
* **HTTP Interceptor** appends `Authorization` header to outbound API calls.
* **ApiService** sends HTTPS requests to backend endpoints.

---

## 2️⃣ API Tier (API Gateway + Lambda Function)

```
+--------------------------------------------------------------------------------------+
| API Gateway (HTTP API) – JWT Auth + Routing                                          |
|--------------------------------------------------------------------------------------|
| Components:                                                                         |
|  - Routes:                                                                          |
|     • POST /requests                → Lambda.post_request()                         |
|     • GET /requests/{id}            → Lambda.get_request()                          |
|     • GET /requests?customerId|status → Lambda.list_requests()                      |
|  - JWT Authorizer (Okta)                                                             |
|     • Validates issuer, audience, exp, sig                                           |
|     • Passes claims in requestContext.authorizer.jwt.claims                          |
|  - Access Logs (CloudWatch)                                                          |
|--------------------------------------------------------------------------------------|
| Interaction:                                                                        |
|  API Gateway → Validates Token → Invokes Lambda with JSON Event                      |
+--------------------------------------------------------------------------------------+

Lambda Function: onboarding_api
---------------------------------------------------------------
+---------------------------------------------------------------+
| Components:                                                   |
|                                                               |
|  +----------------------+                                     |
|  | Handler (entrypoint) |                                     |
|  | - Parses event JSON   |                                    |
|  | - Routes by HTTP verb |                                    |
|  +----------+-----------+                                    |
|             |                                              |
|             v                                              |
|  +----------+-----------+     +--------------------------+ |
|  | Auth Module          |     | Validation Module        | |
|  | - _claims_from_event |     | - schema validation      | |
|  | - _require_scope     |     | - rejects invalid input  | |
|  | - _is_admin          |     | - strips dangerous chars | |
|  +----------+-----------+     +-----------+--------------+ |
|             |                                 |             |
|             v                                 v             |
|  +----------+-----------+     +--------------+-------------+|
|  | DynamoDB Repository  |     | Response Builder           ||
|  | - put_request()      |     | - success/error JSON       ||
|  | - get_request()      |     | - consistent format        ||
|  | - query_by_customer()|     +--------------+-------------+|
|  | - query_by_status()  |                    ^              |
|  +----------+-----------+                    |              |
|             |                                |              |
|             +--------------------------------+--------------+
|                               CloudWatch Logs (structured JSON) |
|                               X-Ray traces (optional)           |
+-----------------------------------------------------------------+
| Interaction summary:                                            |
|  - API GW → Lambda (event + validated JWT)                      |
|  - Lambda → DDB (via boto3 SDK)                                 |
|  - Returns JSON to client                                       |
|  - Logs, metrics, alarms via CloudWatch                         |
+-----------------------------------------------------------------+
```

### Key Interactions

* **API Gateway**: Handles CORS, token validation, routing, and logs.
* **Lambda**: Core business logic — validates scope/role, applies idempotency, reads/writes DynamoDB.
* **DynamoDB**: Persistent store for all onboarding requests.
* **CloudWatch**: Captures metrics and logs (structured JSON for traceability).

---

## 3️⃣ Data Layer (DynamoDB Global Tables)

```
+-----------------------------------------------------------------------------------+
| DynamoDB Global Table: onboarding-requests                                        |
|-----------------------------------------------------------------------------------|
| Primary Keys:                                                                    |
|   pk = "REQ#<uuid>"       (partition key)                                        |
|   sk = "META"             (sort key)                                             |
|                                                                                   |
| GSIs:                                                                            |
|   GSI1 (byCustomer): gsi1pk="CUST#<customerId>", gsi1sk="<createdAt>"            |
|   GSI2 (byStatus):   gsi2pk="STATUS#<status>",   gsi2sk="<createdAt>"            |
|                                                                                   |
| Attributes:                                                                      |
|   requestId, customerId, workflowType, source, target, config, env, status,       |
|   createdAt, updatedAt, version (optional for optimistic locking)                 |
|                                                                                   |
| Replication:                                                                     |
|   Global Table replication between us-west-2 <=> us-east-1                        |
|   (eventual consistency, last writer wins)                                       |
|                                                                                   |
| Backups & Security:                                                              |
|   • PITR (Point-in-Time Recovery) enabled                                         |
|   • SSE-KMS encryption with CMK                                                  |
|   • IAM least-privilege policies (Lambda only)                                   |
+-----------------------------------------------------------------------------------+
```

### Key Interactions

* **Lambda → DynamoDB**:

  * `PutItem` (idempotent write with `attribute_not_exists(pk)`).
  * `Query` (by GSI for customer/status).
  * `UpdateItem` (conditional update with optimistic locking).
* **DynamoDB → Streams (optional)**:

  * Can feed analytics, audit, or cross-system triggers.
* **Global Replication**:

  * Active-active (West/East) with eventual consistency.

---

## 🔐 Cross-Cutting Components (Security / Observability)

```
+------------------------------------------------------------+
| Security & Monitoring (shared across all containers)       |
|------------------------------------------------------------|
|  • Okta (OIDC PKCE) – AuthN/AuthZ for all personas.        |
|  • WAF – L7 protection at ALB & API Gateway.               |
|  • IAM – least privilege roles per Lambda/ECS/DDB.         |
|  • KMS – encryption for logs, secrets, DynamoDB.           |
|  • Secrets Manager – credential storage, rotation.         |
|  • CloudWatch – metrics, structured logs, alarms.          |
+------------------------------------------------------------+
```

---

# 🧩 C3 Component Summary Table

| #  | Container   | Component                 | Description                                       | Interfaces                | Security / Observability                   |
| -- | ----------- | ------------------------- | ------------------------------------------------- | ------------------------- | ------------------------------------------ |
| 1  | Angular SPA | **UI Components**         | Onboarding form, list, detail views               | User → Browser            | Input validation, CSP, Okta login required |
| 2  | Angular SPA | **Router & Guards**       | Route protection, redirects unauthenticated users | Okta SDK                  | Role-based route control                   |
| 3  | Angular SPA | **Okta SDK**              | Handles PKCE login/logout/token                   | Okta endpoints            | Token storage in-memory                    |
| 4  | Angular SPA | **HTTP Interceptor**      | Attaches Bearer token to API calls                | API Gateway               | Logs failures; CORS applied                |
| 5  | Angular SPA | **ApiService**            | Calls backend REST endpoints                      | HTTPS                     | JWT required                               |
| 6  | API Tier    | **API Gateway**           | Routes REST calls to Lambda                       | SPA → HTTPS               | JWT validation, WAF, logs                  |
| 7  | API Tier    | **JWT Authorizer (Okta)** | Verifies token issuer/audience                    | API Gateway control plane | Enforces AuthN/AuthZ                       |
| 8  | API Tier    | **Lambda Handler**        | Routes request to sub-handlers                    | API Gateway               | IAM + Logs                                 |
| 9  | API Tier    | **Auth Module**           | Scope and group validation                        | JWT claims                | Deny unauthorized                          |
| 10 | API Tier    | **Validation Module**     | Input schema validation                           | Event payload             | Logs validation errors                     |
| 11 | API Tier    | **DynamoDB Repository**   | Performs CRUD using boto3                         | DynamoDB SDK              | Idempotent writes                          |
| 12 | Data Layer  | **DynamoDB Global Table** | Persists onboarding requests                      | Lambda                    | KMS encryption, PITR                       |
| 13 | Shared      | **CloudWatch**            | Central logging & alarms                          | All services              | Retention 30d                              |
| 14 | Shared      | **KMS / Secrets Manager** | Key & secret management                           | ECS/Lambda                | Rotation enabled                           |

---

# 🧭 Summary

At the **C3 level**, your architecture shows:

* The **Angular SPA** handles UI, authentication, and API integration.
* The **API Tier** (API Gateway + Lambda) encapsulates business logic, validation, and persistence.
* The **Data Layer (DynamoDB)** provides durable, active-active storage.
* Cross-cutting controls (Okta, IAM, KMS, CloudWatch) ensure security, traceability, and compliance.

---

Would you like me to now generate the **C4 (Code/Class level)** diagram next — with key Lambda classes, helper modules, and data model (aligned to this C3)?
