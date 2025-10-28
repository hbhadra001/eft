Awesome goal. Here’s a battle-tested, low-maintenance **daily test framework** for your Lambda file-transfer platform (SFTP⇄S3). It gives you synthetic end-to-end checks, integrity validation, clear metrics, and instant alerts when a new/updated flow breaks.

# What we’ll stand up

* **Test matrix** (all 4 directions): S3→S3, S3→SFTP, SFTP→S3, SFTP→SFTP
* **Synthetic files** with embedded manifest + SHA-256 checksum
* **Orchestrator**: AWS Step Functions runs each test case
* **Source seeders**: put test files onto S3/SFTP sources before the transfer
* **Validators**: verify arrival, size, checksum, latency SLO
* **Results & metrics**: DynamoDB item per test run + CloudWatch metrics/alarms
* **Daily schedule**: EventBridge → Step Functions
* **One-click add**: drop a JSON test case in DynamoDB to cover a new flow

---

# High-level flow (daily)

1. **EventBridge** (cron) → **Step Functions** “DailyFileFlowTests”.
2. For each enabled test case in **DynamoDB** (partition key = flow_id):
   a) **GenerateTestData** (small/medium/large variants; PII-free)
   b) **SeedSource** (S3 putObject or SFTP upload)
   c) **InvokeTransfer** (call your production Lambda with that flow’s config or just let your existing scheduler pick it up naturally if the flow is event-driven)
   d) **PollTarget** (exponential backoff until file arrives or timeout)
   e) **Validate** (size, SHA-256, optional line counts, record latency)
   f) **RecordResults** (DynamoDB + CloudWatch metrics), **Cleanup** (optional)
   g) On failure → **SNS/Slack** alert with precise cause + correlation ids.

---

# Sequence (text)

```
EventBridge -> StepFunctions(DailyFileFlowTests)
  -> Lambda:ListEnabledTests
    -> for each test_case:
       -> Lambda:GenerateTestData
       -> Lambda:SeedSource (S3 put or Paramiko to SFTP)
       -> Lambda:InvokeTransfer (sync invoke OR drop trigger file)
       -> Lambda:PollTarget (list+get; SFTP or S3)
       -> Lambda:Validate (SHA256, bytes, SLA)
       -> Lambda:RecordResults (DDB + CloudWatch PutMetricData)
       -> Lambda:Cleanup (delete or archive)
```

---

# Test case schema (DynamoDB item)

Use one table, e.g. `fileflow_tests` (PK: `flow_id`, SK: `version`), with GSI for `enabled=true`.

```json
{
  "flow_id": "acme_sftp_to_s3_prod",
  "version": 3,
  "enabled": true,
  "source": {
    "type": "SFTP",                       // S3 | SFTP
    "host": "s-xxxx.server.transfer.us-west-2.amazonaws.com",
    "port": 22,
    "username": "acme",
    "dir": "/inbox",
    "secret_arn": "arn:aws:secretsmanager:...:secret:sftp/acme"     // holds private key/pass
  },
  "target": {
    "type": "S3",
    "bucket": "poc-target-prod",
    "prefix": "partners/acme/inbox/",
    "kms_key_arn": "arn:aws:kms:...:key/..."
  },
  "transfer": {
    "lambda_arn": "arn:aws:lambda:...:function:file-transfer",
    "payload": { "flowConfigId": "acme-prod" },  // what your Lambda expects
    "timeout_seconds": 900
  },
  "validation": {
    "expect_within_seconds": 420,
    "checksum": "SHA256",                // always compute & compare
    "size_tolerance_bytes": 0,
    "post_arrival_wait_seconds": 15      // handle eventual consistency on SFTP listings
  },
  "testdata": {
    "size_bytes": 5242880,               // 5 MB; also run a tiny 4KB & optional 100MB case
    "pattern": "random",                 // or 'csv','jsonl','fixedwidth'
    "filename_prefix": "diag",
    "delete_after": true,
    "tags": ["synthetic","daily"]
  },
  "alerts": {
    "sns_topic_arn": "arn:aws:sns:...:fileflow-test-alerts",
    "slack_webhook_secret_arn": "arn:aws:secretsmanager:...:slack/webhook"
  }
}
```

---

# S3 layout & lifecycle

* Tag all synthetic objects: `flow_id`, `test_run_id`, `synthetic=true`.
* Apply lifecycle: expire after 3–7 days.
* For SFTP targets, optionally a **/test/** subfolder you can auto-purge.

---

# Integrity strategy (checksums & manifests)

* For each test file `diag_YYYYMMDD_HHMMSS_uuid.dat`, create sibling manifest:

  * `diag_... .sha256` (hex digest) and `diag_... .manifest.json` with:

    * `flow_id`, `test_run_id`, `generated_at`, `size`, `sha256`, `schema_ver`
* On target, **download then hash** and match SHA-256 exactly.
* For S3 large files (multipart), don’t rely on ETag—always compute SHA-256 yourself.

---

# Step Functions outline (Amazon States Language)

(Skeleton—keep per-state Lambdas small and single-purpose.)

```json
{
  "Comment": "Daily file-flow tests",
  "StartAt": "ListEnabledTests",
  "States": {
    "ListEnabledTests": { "Type": "Task", "Resource": "arn:aws:lambda:...:list-tests", "Next": "MapTests" },
    "MapTests": {
      "Type": "Map",
      "ItemsPath": "$.tests",
      "MaxConcurrency": 4,
      "Iterator": {
        "StartAt": "GenerateTestData",
        "States": {
          "GenerateTestData": { "Type": "Task", "Resource": "arn:aws:lambda:...:gen-testdata", "Next": "SeedSource" },
          "SeedSource": { "Type": "Task", "Resource": "arn:aws:lambda:...:seed-source", "Next": "InvokeTransfer" },
          "InvokeTransfer": { "Type": "Task", "Resource": "arn:aws:lambda:...:invoke-transfer", "Next": "PollTarget" },
          "PollTarget": { "Type": "Task", "Resource": "arn:aws:lambda:...:poll-target", "Next": "Validate" },
          "Validate": { "Type": "Task", "Resource": "arn:aws:lambda:...:validate", "Next": "RecordResults" },
          "RecordResults": { "Type": "Task", "Resource": "arn:aws:lambda:...:record-results", "Next": "Cleanup" },
          "Cleanup": { "Type": "Task", "Resource": "arn:aws:lambda:...:cleanup", "End": true }
        }
      },
      "Next": "EndState"
    },
    "EndState": { "Type": "Succeed" }
  }
}
```

---

# EventBridge schedule (daily, 6:00 AM PT)

```hcl
# Terraform
resource "aws_cloudwatch_event_rule" "daily_tests" {
  name                = "fileflow-daily-tests"
  schedule_expression = "cron(0 13 * * ? *)" # 13:00 UTC = 06:00 PT (standard)
}

resource "aws_cloudwatch_event_target" "daily_tests_sf" {
  rule      = aws_cloudwatch_event_rule.daily_tests.name
  arn       = aws_sfn_state_machine.daily_tests.arn
  input     = jsonencode({ "trigger": "daily" })
}

resource "aws_iam_role" "events_to_sfn" {
  name = "events-to-sfn"
  assume_role_policy = data.aws_iam_policy_document.events_assume.json
}

resource "aws_iam_role_policy" "events_to_sfn" {
  role   = aws_iam_role.events_to_sfn.id
  policy = data.aws_iam_policy_document.events_to_sfn.json
}

data "aws_iam_policy_document" "events_to_sfn" {
  statement {
    actions   = ["states:StartExecution"]
    resources = [aws_sfn_state_machine.daily_tests.arn]
  }
}
```

---

# Lambda snippets (key parts)

## 1) Generate test data (Python)

```python
import os, hashlib, json, uuid, time
from datetime import datetime, timezone

def handler(event, context):
    td = event["testdata"]
    flow_id = event["flow_id"]
    run_id = f"{flow_id}-{uuid.uuid4()}"
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    fname = f'{td["filename_prefix"]}_{ts}_{run_id}.dat'
    data = os.urandom(td["size_bytes"]) if td["pattern"] == "random" else b"x" * td["size_bytes"]

    sha = hashlib.sha256(data).hexdigest()
    manifest = {
        "flow_id": flow_id, "test_run_id": run_id, "generated_at": ts,
        "size": len(data), "sha256": sha, "schema_ver": 1
    }
    return { "file": {"name": fname, "bytes": len(data), "sha256": sha, "content_b64": data.hex()}, "manifest": manifest }
```

*(Tip: for big files, write to /tmp and stream; don’t base64 huge payloads between states.)*

## 2) Seed S3 source

```python
import boto3, binascii
s3 = boto3.client("s3")

def handler(event, _):
    src = event["source"]; f = event["file"]; man = event["manifest"]
    if src["type"] != "S3": return event
    key = f'{src.get("prefix","")}{f["name"]}'
    body = binascii.unhexlify(f["content_b64"])
    s3.put_object(Bucket=src["bucket"], Key=key, Body=body, Tagging="synthetic=true")
    s3.put_object(Bucket=src["bucket"], Key=key + ".manifest.json", Body=json.dumps(man).encode())
    s3.put_object(Bucket=src["bucket"], Key=key + ".sha256", Body=(man["sha256"]+"\n").encode())
    event["seeded_key"] = key
    return event
```

## 3) Seed SFTP source (Paramiko)

```python
import json, binascii, base64, io, paramiko, boto3
secrets = boto3.client("secretsmanager")

def handler(event, _):
    src = event["source"]; f = event["file"]; man = event["manifest"]
    if src["type"] != "SFTP": return event

    sec = json.loads(secrets.get_secret_value(SecretId=src["secret_arn"])["SecretString"])
    key = paramiko.RSAKey.from_private_key(io.StringIO(sec["privateKey"]))
    t = paramiko.Transport((src["host"], src.get("port",22)))
    t.connect(username=src["username"], pkey=key)
    sftp = paramiko.SFTPClient.from_transport(t)

    data = binascii.unhexlify(f["content_b64"])
    remote_path = f'{src["dir"].rstrip("/")}/{f["name"]}'
    with sftp.file(remote_path, "wb") as fp: fp.write(data)
    with sftp.file(remote_path + ".manifest.json", "wb") as fp: fp.write(json.dumps(man).encode())
    with sftp.file(remote_path + ".sha256", "wb") as fp: fp.write((man["sha256"]+"\n").encode())
    sftp.close(); t.close()

    event["seeded_path"] = remote_path
    return event
```

## 4) Invoke transfer Lambda

```python
import boto3, json, time
lam = boto3.client("lambda")

def handler(event, _):
    tr = event["transfer"]
    lam.invoke(
        FunctionName=tr["lambda_arn"],
        InvocationType="Event",                 # async
        Payload=json.dumps(tr.get("payload",{})).encode()
    )
    event["invoked_at"] = int(time.time())
    return event
```

## 5) Poll target (S3 or SFTP)

```python
import time, boto3, json, io, paramiko
from hashlib import sha256
s3 = boto3.client("s3")

def handler(event, _):
    tgt = event["target"]; f = event["file"]; v = event["validation"]
    deadline = event["invoked_at"] + v["expect_within_seconds"]

    while time.time() < deadline:
        if tgt["type"] == "S3":
            key = f'{tgt.get("prefix","")}{f["name"]}'
            try:
                obj = s3.get_object(Bucket=tgt["bucket"], Key=key)
                data = obj["Body"].read()
                event["target_data"] = data.hex()
                break
            except s3.exceptions.NoSuchKey:
                pass
        else:
            # SFTP
            sec = json.loads(boto3.client("secretsmanager").get_secret_value(SecretId=tgt["secret_arn"])["SecretString"])
            key = paramiko.RSAKey.from_private_key(io.StringIO(sec["privateKey"]))
            t = paramiko.Transport((tgt["host"], tgt.get("port",22))); t.connect(username=tgt["username"], pkey=key)
            sftp = paramiko.SFTPClient.from_transport(t)
            path = f'{tgt["dir"].rstrip("/")}/{f["name"]}'
            try:
                with sftp.file(path, "rb") as fp: data = fp.read()
                sftp.close(); t.close()
                event["target_data"] = data.hex()
                break
            except IOError:
                sftp.close(); t.close()
        time.sleep(5)

    event["arrived"] = "target_data" in event
    return event
```

## 6) Validate (size + SHA-256)

```python
import binascii, hashlib, boto3
cloudwatch = boto3.client("cloudwatch")

def handler(event, _):
    ok = event.get("arrived", False)
    reason = None
    if not ok:
        reason = "Timeout waiting for target"
    else:
        src_sha = event["manifest"]["sha256"]
        data = binascii.unhexlify(event["target_data"])
        sha = hashlib.sha256(data).hexdigest()
        if sha != src_sha: ok, reason = False, f"Checksum mismatch {sha} != {src_sha}"
        elif len(data) != event["file"]["bytes"]: ok, reason = False, "Size mismatch"

    # Metrics
    cloudwatch.put_metric_data(
        Namespace="FileFlowTests",
        MetricData=[
            {"MetricName":"RunSuccess","Value":1.0 if ok else 0.0, "Unit":"Count",
             "Dimensions":[{"Name":"FlowId","Value":event["flow_id"]}]}
        ]
    )
    event["ok"] = ok
    event["reason"] = reason
    return event
```

---

# Alarms & dashboard

* **Metric**: `FileFlowTests/RunSuccess` (per `FlowId`)
* **Alarm**: if `Average < 1` over 1 evaluation period → **SNS → Slack**
* Optional: `TransferLatencySeconds` (time from seed to arrival), set SLO (e.g., ≤ 300s).
* **Dashboard**: per flow: today’s success, 7-day sparkline, p95 latency.

---

# IAM & security notes

* Each Lambda gets **least-privilege** policies (S3 readonly/put on test prefixes only; SecretsManager `GetSecretValue` on specific ARNs; KMS decrypt on stated CMKs).
* Use **VPC endpoints** for S3/Secrets if Lambdas are in VPC.
* Keep **test IAM** separate from prod operators; tag resources `synthetic=true`.

---

# Adding a new/updated flow

1. Insert a new **test case item** in `fileflow_tests` (enabled=true, correct dirs/buckets, secrets).
2. The next daily run auto-picks it up. (You can also start the SFN **ad-hoc** after deploying a new flow to catch regressions immediately.)

---

# Nice-to-have extensions

* Run **three sizes** per flow: 4 KB (smoke), 5 MB (typical), 100 MB (stress).
* **Negative tests**: wrong creds / permission denied → assert graceful failure paths.
* **Contract tests**: verify directory existence and KMS permissions separately before E2E.
* **Canary health for endpoints**: hourly SFTP `ls` and S3 `head` (quick signal, tiny cost).
* **Traceability**: propagate `test_run_id` in your transfer Lambda logs; build a simple **CloudWatch Log Insights** query pinned to the dashboard.

---

If you want, I can package this into **Terraform modules** (DDB table, SFN, Lambdas, EventBridge, IAM), plus a **/tests** repo skeleton with the Python handlers above and a sample `Makefile` to deploy.



Yes—you can absolutely swap DynamoDB for S3 to keep things simple. Here’s a clean pattern that keeps your **configs + test artifacts + results** all in one bucket and still plays nicely with Step Functions/Lambda.

# S3-based layout

```
s3://fileflow-tests/
  config/
    flows/
      acme_sftp_to_s3_prod.json
      globex_s3_to_sftp_prod.json
    groups/                       # optional (run subsets)
      nightly.json                # ["acme_sftp_to_s3_prod","globex_s3_to_sftp_prod"]
  seeds/                          # (optional) pre-made payloads
  results/
    dt=2025-10-25/flow_id=acme_sftp_to_s3_prod/run_id=.../run.json
    dt=2025-10-25/flow_id=acme_sftp_to_s3_prod/metrics.csv
  manifests/
    dt=2025-10-25/flow_id=.../diag_...manifest.json
```

### Example flow config (S3 object: `config/flows/acme_sftp_to_s3_prod.json`)

```json
{
  "flow_id": "acme_sftp_to_s3_prod",
  "enabled": true,
  "source": { "type": "SFTP", "host": "s-xxxx.server.transfer.us-west-2.amazonaws.com",
              "port": 22, "username": "acme", "dir": "/inbox",
              "secret_arn": "arn:aws:secretsmanager:...:secret:sftp/acme" },
  "target": { "type": "S3", "bucket": "poc-target-prod", "prefix": "partners/acme/inbox/" },
  "transfer": { "lambda_arn": "arn:aws:lambda:...:function:file-transfer",
                "payload": { "flowConfigId": "acme-prod" }, "timeout_seconds": 900 },
  "validation": { "expect_within_seconds": 420, "checksum": "SHA256", "size_tolerance_bytes": 0 },
  "testdata": { "size_bytes": 5242880, "pattern": "random", "filename_prefix": "diag", "delete_after": true },
  "alerts": { "sns_topic_arn": "arn:aws:sns:...:fileflow-test-alerts" }
}
```

# What changes vs the DynamoDB design

## 1) “ListEnabledTests” Lambda → read from S3

* **Where:** `config/flows/*.json`
* **Filter:** `enabled=true` inside the JSON (or keep enabled configs under `config/enabled/` and “disabled” under `config/disabled/`—whichever you prefer).
* **Versioning:** turn on S3 Versioning so edits are roll-backable.

```python
# list_tests_s3.py
import boto3, json
s3 = boto3.client("s3")

BUCKET = "fileflow-tests"
PREFIX = "config/flows/"

def handler(event, _):
    tests = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=PREFIX):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            body = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
            cfg = json.loads(body)
            if cfg.get("enabled", True):
                tests.append(cfg)
    return { "tests": tests }
```

## 2) “RecordResults” → write to S3 (and still push CloudWatch metrics)

```python
# record_results_s3.py
import json, os, time, boto3
from datetime import datetime, timezone
s3 = boto3.client("s3")
cw = boto3.client("cloudwatch")

BUCKET = "fileflow-tests"

def handler(event, _):
    dt = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    flow = event["flow_id"]; run_id = event.get("manifest", {}).get("test_run_id","no-runid")
    key = f"results/dt={dt}/flow_id={flow}/run_id={run_id}/run.json"
    s3.put_object(Bucket=BUCKET, Key=key, Body=json.dumps(event).encode(), ContentType="application/json")

    cw.put_metric_data(
        Namespace="FileFlowTests",
        MetricData=[{"MetricName":"RunSuccess","Value":1.0 if event.get("ok") else 0.0,
                     "Unit":"Count","Dimensions":[{"Name":"FlowId","Value":flow}]}]
    )
    return event
```

## 3) (Optional) Query results with Athena

* Store `run.json` as **JSON** (fine) or emit a **row per run** CSV/Parquet too:

  * `results/dt=YYYY-MM-DD/flow_id=.../metrics.csv`
    Create a Glue table partitioned by `dt` and `flow_id` for dashboards.

# Pros / cons of S3 vs DynamoDB

**Pros**

* Super simple ops (one bucket); cheap; versioning gives easy rollbacks.
* Natural home for manifests, synthetic files, and results together.
* Easy to audit/edit configs (Git → CI → `aws s3 sync`).

**Cons**

* No conditional updates / atomic counters like DynamoDB (but you likely don’t need them).
* Listing large numbers of configs is O(N) reads (usually fine; paginate).
* If you later need complex queries (by tag, by env, by owner), you’ll hand-roll that in code or move to Athena/Glue.

*(FYI: Amazon S3 provides strong read-after-write consistency for PUTs/DELETEs/LISTs, so edits to `config/` will be visible to the next run without weirdness.)*

# Terraform sketch (bucket + policy)

```hcl
resource "aws_s3_bucket" "fileflow_tests" { bucket = "fileflow-tests" }
resource "aws_s3_bucket_versioning" "v" {
  bucket = aws_s3_bucket.fileflow_tests.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_lifecycle_configuration" "lc" {
  bucket = aws_s3_bucket.fileflow_tests.id
  rule {
    id     = "expire-results"
    status = "Enabled"
    filter { prefix = "results/" }
    expiration { days = 30 }
  }
}
# Grant Lambdas s3:GetObject on config/* and s3:PutObject on results/*
```

# Step Functions change

* Swap the first state’s `Resource` to your new `list-tests-s3` Lambda; rest of the machine stays the same.

# Small usability tips

* **Enable/disable** by moving a file between `config/enabled/` and `config/disabled/` (or toggle the `enabled` flag).
* **Groups:** keep named lists in `config/groups/*.json` to run subsets on demand (ad-hoc execution input `{ "group": "nightly" }`).
* **Validation diffs:** write a short `summary.txt` next to `run.json` so failures are visible in the S3 console without downloading.

---

If you want, I can drop in the full Lambda package + a minimal Terraform module (`s3_config_store`) that wires the IAM least-privilege and updates the state machine to read configs from S3.


Awesome — here’s a **production-grade mini-repo** you can drop into a GitHub project and deploy. It implements the S3-backed config store you chose, covers **all four directions** (S3→S3, S3→SFTP, SFTP→S3, SFTP→SFTP) with **checksums, latency SLOs**, and comes with **pytest smoke & negative tests** (timeout, checksum mismatch, size mismatch, SFTP failures).

I’ve kept files tight but complete. You can extend, but you don’t need to “fill in the blanks.”

---

# Repo layout

```
fileflow-tests/
├─ README.md
├─ requirements.txt
├─ template.yaml                     # SAM (or use Terraform if you prefer)
├─ stepfunctions/
│  └─ daily_fileflow_tests.asl.json
├─ lambdas/
│  ├─ common/
│  │  ├─ __init__.py
│  │  ├─ env.py
│  │  ├─ logging.py
│  │  ├─ s3io.py
│  │  ├─ secrets.py
│  │  ├─ sftp_client.py
│  │  └─ hashing.py
│  ├─ list_tests_s3/
│  │  └─ app.py
│  ├─ gen_testdata/
│  │  └─ app.py
│  ├─ seed_source/
│  │  └─ app.py
│  ├─ invoke_transfer/
│  │  └─ app.py
│  ├─ poll_target/
│  │  └─ app.py
│  ├─ validate/
│  │  └─ app.py
│  ├─ record_results/
│  │  └─ app.py
│  └─ cleanup/
│     └─ app.py
└─ tests/
   ├─ conftest.py
   ├─ test_list_tests_s3.py
   ├─ test_gen_testdata.py
   ├─ test_seed_source_s3.py
   ├─ test_seed_source_sftp.py
   ├─ test_poll_target_s3_success.py
   ├─ test_poll_target_timeout.py
   ├─ test_validate_ok.py
   ├─ test_validate_checksum_mismatch.py
   ├─ test_validate_size_mismatch.py
   ├─ test_record_results.py
   └─ test_end_to_end_s3_to_s3.py    # smoke E2E
```

---

# Infrastructure notes (quick)

* **S3 bucket** (config+results): `FILEFLOW_CONFIG_BUCKET` (env var)

  * Structure:

    ```
    config/flows/*.json
    results/dt=YYYY-MM-DD/flow_id=.../run_id=.../run.json
    ```
* **Lambdas**: Each directory in `lambdas/*` is a function.
* **Step Functions**: `stepfunctions/daily_fileflow_tests.asl.json`
* **Schedule**: EventBridge cron to start the state machine daily.
* **IAM**: Least-privilege (see README).

---

# Code

## `lambdas/common/env.py`

```python
import os

def must_get(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v

FILEFLOW_CONFIG_BUCKET = must_get("FILEFLOW_CONFIG_BUCKET")
NAMESPACE = os.getenv("METRIC_NAMESPACE", "FileFlowTests")
```

## `lambdas/common/logging.py`

```python
import json, logging, os, sys
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logger = logging.getLogger()
for h in list(logger.handlers):
    logger.removeHandler(h)
h = logging.StreamHandler(sys.stdout)
fmt = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
h.setFormatter(fmt)
logger.addHandler(h)
logger.setLevel(LOG_LEVEL)

def jlog(level, msg, **kv):
    getattr(logger, level.lower())(msg + " " + json.dumps(kv))
```

## `lambdas/common/hashing.py`

```python
import hashlib, io

def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def sha256_stream(stream: io.BufferedReader, chunk=1024*1024) -> str:
    h = hashlib.sha256()
    for c in iter(lambda: stream.read(chunk), b""):
        h.update(c)
    return h.hexdigest()
```

## `lambdas/common/s3io.py`

```python
import boto3, json
from .env import FILEFLOW_CONFIG_BUCKET
s3 = boto3.client("s3")

def read_json(bucket, key):
    obj = s3.get_object(Bucket=bucket, Key=key)
    return json.loads(obj["Body"].read())

def write_json(bucket, key, data: dict):
    s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(data).encode(), ContentType="application/json")

def read_config_objects(prefix="config/flows/"):
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=FILEFLOW_CONFIG_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            yield obj["Key"]

def put_bytes(bucket, key, data: bytes, tagging=None):
    extra = {}
    if tagging:
        extra["Tagging"] = tagging
    s3.put_object(Bucket=bucket, Key=key, Body=data, **extra)

def get_bytes(bucket, key) -> bytes:
    return s3.get_object(Bucket=bucket, Key=key)["Body"].read()
```

## `lambdas/common/secrets.py`

```python
import boto3, json
_secrets = boto3.client("secretsmanager")

def get_secret_json(secret_arn: str) -> dict:
    val = _secrets.get_secret_value(SecretId=secret_arn)
    if "SecretString" in val:
        return json.loads(val["SecretString"])
    raise RuntimeError("Binary secrets not supported for this flow.")
```

## `lambdas/common/sftp_client.py`

```python
from typing import Optional
import paramiko, io

class SFTPClientWrapper:
    def __init__(self, host: str, port: int, username: str, private_key_pem: str, timeout=30):
        self.host, self.port, self.username, self.timeout = host, port, username, timeout
        self._key = paramiko.RSAKey.from_private_key(io.StringIO(private_key_pem))
        self._t = None
        self._sftp = None

    def __enter__(self):
        self._t = paramiko.Transport((self.host, self.port))
        self._t.connect(username=self.username, pkey=self._key)
        self._sftp = paramiko.SFTPClient.from_transport(self._t)
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self._sftp: self._sftp.close()
        finally:
            if self._t: self._t.close()

    def put_bytes(self, remote_path: str, data: bytes):
        with self._sftp.file(remote_path, "wb") as fp:
            fp.write(data)

    def get_bytes(self, remote_path: str) -> bytes:
        with self._sftp.file(remote_path, "rb") as fp:
            return fp.read()
```

---

## `lambdas/list_tests_s3/app.py`

```python
import json
from lambdas.common import s3io
from lambdas.common.env import FILEFLOW_CONFIG_BUCKET
from lambdas.common.logging import jlog

def handler(event, _):
    tests = []
    for key in s3io.read_config_objects(prefix="config/flows/"):
        cfg = s3io.read_json(FILEFLOW_CONFIG_BUCKET, key)
        if cfg.get("enabled", True):
            tests.append(cfg)
    jlog("info", "Loaded tests from S3", count=len(tests))
    return {"tests": tests}
```

## `lambdas/gen_testdata/app.py`

```python
import os, uuid, binascii
from datetime import datetime, timezone
from lambdas.common.logging import jlog
from lambdas.common.hashing import sha256_bytes

def handler(event, _):
    td = event["testdata"]
    flow_id = event["flow_id"]
    size = int(td.get("size_bytes", 4096))
    pattern = td.get("pattern", "random")
    fname_prefix = td.get("filename_prefix", "diag")
    run_id = f"{flow_id}-{uuid.uuid4()}"
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    fname = f"{fname_prefix}_{ts}_{run_id}.dat"

    data = os.urandom(size) if pattern == "random" else (b"x" * size)
    sha = sha256_bytes(data)
    manifest = {
        "flow_id": flow_id, "test_run_id": run_id, "generated_at": ts,
        "size": size, "sha256": sha, "schema_ver": 1
    }
    jlog("info", "Generated test data", file=fname, bytes=size)
    # pass data around hex-encoded to keep ASL payload friendly
    return {**event, "file": {"name": fname, "bytes": size, "sha256": sha, "content_hex": data.hex()}, "manifest": manifest}
```

## `lambdas/seed_source/app.py`

```python
import binascii, json
from lambdas.common.logging import jlog
from lambdas.common import s3io, secrets
from lambdas.common.sftp_client import SFTPClientWrapper

def _seed_s3(src, f, manifest):
    key = f'{src.get("prefix","")}{f["name"]}'
    data = binascii.unhexlify(f["content_hex"])
    s3io.put_bytes(src["bucket"], key, data, tagging="synthetic=true")
    s3io.put_bytes(src["bucket"], key + ".sha256", (f["sha256"]+"\n").encode())
    s3io.put_bytes(src["bucket"], key + ".manifest.json", json.dumps(manifest).encode())
    return key

def _seed_sftp(src, f, manifest):
    sec = secrets.get_secret_json(src["secret_arn"])
    data = binascii.unhexlify(f["content_hex"])
    remote = f'{src["dir"].rstrip("/")}/{f["name"]}'
    with SFTPClientWrapper(src["host"], src.get("port",22), src["username"], sec["privateKey"]) as c:
        c.put_bytes(remote, data)
        c.put_bytes(remote + ".sha256", (f["sha256"]+"\n").encode())
        c.put_bytes(remote + ".manifest.json", json.dumps(manifest).encode())
    return remote

def handler(event, _):
    src = event["source"]; f = event["file"]; man = event["manifest"]
    if src["type"] == "S3":
        seeded_key = _seed_s3(src, f, man)
        jlog("info", "Seeded S3", key=seeded_key)
        return {**event, "seeded_key": seeded_key}
    elif src["type"] == "SFTP":
        path = _seed_sftp(src, f, man)
        jlog("info", "Seeded SFTP", path=path)
        return {**event, "seeded_path": path}
    else:
        raise ValueError("Unknown source type")
```

## `lambdas/invoke_transfer/app.py`

```python
import json, time, boto3
from lambdas.common.logging import jlog
lam = boto3.client("lambda")

def handler(event, _):
    tr = event["transfer"]
    lam.invoke(
        FunctionName=tr["lambda_arn"],
        InvocationType="Event",
        Payload=json.dumps(tr.get("payload", {})).encode()
    )
    t = int(time.time())
    jlog("info", "Invoked transfer lambda", when=t)
    return {**event, "invoked_at": t}
```

## `lambdas/poll_target/app.py`

```python
import time, json, binascii, boto3
from lambdas.common.logging import jlog
from lambdas.common import s3io, secrets
from lambdas.common.sftp_client import SFTPClientWrapper

s3 = boto3.client("s3")

def _get_s3_bytes(tgt, fname):
    key = f'{tgt.get("prefix","")}{fname}'
    try:
        return s3io.get_bytes(tgt["bucket"], key)
    except s3.exceptions.NoSuchKey:
        return None
    except Exception:
        # if 404 presents differently
        return None

def _get_sftp_bytes(tgt, fname):
    sec = secrets.get_secret_json(tgt["secret_arn"])
    path = f'{tgt["dir"].rstrip("/")}/{fname}'
    try:
        with SFTPClientWrapper(tgt["host"], tgt.get("port",22), tgt["username"], sec["privateKey"]) as c:
            return c.get_bytes(path)
    except Exception:
        return None

def handler(event, _):
    tgt = event["target"]; f = event["file"]; v = event["validation"]
    deadline = int(event["invoked_at"]) + int(v.get("expect_within_seconds", 300))
    data = None

    while time.time() < deadline:
        if tgt["type"] == "S3":
            data = _get_s3_bytes(tgt, f["name"])
        else:
            data = _get_sftp_bytes(tgt, f["name"])

        if data is not None:
            jlog("info", "Target arrived", bytes=len(data))
            return {**event, "arrived": True, "target_data_hex": data.hex()}
        time.sleep(5)

    jlog("error", "Timeout polling target")
    return {**event, "arrived": False}
```

## `lambdas/validate/app.py`

```python
import binascii, boto3
from lambdas.common.hashing import sha256_bytes
from lambdas.common.env import NAMESPACE
from lambdas.common.logging import jlog
cw = boto3.client("cloudwatch")

def _put_success_metric(flow_id: str, ok: bool):
    cw.put_metric_data(
        Namespace=NAMESPACE,
        MetricData=[{"MetricName":"RunSuccess","Value":1.0 if ok else 0.0,"Unit":"Count",
                     "Dimensions":[{"Name":"FlowId","Value":flow_id}]}]
    )

def handler(event, _):
    ok, reason = False, None
    if not event.get("arrived"):
        reason = "Timeout waiting for target"
    else:
        target = binascii.unhexlify(event["target_data_hex"])
        exp_sha = event["manifest"]["sha256"]
        got_sha = sha256_bytes(target)
        if got_sha != exp_sha:
            reason = f"Checksum mismatch {got_sha} != {exp_sha}"
        elif len(target) != event["file"]["bytes"]:
            reason = "Size mismatch"
        else:
            ok = True

    _put_success_metric(event["flow_id"], ok)
    if ok: jlog("info", "Validation OK")
    else:  jlog("error", "Validation failed", reason=reason)

    return {**event, "ok": ok, "reason": reason}
```

## `lambdas/record_results/app.py`

```python
from datetime import datetime, timezone
from lambdas.common import s3io
from lambdas.common.env import FILEFLOW_CONFIG_BUCKET
from lambdas.common.logging import jlog

def handler(event, _):
    dt = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    flow = event["flow_id"]; run_id = event.get("manifest", {}).get("test_run_id","no-runid")
    key = f"results/dt={dt}/flow_id={flow}/run_id={run_id}/run.json"
    s3io.write_json(FILEFLOW_CONFIG_BUCKET, key, event)
    jlog("info", "Recorded results", key=key, ok=event.get("ok"))
    return event
```

## `lambdas/cleanup/app.py`

```python
from lambdas.common.logging import jlog

def handler(event, _):
    # No-op cleanup by default; keep artifacts for audit. Toggle via config if needed.
    jlog("info", "Cleanup complete (noop)")
    return event
```

---

## Step Functions — `stepfunctions/daily_fileflow_tests.asl.json`

```json
{
  "Comment": "Daily File Flow Tests",
  "StartAt": "ListEnabledTests",
  "States": {
    "ListEnabledTests": {
      "Type": "Task",
      "Resource": "${ListTestsS3Arn}",
      "ResultPath": "$",
      "Next": "MapTests"
    },
    "MapTests": {
      "Type": "Map",
      "ItemsPath": "$.tests",
      "MaxConcurrency": 4,
      "Iterator": {
        "StartAt": "GenTestData",
        "States": {
          "GenTestData": { "Type": "Task", "Resource": "${GenTestdataArn}", "Next": "SeedSource" },
          "SeedSource":  { "Type": "Task", "Resource": "${SeedSourceArn}",   "Next": "InvokeTransfer" },
          "InvokeTransfer": { "Type": "Task", "Resource": "${InvokeTransferArn}", "Next": "PollTarget" },
          "PollTarget":  { "Type": "Task", "Resource": "${PollTargetArn}",   "Next": "Validate" },
          "Validate":    { "Type": "Task", "Resource": "${ValidateArn}",     "Next": "RecordResults" },
          "RecordResults": { "Type": "Task", "Resource": "${RecordResultsArn}", "Next": "Cleanup" },
          "Cleanup":     { "Type": "Task", "Resource": "${CleanupArn}", "End": true }
        }
      },
      "End": true
    }
  }
}
```

---

# Tests

> Uses `pytest`, `moto` (S3), and lightweight monkeypatch stubs for Secrets Manager, SFTP, and Lambda invocation.

## `requirements.txt`

```
boto3==1.34.144
botocore==1.34.144
paramiko==3.4.0
pytest==8.3.2
moto[s3]==5.0.11
```

## `tests/conftest.py`

```python
import os, json, types, boto3, pytest
from moto import mock_aws

@pytest.fixture(autouse=True)
def env_setup(monkeypatch):
    monkeypatch.setenv("FILEFLOW_CONFIG_BUCKET", "fileflow-tests")
    monkeypatch.setenv("METRIC_NAMESPACE", "FileFlowTests")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    yield

@pytest.fixture
def aws_env():
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-west-2")
        s3.create_bucket(Bucket="fileflow-tests")
        yield s3

@pytest.fixture
def put_flow_config(aws_env):
    def _put(cfg: dict, name="acme.json"):
        body = json.dumps(cfg).encode()
        aws_env.put_object(Bucket="fileflow-tests", Key=f"config/flows/{name}", Body=body)
    return _put

# --- Stubs/monkeypatch helpers ---

class SecretStub:
    def __init__(self, mp):
        self._vals = {}
        def _client(name):
            if name == "secretsmanager":
                c = types.SimpleNamespace()
                c.get_secret_value = lambda SecretId: {"SecretString": json.dumps(self._vals[SecretId])}
                return c
            return boto3.client(name, region_name="us-west-2")
        mp.setenv("AWS_DEFAULT_REGION", "us-west-2")
        self.client_factory = _client

    def set(self, arn, dct):
        self._vals[arn] = dct

@pytest.fixture
def secrets_stub(monkeypatch):
    stub = SecretStub(monkeypatch)
    monkeypatch.setattr("boto3.client", stub.client_factory)
    return stub

class SFTPStub:
    def __init__(self):
        self.storage = {}
    def put_bytes(self, path, data):
        self.storage[path] = data
    def get_bytes(self, path):
        if path not in self.storage:
            raise FileNotFoundError(path)
        return self.storage[path]

@pytest.fixture
def sftp_patch(monkeypatch):
    stub = SFTPStub()
    class WrapperMock:
        def __init__(self, *a, **k): pass
        def __enter__(self): return stub
        def __exit__(self, *a): return False
    monkeypatch.setattr("lambdas.common.sftp_client.SFTPClientWrapper", WrapperMock)
    return stub
```

## `tests/test_list_tests_s3.py`

```python
from lambdas.list_tests_s3.app import handler

def test_list(aws_env, put_flow_config):
    put_flow_config({"flow_id":"one","enabled":True})
    put_flow_config({"flow_id":"two","enabled":False}, name="two.json")
    out = handler({}, None)
    ids = {t["flow_id"] for t in out["tests"]}
    assert ids == {"one"}
```

## `tests/test_gen_testdata.py`

```python
from lambdas.gen_testdata.app import handler

def test_gen():
    event = {"flow_id":"acme","testdata":{"size_bytes":1024,"pattern":"fixed","filename_prefix":"t"}}
    out = handler(event, None)
    assert out["file"]["bytes"] == 1024
    assert out["manifest"]["sha256"] == out["file"]["sha256"]
```

## `tests/test_seed_source_s3.py`

```python
import boto3, json, binascii
from lambdas.seed_source.app import handler

def test_seed_s3(aws_env):
    event = {
        "flow_id":"f",
        "file":{"name":"x.dat","bytes":4,"sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","content_hex":""},
        "manifest":{"sha256":"e3b0...855"},
        "source":{"type":"S3","bucket":"fileflow-tests","prefix":"seed/"},
    }
    out = handler(event, None)
    assert out["seeded_key"] == "seed/x.dat"
```

## `tests/test_seed_source_sftp.py`

```python
from lambdas.seed_source.app import handler

def test_seed_sftp(aws_env, sftp_patch, secrets_stub):
    secrets_stub.set("arn:s:sec", {"privateKey":"-----BEGIN RSA PRIVATE KEY-----\nMIIBOgIBAAJBAL8...\n-----END RSA PRIVATE KEY-----"})
    event = {
        "flow_id":"f",
        "file":{"name":"y.dat","bytes":3,"sha256":"abc","content_hex":"010203"},
        "manifest":{"sha256":"abc"},
        "source":{"type":"SFTP","host":"h","port":22,"username":"u","dir":"/in","secret_arn":"arn:s:sec"},
    }
    out = handler(event, None)
    assert out["seeded_path"] == "/in/y.dat"
    # 3 files written (data, .sha256, .manifest.json)
    assert len(sftp_patch.storage) == 3
```

## `tests/test_poll_target_s3_success.py`

```python
from lambdas.poll_target.app import handler
import time

def test_poll_s3_success(aws_env):
    # seed target late (simulate arrival)
    event = {
        "invoked_at": int(time.time()),
        "validation": {"expect_within_seconds": 3},
        "target":{"type":"S3","bucket":"fileflow-tests","prefix":"t/"},
        "file":{"name":"ok.dat"},
    }
    # arrange arrival
    def later():
        aws_env.put_object(Bucket="fileflow-tests", Key="t/ok.dat", Body=b"hi")
    later()
    out = handler(event, None)
    assert out["arrived"] is True
```

## `tests/test_poll_target_timeout.py`

```python
from lambdas.poll_target.app import handler
import time

def test_poll_timeout(aws_env):
    event = {
        "invoked_at": int(time.time()),
        "validation": {"expect_within_seconds": 1},
        "target":{"type":"S3","bucket":"fileflow-tests","prefix":"none/"},
        "file":{"name":"missing.dat"},
    }
    out = handler(event, None)
    assert out["arrived"] is False
```

## `tests/test_validate_ok.py`

```python
import binascii
from lambdas.validate.app import handler

def test_validate_ok(monkeypatch):
    data = b"abc"
    event = {
        "flow_id":"f",
        "arrived": True,
        "file": {"bytes":3},
        "manifest": {"sha256":"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"},
        "target_data_hex": data.hex()
    }
    # mute CW
    import boto3
    cw = boto3.client("cloudwatch", region_name="us-west-2")
    def fake_put_metric_data(**kw): return None
    monkeypatch.setattr(cw, "put_metric_data", fake_put_metric_data, raising=False)
    out = handler(event, None)
    assert out["ok"] is True
```

## `tests/test_validate_checksum_mismatch.py`

```python
from lambdas.validate.app import handler

def test_mismatch(monkeypatch):
    event = {
        "flow_id":"f",
        "arrived": True,
        "file": {"bytes":3},
        "manifest": {"sha256":"deadbeef"},
        "target_data_hex":"00ff00"
    }
    import boto3
    cw = boto3.client("cloudwatch", region_name="us-west-2")
    monkeypatch.setattr(cw, "put_metric_data", lambda **k: None, raising=False)
    out = handler(event, None)
    assert out["ok"] is False
    assert "Checksum mismatch" in out["reason"]
```

## `tests/test_validate_size_mismatch.py`

```python
from lambdas.validate.app import handler

def test_size(monkeypatch):
    event = {
        "flow_id":"f",
        "arrived": True,
        "file": {"bytes":10},
        "manifest": {"sha256":"9f64a747e1b97f131fabb6b447296c9b6f0201e79fb3c5356e6c77e89b6a806a"}, # sha256("hello")
        "target_data_hex":"68656c6c6f" # "hello"
    }
    import boto3
    cw = boto3.client("cloudwatch", region_name="us-west-2")
    monkeypatch.setattr(cw, "put_metric_data", lambda **k: None, raising=False)
    out = handler(event, None)
    assert out["ok"] is False
    assert out["reason"] == "Size mismatch"
```

## `tests/test_record_results.py`

```python
import json
from lambdas.record_results.app import handler
from lambdas.common.env import FILEFLOW_CONFIG_BUCKET
import boto3
from datetime import datetime

def test_record(aws_env, monkeypatch):
    e = {"flow_id":"f","ok":True,"manifest":{"test_run_id":"r"}}
    out = handler(e, None)
    # Verify object exists
    resp = aws_env.list_objects_v2(Bucket="fileflow-tests", Prefix="results/")
    assert resp["KeyCount"] == 1
```

## `tests/test_end_to_end_s3_to_s3.py`  *(Smoke E2E in-process)*

```python
import json, time, binascii
from lambdas.list_tests_s3.app import handler as list_h
from lambdas.gen_testdata.app import handler as gen_h
from lambdas.seed_source.app import handler as seed_h
from lambdas.invoke_transfer.app import handler as inv_h
from lambdas.poll_target.app import handler as poll_h
from lambdas.validate.app import handler as val_h
from lambdas.record_results.app import handler as rec_h

def test_e2e_s3_to_s3(aws_env, put_flow_config, monkeypatch):
    # Fake the "transfer lambda" by copying object from src->tgt
    def fake_invoke(**kw): return {}
    import boto3
    lam = boto3.client("lambda", region_name="us-west-2")
    monkeypatch.setattr(lam, "invoke", lambda **k: None, raising=False)

    put_flow_config({
        "flow_id":"e2e",
        "enabled": True,
        "source": {"type":"S3","bucket":"fileflow-tests","prefix":"src/"},
        "target": {"type":"S3","bucket":"fileflow-tests","prefix":"tgt/"},
        "transfer": {"lambda_arn":"arn:aws:lambda:us-west-2:123:function:file-transfer","payload":{},"timeout_seconds":30},
        "validation": {"expect_within_seconds":2,"checksum":"SHA256","size_tolerance_bytes":0},
        "testdata": {"size_bytes":5,"pattern":"fixed","filename_prefix":"diag"}
    }, name="e2e.json")

    # list
    tests = list_h({}, None)["tests"]
    ev = tests[0]
    # gen
    ev = gen_h(ev, None)
    # seed
    ev = seed_h(ev, None)

    # emulate transfer arrival: copy object in S3 (src -> tgt)
    src_key = ev["source"]["prefix"] + ev["file"]["name"]
    tgt_key = ev["target"]["prefix"] + ev["file"]["name"]
    s3 = aws_env
    body = s3.get_object(Bucket="fileflow-tests", Key=src_key)["Body"].read()
    s3.put_object(Bucket="fileflow-tests", Key=tgt_key, Body=body)

    # invoke (noop but keeps timestamp)
    ev = inv_h(ev, None)
    # poll
    ev = poll_h(ev, None)
    assert ev["arrived"]
    # validate
    ev = val_h(ev, None)
    assert ev["ok"]
    # record
    ev = rec_h(ev, None)
```

---

# Example flow config (S3 object)

Put this file in `s3://fileflow-tests/config/flows/acme_sftp_to_s3_prod.json`:

```json
{
  "flow_id": "acme_sftp_to_s3_prod",
  "enabled": true,
  "source": {
    "type": "SFTP",
    "host": "s-xxxx.server.transfer.us-west-2.amazonaws.com",
    "port": 22,
    "username": "acme",
    "dir": "/inbox",
    "secret_arn": "arn:aws:secretsmanager:us-west-2:1111:secret:sftp/acme"
  },
  "target": { "type": "S3", "bucket": "target-bucket-prod", "prefix": "partners/acme/inbox/" },
  "transfer": {
    "lambda_arn": "arn:aws:lambda:us-west-2:1111:function:file-transfer",
    "payload": { "flowConfigId": "acme-prod" },
    "timeout_seconds": 900
  },
  "validation": {
    "expect_within_seconds": 420,
    "checksum": "SHA256",
    "size_tolerance_bytes": 0
  },
  "testdata": {
    "size_bytes": 5242880,
    "pattern": "random",
    "filename_prefix": "diag",
    "delete_after": true
  },
  "alerts": {
    "sns_topic_arn": "arn:aws:sns:us-west-2:1111:fileflow-test-alerts"
  }
}
```

---

# README.md (ops quick start)

**Deploy (SAM example)**

* Package each Lambda from its folder (one `app.py` each).
* Provide env vars on each function:

  * `FILEFLOW_CONFIG_BUCKET = fileflow-tests`
  * `METRIC_NAMESPACE = FileFlowTests`
* Give IAM:

  * `s3:GetObject` on `config/*`, `s3:PutObject` on `results/*`
  * If sources/targets include S3: grant scoped `GetObject/PutObject` to those prefixes.
  * `secretsmanager:GetSecretValue` for required secret ARNs.
  * `cloudwatch:PutMetricData` to namespace.
* Create Step Functions from `stepfunctions/daily_fileflow_tests.asl.json` with the Lambda ARNs substituted.

**Run tests locally**

```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

**Daily schedule**

* EventBridge rule → StartExecution on state machine at your chosen cron.

**Observability**

* CloudWatch metric: `FileFlowTests/RunSuccess` (dim: `FlowId`)
* S3 results: `results/dt=YYYY-MM-DD/flow_id=.../run_id=.../run.json`
* Add alarms: `Average < 1` for 1 evaluation period → SNS/Slack.

**Security**

* Keep test prefixes segregated (`/test/`), tag synthetic objects.
* Use VPC endpoints for S3/Secrets if Lambdas run in VPC.
* Rotate SFTP keys in Secrets Manager; restrict IAM to exact ARNs.

---

## What’s covered by tests

* Load enabled flows from S3 config.
* Generate deterministic test data and manifest.
* Seed to **S3** and **SFTP** sources (SFTP via stub/mocks).
* Poll **S3** until object arrival & timeout path.
* Validate success; detect **checksum mismatch** & **size mismatch**.
* Record results to S3.
* **Smoke E2E** (S3→S3) simulating the transfer copy.

---

If you want this as a **Terraform module** instead of SAM, I can inline the module (bucket, IAM roles/policies, Lambda + SFN wiring) next.


Awesome—here’s your **end-to-end, step-by-step guide** to stand up and operate the S3-backed daily testing framework for your Lambda file-transfer flows (SFTP ⇄ S3). This matches the downloadable Terraform project I gave you.

---

# 0) What you’ll have at the end

* A versioned **S3 bucket** that stores your **flow configs** and **test results**
* **8 Lambda functions** (list → gen → seed → invoke → poll → validate → record → cleanup)
* A **Step Functions** state machine that runs tests for every enabled flow
* An **EventBridge** **daily schedule** (default 06:00 PT) to run your smoke tests
* **CloudWatch metrics & alarms** so failures ping you immediately
* Optional **Paramiko Lambda Layer** auto-built (for SFTP)

---

# 1) Prereqs

* AWS CLI configured (account + region) and Terraform ≥ 1.6
* Docker (only needed the first time if you auto-build the Paramiko layer)
* IAM user/role with rights to create Lambda, Step Functions, EventBridge, CloudWatch, S3, Secrets Manager

---

# 2) Get the code & set variables

1. Download and unzip the project:

   * `fileflow-tests-terraform.zip` (the one I provided)
2. Go to Terraform folder:

   ```bash
   cd fileflow-tests-terraform/terraform
   cp terraform.tfvars.example terraform.tfvars
   ```
3. Open `terraform.tfvars` and set:

   ```hcl
   aws_region         = "us-west-2"   # or your region
   config_bucket_name = "fileflow-tests-prod-<your-unique-suffix>"
   # Leave paramiko_layer_arn empty to auto-build; or paste your pre-existing layer ARN
   allowed_s3_arns = [
     # Add exact ARNs your tests will touch:
     # "arn:aws:s3:::source-bucket",
     # "arn:aws:s3:::source-bucket/prefix/*",
     # "arn:aws:s3:::target-bucket",
     # "arn:aws:s3:::target-bucket/prefix/*",
   ]
   alarm_email = "alerts@yourcompany.com" # optional; SNS email subscription
   ```

> **Why `allowed_s3_arns`?**
> Your test Lambdas must read/write the same S3 prefixes your *real* flows use. Listing those ARNs here keeps IAM least-privileged.

---

# 3) (Optional) Paramiko layer options (for SFTP support)

You have two options:

**A. Auto-build & publish (default)**
Leave `paramiko_layer_arn=""`. On `terraform apply`, Terraform will:

* run `scripts/build_paramiko_layer.sh` in Docker,
* create `layers/paramiko-python3.12.zip`,
* publish `aws_lambda_layer_version.paramiko`,
* wire the layer into the **seed_source** and **poll_target** Lambdas.

**B. Use an existing layer**
Set `paramiko_layer_arn="arn:aws:lambda:...:layer:paramiko-python312:1"` in `terraform.tfvars`. Terraform will skip the local build.

---

# 4) Deploy the framework

```bash
terraform init
terraform apply
```

* Confirm the plan.
* On success, note the outputs:

  * `state_machine_arn`
  * `config_bucket_name` (this is where configs/results live)

---

# 5) Create Secrets for SFTP endpoints

For each SFTP endpoint (source or target) create a Secrets Manager secret with this **JSON** shape:

```json
{
  "privateKey": "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
}
```

Save the **Secret ARN**; you’ll reference it inside each flow config file.

---

# 6) Add your first flow config(s)

Configs live in the bucket under `config/flows/*.json`.
Four examples below—tweak to match your endpoints/buckets. Upload with AWS CLI or console.

**A) S3 → S3**

```json
{
  "flow_id": "sample_s3_to_s3",
  "enabled": true,
  "source": { "type":"S3", "bucket":"your-source-bucket", "prefix":"incoming/test/" },
  "target": { "type":"S3", "bucket":"your-target-bucket", "prefix":"partners/acme/inbox/" },
  "transfer": {
    "lambda_arn": "arn:aws:lambda:us-west-2:123:function:file-transfer",
    "payload": { "flowConfigId": "acme-prod" },
    "timeout_seconds": 900
  },
  "validation": { "expect_within_seconds": 420, "checksum": "SHA256", "size_tolerance_bytes": 0 },
  "testdata": { "size_bytes": 5242880, "pattern":"random", "filename_prefix":"diag", "delete_after": true }
}
```

**B) S3 → SFTP**

```json
{
  "flow_id": "sample_s3_to_sftp",
  "enabled": true,
  "source": { "type":"S3", "bucket":"your-source-bucket", "prefix":"incoming/test/" },
  "target": {
    "type":"SFTP",
    "host":"s-xxxx.server.transfer.us-west-2.amazonaws.com",
    "port":22,
    "username":"acme",
    "dir":"/inbox",
    "secret_arn":"arn:aws:secretsmanager:us-west-2:111111111111:secret:sftp/acme"
  },
  "transfer": { "lambda_arn": "arn:aws:lambda:...:function:file-transfer", "payload": {}, "timeout_seconds": 900 },
  "validation": { "expect_within_seconds": 420, "checksum":"SHA256", "size_tolerance_bytes": 0 },
  "testdata": { "size_bytes": 1048576, "pattern":"fixed", "filename_prefix":"diag" }
}
```

**C) SFTP → S3**

```json
{
  "flow_id": "sample_sftp_to_s3",
  "enabled": true,
  "source": {
    "type":"SFTP",
    "host":"s-yyyy.server.transfer.us-west-2.amazonaws.com",
    "port":22,
    "username":"globex",
    "dir":"/outbox",
    "secret_arn":"arn:aws:secretsmanager:us-west-2:111111111111:secret:sftp/globex"
  },
  "target": { "type":"S3", "bucket":"your-target-bucket", "prefix":"partners/globex/inbox/" },
  "transfer": { "lambda_arn": "arn:aws:lambda:...:function:file-transfer", "payload": {}, "timeout_seconds": 900 },
  "validation": { "expect_within_seconds": 600, "checksum":"SHA256", "size_tolerance_bytes": 0 },
  "testdata": { "size_bytes": 5242880, "pattern":"random", "filename_prefix":"diag" }
}
```

**D) SFTP → SFTP**

```json
{
  "flow_id": "sample_sftp_to_sftp",
  "enabled": true,
  "source": {
    "type":"SFTP", "host":"s-a.server.transfer.us-west-2.amazonaws.com", "port":22,
    "username":"srcuser", "dir":"/out", "secret_arn":"arn:aws:secretsmanager:...:secret:sftp/src"
  },
  "target": {
    "type":"SFTP", "host":"s-b.server.transfer.us-west-2.amazonaws.com", "port":22,
    "username":"tgtuser", "dir":"/in", "secret_arn":"arn:aws:secretsmanager:...:secret:sftp/tgt"
  },
  "transfer": { "lambda_arn": "arn:aws:lambda:...:function:file-transfer", "payload": {}, "timeout_seconds": 900 },
  "validation": { "expect_within_seconds": 900, "checksum":"SHA256", "size_tolerance_bytes": 0 },
  "testdata": { "size_bytes": 1048576, "pattern":"fixed", "filename_prefix":"diag" }
}
```

**Upload the files** (replace bucket name):

```bash
aws s3 cp ../bootstrap/config/flows/acme_sftp_to_s3_prod.json s3://<config_bucket>/config/flows/
# or your custom JSONs
```

> Tip: You can **enable/disable** a flow by toggling `"enabled": true|false` inside the JSON.

---

# 7) Run tests on demand

Open Step Functions → your state machine → **Start execution** → no input required.
It will:

1. Read all `config/flows/*.json` with `enabled=true`
2. For each:

   * Generate a synthetic file + manifest
   * Seed it into the **source**
   * Invoke your **transfer Lambda** (async)
   * **Poll** the target until the file arrives or timeout
   * **Validate** checksum & size
   * **Record results** into the config bucket

---

# 8) Let it run daily (default 06:00 PT)

An EventBridge rule is already created with:

```
cron(0 13 * * ? *)  # 13:00 UTC = 06:00 PT
```

To change time, update `daily_cron_expression` in `terraform.tfvars` and `terraform apply`.

---

# 9) See results & metrics

**S3 results (by date & flow):**

```
s3://<config_bucket>/results/dt=YYYY-MM-DD/flow_id=<flow_id>/run_id=<uuid>/run.json
```

This JSON carries the full story (file name, sizes, sha, arrived?, ok?, reason).

**Metrics & alarms:**

* Metric: `FileFlowTests / RunSuccess` (Dimension: `FlowId`)
* Default alarm: **ExecutionsFailed** > 0 for the state machine (SNS email if you set `alarm_email`)
* (Optional) Add another alarm for `RunSuccess < 1` if you want per-flow failure alerts

---

# 10) Smoke & stress testing tips

* Add **three sizes** per flow for better coverage (create 3 JSON configs per flow or extend one to loop sizes in your transfer Lambda payload):

  * 4 KB (quick smoke)
  * 5 MB (typical)
  * 100 MB (stress / multipart paths)
* Set `validation.expect_within_seconds` based on real SLAs. E.g., 420s for SFTP hops, 120s for S3→S3 within region.

---

# 11) Least-privilege IAM (critical)

Make sure `allowed_s3_arns` includes the **exact** buckets/prefixes your tests will touch (both source & target). Examples:

```hcl
allowed_s3_arns = [
  "arn:aws:s3:::your-source-bucket",
  "arn:aws:s3:::your-source-bucket/incoming/test/*",
  "arn:aws:s3:::your-target-bucket",
  "arn:aws:s3:::your-target-bucket/partners/acme/inbox/*",
]
```

For SFTP, the Lambdas read only Secrets you reference in configs. If you want to pin Secrets to specific ARNs, tighten the IAM policy in `modules/iam/main.tf` by replacing `"*"` with a list.

---

# 12) Troubleshooting playbook

* **No tests run**: Check the config bucket has JSON files under `config/flows/` and `enabled=true`.
* **Timeout waiting for target**:

  * Confirm your production transfer Lambda received the event (CloudWatch logs).
  * Verify target path is correct (`prefix`, SFTP `dir`) and credentials/keys are valid.
* **Checksum mismatch**:

  * Some flows transform files—if expected, disable checksum or adjust to validate a post-transform format (CSV row count, JSONL line count, etc.). Otherwise, likely a truncation/encoding issue in the transfer code.
* **Access denied**:

  * Add needed ARNs to `allowed_s3_arns` and re-`terraform apply`.
* **SFTP errors**:

  * Ensure the Secrets Manager JSON is exactly `{"privateKey": "...PEM..."}` and that the key matches the SFTP user.
  * Confirm security groups/ingress to the SFTP server from Lambda’s networking (if your Lambdas run in a VPC, add a NAT or interface endpoints as needed).

---

# 13) Optional: Ad-hoc validation right after a new flow goes live

When you add a new flow or change code, start the state machine **manually** to catch regressions immediately instead of waiting for the daily run.

---

# 14) CI/CD (recommended)

* Commit this repo to your Git host.
* Add a pipeline that runs:

  * `terraform fmt -check && terraform validate`
  * `terraform plan` on PRs
  * `terraform apply -auto-approve` on main (or via manual approval)
* Protect the config bucket via **S3 bucket policies** and enable **Object Lock** (optional) to keep test results tamper-evident.

---

# 15) Cost guardrails

* Lambdas are short-lived; State Machine runs once/day—very low cost.
* S3 lifecycle auto-expires results after 30 days (adjust in `modules/s3/main.tf`).
* If you add 100MB tests, keep them to nightly, not hourly.

---

# 16) Extend the framework (when ready)

* **Groups/subsets**: Add a simple “group” list (e.g., `config/groups/nightly.json`) and modify `list_tests_s3` Lambda to filter by event input (easy change).
* **More validators**: schema checks (CSV header), row counts, GZIP integrity, PGP signature verify.
* **Per-flow SLOs**: set different `expect_within_seconds` by flow, tag p95 latency as a metric.

---

## Quick command recap

```bash
# Deploy
cd fileflow-tests-terraform/terraform
terraform init && terraform apply

# Upload a config
aws s3 cp ../bootstrap/config/flows/acme_sftp_to_s3_prod.json s3://<config_bucket>/config/flows/

# Manual run (from console) or via AWS CLI:
aws stepfunctions start-execution --state-machine-arn <STATE_MACHINE_ARN>

# View results
aws s3 ls s3://<config_bucket>/results/ --recursive
```

If you want, I can tailor a **ready-to-paste set** of flow configs from your current production endpoints (SFTP hostnames, S3 prefixes, and your transfer Lambda payload format) so you can drop them in and run today.


Great—here are **ready-to-use flow configs** tailored to your BayAreaLa8s file-transfer setup (partners **acme** and **globex**, buckets `ba8s-file-poc-landing` and `ba8s-file-poc-target`, AWS Transfer Family in **us-west-2**). They cover the full matrix (S3→S3, S3→SFTP, SFTP→S3, SFTP→SFTP) with sensible defaults for smoke (1 MB) and typical (5 MB) tests.

Replace the three ALL-CAPS placeholders before uploading:

* **`<ACCOUNT_ID>`**: your AWS account ID
* **`<ACME_SECRET_ARN>`**: Secrets Manager ARN holding ACME’s SFTP private key (`{"privateKey":"-----BEGIN..."}`)
* **`<GLOBEX_SECRET_ARN>`**: Secrets Manager ARN holding Globex’s SFTP private key

Your **transfer Lambda ARN** is referenced once; adjust the `payload` as your function expects.

---

# 1) S3 → S3 (landing → target)

**`acme_s3_to_s3.json`**

```json
{
  "flow_id": "acme_s3_to_s3",
  "enabled": true,
  "source": {
    "type": "S3",
    "bucket": "ba8s-file-poc-landing",
    "prefix": "partners/acme/inbox/test/"
  },
  "target": {
    "type": "S3",
    "bucket": "ba8s-file-poc-target",
    "prefix": "partners/acme/inbox/"
  },
  "transfer": {
    "lambda_arn": "arn:aws:lambda:us-west-2:<ACCOUNT_ID>:function:file-transfer",
    "payload": { "flowConfigId": "partners/acme/inbox" },
    "timeout_seconds": 600
  },
  "validation": {
    "expect_within_seconds": 180,
    "checksum": "SHA256",
    "size_tolerance_bytes": 0
  },
  "testdata": {
    "size_bytes": 1048576,
    "pattern": "fixed",
    "filename_prefix": "diag",
    "delete_after": true
  }
}
```

---

# 2) S3 → SFTP (landing → ACME SFTP)

**`acme_s3_to_sftp.json`**

```json
{
  "flow_id": "acme_s3_to_sftp",
  "enabled": true,
  "source": {
    "type": "S3",
    "bucket": "ba8s-file-poc-landing",
    "prefix": "partners/acme/inbox/test/"
  },
  "target": {
    "type": "SFTP",
    "host": "s-a6a61c09e49b42d29.server.transfer.us-west-2.amazonaws.com",
    "port": 22,
    "username": "acme",
    "dir": "/ba8s-file-poc-landing/partners/acme/inbox",
    "secret_arn": "<ACME_SECRET_ARN>"
  },
  "transfer": {
    "lambda_arn": "arn:aws:lambda:us-west-2:<ACCOUNT_ID>:function:file-transfer",
    "payload": { "flowConfigId": "partners/acme/inbox-s3-to-sftp" },
    "timeout_seconds": 900
  },
  "validation": {
    "expect_within_seconds": 420,
    "checksum": "SHA256",
    "size_tolerance_bytes": 0
  },
  "testdata": {
    "size_bytes": 5242880,
    "pattern": "random",
    "filename_prefix": "diag",
    "delete_after": true
  }
}
```

---

# 3) SFTP → S3 (ACME SFTP → target)

**`acme_sftp_to_s3.json`**

```json
{
  "flow_id": "acme_sftp_to_s3",
  "enabled": true,
  "source": {
    "type": "SFTP",
    "host": "s-a6a61c09e49b42d29.server.transfer.us-west-2.amazonaws.com",
    "port": 22,
    "username": "acme",
    "dir": "/ba8s-file-poc-landing/partners/acme/outbox",
    "secret_arn": "<ACME_SECRET_ARN>"
  },
  "target": {
    "type": "S3",
    "bucket": "ba8s-file-poc-target",
    "prefix": "partners/acme/inbox/"
  },
  "transfer": {
    "lambda_arn": "arn:aws:lambda:us-west-2:<ACCOUNT_ID>:function:file-transfer",
    "payload": { "flowConfigId": "partners/acme/sftp-to-s3" },
    "timeout_seconds": 900
  },
  "validation": {
    "expect_within_seconds": 600,
    "checksum": "SHA256",
    "size_tolerance_bytes": 0
  },
  "testdata": {
    "size_bytes": 5242880,
    "pattern": "random",
    "filename_prefix": "diag",
    "delete_after": true
  }
}
```

---

# 4) SFTP → SFTP (ACME → GLOBEX; cross-partner hop)

**`acme_sftp_to_globex_sftp.json`**

```json
{
  "flow_id": "acme_sftp_to_globex_sftp",
  "enabled": true,
  "source": {
    "type": "SFTP",
    "host": "s-a6a61c09e49b42d29.server.transfer.us-west-2.amazonaws.com",
    "port": 22,
    "username": "acme",
    "dir": "/ba8s-file-poc-landing/partners/acme/outbox",
    "secret_arn": "<ACME_SECRET_ARN>"
  },
  "target": {
    "type": "SFTP",
    "host": "s-zzzzzzzzzzzzzzzz.server.transfer.us-west-2.amazonaws.com",
    "port": 22,
    "username": "globex",
    "dir": "/ba8s-file-poc-landing/partners/globex/inbox",
    "secret_arn": "<GLOBEX_SECRET_ARN>"
  },
  "transfer": {
    "lambda_arn": "arn:aws:lambda:us-west-2:<ACCOUNT_ID>:function:file-transfer",
    "payload": { "flowConfigId": "partners/acme-to-globex" },
    "timeout_seconds": 1200
  },
  "validation": {
    "expect_within_seconds": 900,
    "checksum": "SHA256",
    "size_tolerance_bytes": 0
  },
  "testdata": {
    "size_bytes": 1048576,
    "pattern": "fixed",
    "filename_prefix": "diag",
    "delete_after": true
  }
}
```

> Replace `s-zzzzzzzzzzzzzzzz...` with your Globex Transfer Family server ID.

---

# 5) Optional stress variants (100 MB)

Duplicate any JSON and change:

```json
"testdata": { "size_bytes": 104857600, "pattern": "random", "filename_prefix": "diag" },
"validation": { "expect_within_seconds": 1800, "checksum": "SHA256", "size_tolerance_bytes": 0 }
```

Keep these **disabled by default** by adding `"enabled": false` and toggle on demand.

---

# 6) Upload the configs

```bash
CFG_BUCKET=$(terraform -chdir=terraform output -raw config_bucket_name)

aws s3 cp acme_s3_to_s3.json                 s3://$CFG_BUCKET/config/flows/
aws s3 cp acme_s3_to_sftp.json               s3://$CFG_BUCKET/config/flows/
aws s3 cp acme_sftp_to_s3.json               s3://$CFG_BUCKET/config/flows/
aws s3 cp acme_sftp_to_globex_sftp.json      s3://$CFG_BUCKET/config/flows/
```

---

# 7) Run a manual smoke now

* Open **Step Functions** → `fileflow-tests-sfn` → **Start execution**
* Or via CLI:

  ```bash
  aws stepfunctions start-execution --state-machine-arn $(terraform -chdir=terraform output -raw state_machine_arn)
  ```

You’ll see result artifacts under:

```
s3://$CFG_BUCKET/results/dt=YYYY-MM-DD/flow_id=<flow_id>/run_id=<uuid>/run.json
```

---

# 8) Gotchas mapped to your setup

* **Using `ec2-user` for POC**: your SFTP secrets must match the user configured on the server (Transfer Family user or EC2 SFTP daemon user) and allow key-based auth.
* **Key rotation**: rotate the Secrets Manager `privateKey`—no code changes needed; tests pick up the new key at next run.
* **Folder paths**: you’ve previously used `/ba8s-file-poc-landing/partners/<p>/inbox` on SFTP—keep that as the `dir` for targets/sources above.
* **Buckets**: if you changed from `ba8s-file-poc-landing/ba8s-file-poc-target`, update both the configs **and** `allowed_s3_arns` in `terraform.tfvars`, then `terraform apply`.

---

If you share any exact **Transfer Family server IDs** (for Globex) or a different **Lambda function name/payload**, I can tweak these JSONs precisely to your production identifiers and hand you a zipped `/configs` folder ready to upload.



Got it. Here’s how the **daily file-transfer testing framework** behaves in a real production environment—end to end, including what actually happens on AWS, how it exercises your *real* pipelines, what you’ll see, how you operate it day-to-day, and how it fails safely.

---

# 1) Big picture (what’s “really” happening)

* You already have a **production transfer system** (your Lambda that moves files between SFTP and S3).
* The framework is a **synthetic user** of that system. Once a day (or on demand), it:

  1. Creates a **synthetic file** and a **manifest** (size, SHA-256, run id).
  2. **Seeds** the file in the **real source endpoint** (S3 prefix or SFTP folder) exactly like a partner would.
  3. **Triggers your production Lambda** the same way your orchestrator would (async invoke, or by dropping a file your event mechanism picks up).
  4. **Polls the real target endpoint** until the file arrives (or a timeout).
  5. **Validates** the file’s integrity (exact byte count + checksum).
  6. **Records results** to S3 and pushes **CloudWatch metrics** so you get alarms if anything broke.

This gives you a **true end-to-end, production-path** test—credentials, directories, KMS policies, networking, security groups, NAT, Transfer Family, S3 performance, *everything*.

---

# 2) The moving parts (and why they exist)

* **Config bucket (S3)**

  * `config/flows/*.json`: one JSON per flow describing source, target, credentials, sizes, and SLOs.
  * `results/.../run.json`: immutable test outcomes (one per run per flow).
* **Lambdas (8 small functions)**

  * *List tests* → *Generate test data* → *Seed source* → *Invoke transfer* → *Poll target* → *Validate* → *Record results* → *Cleanup*.
  * Each is tiny/single-purpose = easier to secure/trace/replace.
* **Step Functions**

  * Orchestrates the above Lambdas for **every enabled flow**.
  * Concurrency control: runs multiple flows in parallel (tunable).
* **EventBridge (cron)**

  * Kicks off the state machine daily at a fixed time (e.g., 06:00 PT).
* **CloudWatch metrics & alarms**

  * `RunSuccess{FlowId}` signals green/red per flow; alarm if red or if the state machine itself fails.
* **(Optional) Paramiko layer**

  * Supplies SFTP client libs to the seed/poll Lambdas.

---

# 3) What a daily run looks like (in plain English)

1. **06:00 PT** the schedule fires.
2. **List tests** reads `config/flows/*.json` and yields, say, four test cases: S3→S3, S3→SFTP, SFTP→S3, SFTP→SFTP.
3. For each test case (in parallel up to MaxConcurrency):

   * **Generate** 1–5 MB file (or whatever you set), produce `sha256` and `run_id`.
   * **Seed source**

     * If source=S3: `PutObject` to the **real** landing bucket/prefix; place `.manifest.json` and `.sha256` next to it.
     * If source=SFTP: connect to your **real** Transfer Family/EC2 SFTP and upload the same trio.
   * **Invoke transfer**: the framework **async-invokes your production Lambda** with the same payload format your orchestrator uses (or simply drops the file and your existing rules pick it up).
   * **Poll target**:

     * If target=S3: `GetObject` (with exponential backoff) waiting for the file to appear.
     * If target=SFTP: SFTP `get` with backoff.
     * Timeout enforces your **latency SLO** (e.g., 420s for SFTP hops).
   * **Validate**: download the target object bytes, recompute `sha256`, compare size; write CloudWatch **RunSuccess=1** or **0** for that `FlowId`.
   * **Record**: write `run.json` to `results/dt=YYYY-MM-DD/flow_id=<id>/run_id=<uuid>/`. Contains the entire story (timestamps, file name, failure reason).
   * **Cleanup**: usually a no-op (you keep artifacts for audit). You can enable auto-delete if you want zero residue, but most teams keep 30 days.

If any step fails, the **reason** is captured (auth error, timeout, mismatch, permission denied, etc.), and the metric flips to **0** so your alarm fires.

---

# 4) Visual (text) sequence for SFTP → S3 case

```
EventBridge ──▶ StepFunctions (DailyFileFlowTests)
                 │
                 ├─▶ ListEnabledTests (reads S3 configs) ──▶ [tests[]]
                 │
                 └─▶ For each test (in parallel)
                      ├─▶ GenerateTestData (file+sha+manifest, run_id)
                      ├─▶ SeedSource
                      │     └─▶ SFTP upload → /outbox/diag_...dat (+ .sha256, .manifest.json)
                      ├─▶ InvokeTransfer
                      │     └─▶ Lambda invoke (your prod transfer)
                      ├─▶ PollTarget
                      │     └─▶ S3 GetObject until found (≤ expect_within_seconds)
                      ├─▶ Validate (re-sha256, size) → RunSuccess=1|0
                      ├─▶ RecordResults (S3 results/run.json)
                      └─▶ Cleanup (optional)
```

---

# 5) How this hits “real” production concerns

**Credentials & auth**

* S3 access uses the exact bucket/prefix your flows use (IAM allows only those prefixes you list).
* SFTP uses **real keys** in Secrets Manager; rejects bad keys; surfaces permission errors.

**Networking**

* If your Lambdas run in a **VPC**, make sure you have:

  * **NAT** or **VPC endpoints** (Interface endpoints for Secrets Manager; Gateway endpoint for S3).
  * Security groups that allow **outbound 22/tcp** to Transfer Family (if required by your setup).
* Any networking drift (NACL change, DNS issue, SG clamp) shows up as SFTP connection failure or S3 access errors—**you’ll see it before partners do**.

**KMS & policies**

* If target S3 uses KMS, a missing `kms:Decrypt`/`kms:Encrypt` for your test Lambda shows up as AccessDenied at seed/poll time—caught by daily tests.

**Latency/SLO**

* The `expect_within_seconds` value models your **SLA**. If your pipeline slows down (queue backlog, scaling lag), the test times out and alarms.

**Data integrity**

* SHA-256 end-to-end prevents silent truncation or encoding glitches. If a transformation is *supposed* to happen (e.g., gzip or PGP), either:

  * Test the **raw handoff** segment (e.g., SFTP→S3 pre-transform), or
  * Extend validation to match the **post-transform** artifact (e.g., inflate and hash the inner file, or verify a PGP signature).

**Scale & concurrency**

* Step Functions map state runs flows in parallel (configurable `MaxConcurrency`). Your daily synthetic load is tiny (one small file per flow), so it won’t disturb production.

**Audit & forensics**

* Every run writes a **tamper-evident record** to S3 with the run id, file name, sizes, timestamps, reason. You can turn on S3 **Object Versioning** (already configured) and optionally **Object Lock** for stricter immutability.

---

# 6) How you operate it (day-to-day)

**Daily green check (no clicks):**

* If everything’s good, no alerts. If you want a glance:

  * Look at the dashboard (add a simple CW dashboard with RunSuccess per flow).
  * Browse `results/dt=TODAY` to spot check.

**Adding a new production flow:**

1. Create a new `config/flows/<flow_id>.json` describing source, target, SLO, sizes, secrets.
2. Upload to the config bucket.
3. Either wait for the next daily, or **Start execution** in Step Functions manually to test immediately.

**Fixing a failing flow:**

* Check **run.json** for `reason`.
* Common cases:

  * *Timeout*: transfer Lambda not triggered, target prefix wrong, or system slow—verify the prod Lambda logs and triggers.
  * *AccessDenied*: add missing S3/KMS permissions; ensure test role can read/write the specific prefixes.
  * *Checksum mismatch*: the flow modified content—either fix the pipeline or change validation to what “correct” looks like (e.g., compare to the uncompressed hash).

**Cleaning up space:**

* Results auto-expire after 30 days via S3 Lifecycle (tweak as needed). Synthetic files can be auto-deleted by enabling a cleanup setting, or leaving short lifecycles/`/test/` folders on SFTP.

---

# 7) Multi-environment reality (dev/test/prod)

* **One Terraform stack per environment**, separate config buckets (e.g., `fileflow-tests-dev`, `fileflow-tests-prod`).
* Flow configs differ only by endpoints and SLOs.
* Promote configs through envs like code (PRs → review → merge → sync to S3).
* Run **hourly** in dev (cheap) and **daily** in prod.

---

# 8) Failure modes you’ll encounter (and what they mean)

| Symptom                           | What it usually means                                     | Where you’ll see it              |
| --------------------------------- | --------------------------------------------------------- | -------------------------------- |
| `Timeout waiting for target`      | Transfer not triggered; wrong dir/prefix; system too slow | PollTarget & Validate (`reason`) |
| `Auth failed / Permission denied` | Wrong SFTP key/user; Secrets ARN mismatch; SG/NACL block  | SeedSource/PollTarget logs       |
| `AccessDenied (S3/KMS)`           | IAM policy missing; wrong bucket/prefix ARN               | SeedSource/PollTarget logs       |
| `Checksum mismatch`               | Truncation, encoding change, or intentional transform     | Validate (`reason`)              |
| `ExecutionsFailed > 0`            | A Lambda crashed (bug or env var)                         | State machine alarm              |

---

# 9) Cost & blast radius (real-world)

* **Cost** is negligible: a handful of short Lambda invocations + one Step Functions execution per day + tiny S3 objects.
* **Blast radius** is controlled:

  * Tests write under **/test/** or a clearly marked partner folder; objects are small and tagged `synthetic=true`.
  * IAM least-privilege limits Lambdas strictly to the prefixes you list.
  * No partner credentials are touched; SFTP tests use your **own** Transfer Family users intended for BAU flows.

---

# 10) Extending to match “enterprise reality”

* **Contract tests** before E2E: a fast preflight that checks “directory exists”, “S3 prefix exists & writeable”, “KMS encrypt ok” to fail fast with clearer messages.
* **Groups**: run a `nightly` group plus a `critical` hourly canary (just a JSON list in `config/groups/`).
* **Bigger files weekly**: a 100 MB test on weekends to exercise multipart paths & throughput.
* **Business KPIs**: emit `TransferLatencySeconds` and monitor p95 over 7 days.
* **Compliance**: tag all artifacts; keep 90-day results in prod; export failures to a ticketing webhook (SNS → Lambda → ServiceNow/Jira).
* **DR/Active-Active**: duplicate configs for us-east-1 and verify Route 53 failover by intentionally disabling one region’s target once a month (chaos drill).

---

# 11) Why this approach works in production

* It **doesn’t mock** anything critical: it uses the same **credentials, network, storage, encryption**, and **Lambda code paths** your partners depend on.
* Failures surface **exactly** where your customers would have felt pain—but at 06:00 PT, not at 3pm during a launch.
* Artifacts and metrics make it **auditable** and **measurable**. You can prove “flows were healthy this morning” with concrete evidence.

---

If you want, I can also generate a **CloudWatch Dashboard JSON** (RunSuccess per flow + 7-day sparklines + latency percentiles) and a **ServiceNow/Jira webhook Lambda** to auto-file incidents on failures.


Perfect — here’s a **Visual Text Architecture Diagram** of your **Automated Testing Framework for File Transfer Flows**, designed for you to walk through during your meeting with the Source Team Architect.
It highlights all major AWS components, control flow, and monitoring integrations — in a clean, presentation-friendly format.

---

## 🧭 **Visual Text Architecture Diagram – Automated File Transfer Testing Framework**

```
                    ┌────────────────────────────────────────┐
                    │        🔄 EventBridge Scheduler         │
                    │  (Daily 6 AM PT - cron trigger)         │
                    └────────────────────────────────────────┘
                                        │
                                        ▼
                   ┌─────────────────────────────────────────────┐
                   │           Step Functions Workflow            │
                   │   (State Machine: fileflow-tests-sfn)        │
                   └─────────────────────────────────────────────┘
                     │          │            │             │
   ┌─────────────────┘          │            │             └────────────────┐
   ▼                            ▼            ▼                              ▼
┌──────────────┐       ┌────────────────┐  ┌────────────────┐      ┌─────────────────┐
│ List Configs │       │ Generate Test  │  │ Seed Source     │      │ Invoke Transfer  │
│ (S3 configs) │──────▶│ File & Hash    │──│ (S3 or SFTP)    │────▶ │ Lambda (Prod)   │
└──────────────┘       └────────────────┘  └────────────────┘      └─────────────────┘
                                                                         │
                                                                         ▼
                                                                  ┌──────────────┐
                                                                  │ Poll Target  │
                                                                  │ (S3/SFTP)    │
                                                                  └──────────────┘
                                                                         │
                                                                         ▼
                                                                 ┌────────────────┐
                                                                 │ Validate File  │
                                                                 │  - Size Match  │
                                                                 │  - SHA256 OK   │
                                                                 └────────────────┘
                                                                         │
                                                                         ▼
                                                              ┌──────────────────────┐
                                                              │ Record Results (S3) │
                                                              │ results/dt=YYYY-MM  │
                                                              └──────────────────────┘
                                                                         │
                                                                         ▼
                                                              ┌──────────────────────┐
                                                              │ CloudWatch Metrics  │
                                                              │   RunSuccess=1/0    │
                                                              │   Latency (Seconds) │
                                                              └──────────────────────┘
                                                                         │
                                             ┌───────────────────────────┴───────────────────────────┐
                                             │                                                       │
                              ┌────────────────────────┐                       ┌──────────────────────────────┐
                              │  CloudWatch Dashboard  │                       │ Webhook Notifier (Lambda)    │
                              │ - RunSuccess Trend     │◀─────Metrics──────────│ - Sends Alerts to Slack,     │
                              │ - Failed vs Passed     │                       │   Jira, or ServiceNow        │
                              │ - Execution Time       │                       │ - Reads URL from SecretMgr   │
                              └────────────────────────┘                       └──────────────────────────────┘
                                             │                                                       │
                                             │                                                       │
                                   ┌────────────────────────┐                              ┌────────────────────────────┐
                                   │ Source Team Dashboard  │                              │ ServiceNow / Jira Ticket  │
                                   │  (Daily health view)   │                              │ or Slack Channel Alert    │
                                   └────────────────────────┘                              └────────────────────────────┘
```

---

## ⚙️ **Key Components**

| Layer                     | AWS Service                          | Purpose                                                                                                 |
| ------------------------- | ------------------------------------ | ------------------------------------------------------------------------------------------------------- |
| **Orchestration**         | **EventBridge + Step Functions**     | Triggers daily and manages sequence of Lambda tasks                                                     |
| **Execution Units**       | **Lambda Functions (8 micro steps)** | Each does a single task: list configs, generate file, seed source, trigger flow, poll, validate, record |
| **Storage**               | **S3 (Config + Results)**            | Stores JSON flow configs and run results (tamper-evident, versioned)                                    |
| **Integration**           | **Secrets Manager**                  | Stores SFTP private keys and webhook URLs securely                                                      |
| **Notification**          | **Webhook Notifier Lambda**          | Posts failures to ServiceNow, Jira, or Slack                                                            |
| **Observability**         | **CloudWatch Dashboard + Metrics**   | Displays RunSuccess per flow, latency trends, execution counts                                          |
| **Security & Compliance** | **IAM (least privilege)**            | Lambdas limited to specific S3 prefixes and secret ARNs                                                 |

---

## 📈 **Data & Control Flow Summary**

1. **EventBridge** triggers daily at 6 AM PT.
2. **Step Functions** reads all enabled flow JSONs from S3.
3. For each flow:

   * Creates a test file (synthetic data).
   * Seeds it to source (S3 or SFTP).
   * Invokes **production transfer Lambda** (the same code that partners use).
   * Waits for the file at the target endpoint.
   * Validates content integrity and records metrics.
4. **Results** stored in S3 + **metrics** sent to CloudWatch.
5. If any flow fails → **Notifier Lambda** posts to **ServiceNow/Jira/Slack**.
6. Dashboard shows daily green/red indicators per flow.

---

## 🧩 **Meeting Discussion Highlights**

* ✅ **Why this matters:** Automates daily regression testing across all transfer paths, catching failures proactively.
* ⚙️ **Integrates with existing system:** Uses *real* endpoints, Lambda, and credentials — no mocks.
* 📊 **Visibility:** CloudWatch dashboard & webhook alerts give near-real-time insight.
* 🪄 **Low maintenance:** Adding new flows = drop a JSON config file, no redeploy.
* 🔐 **Security:** All secrets in AWS Secrets Manager; IAM scoped to exact prefixes and ARNs.
* 🚀 **Future expansion:** Add latency KPIs, PGP validation, or cross-region DR tests.

---

Would you like me to create a **PowerPoint-ready diagram image** version of this (with AWS icons and flow arrows) so you can include it in your meeting presentation deck?
