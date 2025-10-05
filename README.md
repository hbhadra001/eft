Perfect — let’s keep it **C1 level (System Context)**: only *system as a black box, external personas, and external systems*.

Here are the **C1 components with descriptions** you can use in your ARB deck:

---

## 🎯 C1 – System Context Components & Descriptions

### **System (in scope)**

* **Self-Serve Onboarding Portal**

  * **What:** The overall system being built — a web portal for customers and internal teams to onboard file transfer requests and query statuses.
  * **How it’s used:**

    * Hosts the **Angular SPA** front-end (served to browsers).
    * Exposes APIs (backed by AWS) for metadata submission and queries.
  * **Boundary:** Internal technical implementation (ECS, ALB, API Gateway, DynamoDB, etc.) is hidden at this level.

---

### **Personas (actors)**

* **Customer (External Partner/User)**

  * Uses the portal to create onboarding requests (providing metadata such as source, target, environment).
  * Can log in securely and track the status of requests.

* **Internal Onboarding Team (Ops/Support Analyst)**

  * Internal staff who manage or assist onboarding.
  * Can log in with elevated roles (e.g., review, approve, troubleshoot requests).

* **Platform Engineer / IT (Administrator/Maintainer)**

  * Internal technical team responsible for running and maintaining the system.
  * Not a “functional user,” but interacts indirectly by operating, monitoring, and securing the system.

---

### **External Systems (dependencies)**

* **Okta (Identity Provider)**

  * Provides secure authentication and authorization using OIDC PKCE.
  * Issues ID/Access tokens (JWTs) with scopes and groups.
  * Ensures only authenticated and authorized users can access the portal and APIs.

* **(Optional) External File Transfer Endpoints**

  * Future integration: customer or partner SFTP/S3 endpoints where files are ultimately moved.
  * At C1, these are “external systems” if onboarding metadata references them.

---

## 🖼 C1 in Words (what the diagram shows)

* The **Self-Serve Onboarding Portal** sits in the center as *the system under design*.
* **Customers** and **Internal Ops** log in to it (via **Okta** for authentication).
* **Platform Engineers** interact indirectly by maintaining the system.
* The **Portal** may reference **external file endpoints** but doesn’t expose internal infra details.

---

✅ This way, **C1 tells the “who and what” story** for executives and the ARB — while **C2+ diagrams dive into the “how”** (ECS, ALB, API Gateway, DynamoDB).

---

👉 Do you want me to also **redraw the C1 diagram** in simple text (personas + system + Okta + optional external endpoints) with these descriptions alongside, so you can present one clean slide?
