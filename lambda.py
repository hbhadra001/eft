# -*- coding: utf-8 -*-
"""
Stream S3 -> SFTP with chunking, resume, self-chaining, retries, and atomic rename.
"""

import base64
import boto3
import io
import json
import logging
import os
import socket
import sys
import time
from typing import Dict, Tuple

import paramiko  # from Lambda layer

# ---------- Logging ----------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO),
                    format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger(__name__)

# ---------- AWS clients ----------
s3 = boto3.client("s3")
secrets = boto3.client("secretsmanager")
lmb = boto3.client("lambda")

# ---------- Env ----------
SFTP_HOST = os.environ["SFTP_HOST"]
SFTP_PORT = int(os.getenv("SFTP_PORT", "22"))
SFTP_USERNAME = os.environ["SFTP_USERNAME"]
SFTP_TARGET_DIR = os.getenv("SFTP_TARGET_DIR", "/incoming")
SECRET_ID = os.environ["SECRET_ID"]
SFTP_HOST_FINGERPRINT = os.getenv("SFTP_HOST_FINGERPRINT")

CHUNK_SIZE_BYTES = int(os.getenv("CHUNK_SIZE_MB", "8")) * 1024 * 1024
CONNECT_TIMEOUT_SEC = int(os.getenv("CONNECT_TIMEOUT_SEC", "30"))
TCP_KEEPALIVE_SEC = int(os.getenv("TCP_KEEPALIVE_SEC", "20"))
SAFETY_TIME_MS = int(os.getenv("SAFETY_TIME_MS", "30000"))  # chain when < 30s remain

MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_BASE_DELAY_SEC = float(os.getenv("RETRY_BASE_DELAY_SEC", "2"))

ENABLE_METRICS = os.getenv("ENABLE_METRICS", "true").lower() in ("1", "true", "yes")

# ---------- Helpers ----------
def _get_secret(secret_id: str) -> Dict:
    r = secrets.getSecretValue(SecretId=secret_id)
    if "SecretString" in r:
        return json.loads(r["SecretString"])
    return json.loads(base64.b64decode(r["SecretBinary"]).decode("utf-8"))

def _verify_fingerprint(host: str, port: int, expected_fp: str, timeout: int) -> None:
    sock = socket.create_connection((host, port), timeout=timeout)
    t = paramiko.Transport(sock)
    try:
        t.start_client(timeout=timeout)
        key = t.get_remote_server_key()
        actual = "SHA256:" + base64.b64encode(key.get_fingerprint(hashalg="sha256")).decode("utf-8")
        if actual != expected_fp:
            raise RuntimeError(f"Host fingerprint mismatch. Expected {expected_fp}, got {actual}")
    finally:
        try: t.close()
        except Exception: pass

def _connect_sftp(host: str, port: int, username: str, secret: Dict,
                  timeout: int, keepalive: int) -> paramiko.SFTPClient:
    if SFTP_HOST_FINGERPRINT:
        _verify_fingerprint(host, port, SFTP_HOST_FINGERPRINT, timeout)

    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        if hasattr(socket, "TCP_KEEPIDLE"):
            try: sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, keepalive)
            except OSError: pass

        t = paramiko.Transport(sock)
        t.use_compression(True)
        t.start_client(timeout=timeout)

        if "private_key" in secret:
            pkey = None
            for loader in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
                try:
                    pkey = loader.from_private_key(io.StringIO(secret["private_key"]),
                                                   password=secret.get("passphrase"))
                    break
                except Exception:
                    continue
            if not pkey:
                raise RuntimeError("Invalid private key")
            t.auth_publickey(username, pkey)
        elif "password" in secret:
            t.auth_password(username, secret["password"])
        else:
            raise RuntimeError("Secret must include 'private_key' or 'password'")

        t.set_keepalive(keepalive)
        return paramiko.SFTPClient.from_transport(t)
    except Exception:
        try: sock.close()
        except Exception: pass
        raise

def _mkdir_p(sftp: paramiko.SFTPClient, path: str) -> None:
    parts = [p for p in path.strip("/").split("/") if p]
    cur = ""
    for p in parts:
        cur += f"/{p}"
        try: sftp.stat(cur)
        except IOError:
            try: sftp.mkdir(cur)
            except IOError: sftp.stat(cur)  # race-safe

def _s3_head(bucket: str, key: str) -> Tuple[int, Dict]:
    h = s3.head_object(Bucket=bucket, Key=key)
    return h["ContentLength"], h

def _s3_range(bucket: str, key: str, start: int, end: int) -> bytes:
    o = s3.get_object(Bucket=bucket, Key=key, Range=f"bytes={start}-{end}")
    return o["Body"].read()

def _publish_atomic(sftp: paramiko.SFTPClient, part_path: str, final_path: str, expected_size: int) -> None:
    st = sftp.stat(part_path)
    if st.st_size != expected_size:
        raise RuntimeError(f"Remote size mismatch: {st.st_size} != {expected_size}")
    try: sftp.remove(final_path)
    except IOError: pass
    sftp.rename(part_path, final_path)

def _emit_emf(namespace: str, dims: Dict[str, str], metrics: Dict[str, float]) -> None:
    if not ENABLE_METRICS: return
    body = {
        "_aws": {
            "Timestamp": int(time.time()*1000),
            "CloudWatchMetrics": [{
                "Namespace": namespace,
                "Dimensions": [list(dims.keys())],
                "Metrics": [{"Name": k, "Unit": "None"} for k in metrics.keys()]
            }]
        }
    }
    body.update(dims); body.update(metrics)
    print(json.dumps(body))  # EMF parser reads from logs

def _self_invoke(fn_name: str, payload: Dict) -> None:
    lmb.invoke(FunctionName=fn_name, InvocationType="Event",
               Payload=json.dumps(payload).encode("utf-8"))

# ---------- Core upload slice ----------
def _upload_slice(bucket: str, key: str, sftp: paramiko.SFTPClient,
                  remote_dir: str, chunk_bytes: int,
                  remaining_ms, safety_ms: int) -> Tuple[int, int, str, str]:
    total, _ = _s3_head(bucket, key)
    filename = os.path.basename(key)
    final_path = f"{remote_dir.rstrip('/')}/{filename}"
    part_path  = final_path + ".part"

    _mkdir_p(sftp, remote_dir)

    try:
        offset = sftp.stat(part_path).st_size
    except IOError:
        offset = 0

    mode = "ab" if offset > 0 else "wb"
    sent = offset
    last_log = offset

    log.info(f"Start slice: file={filename}, total={total}, offset={offset}, chunk={chunk_bytes}")

    with sftp.file(part_path, mode) as rf:
        rf.set_pipelined(True)
        pos = offset
        while pos < total:
            if remaining_ms() <= safety_ms:
                log.info(f"Chaining: pos={pos} total={total}")
                return pos, total, part_path, final_path
            end = min(pos + chunk_bytes - 1, total - 1)
            data = _s3_range(bucket, key, pos, end)
            rf.write(data)
            pos = end + 1
            sent = pos
            if sent - last_log >= 32*1024*1024:
                log.info(f"Progress {filename}: {sent}/{total} ({sent/total:.1%})")
                last_log = sent

    return sent, total, part_path, final_path

# ---------- Handler ----------
def handler(event, context):
    """
    Event:
      - Direct: {"bucket":"my-data-bucket","key":"big/ten-gig.bin"}
      - S3 Put  (auto-detected)
    """
    t0 = time.time()

    if "Records" in event:
        rec = event["Records"][0]["s3"]
        bucket = rec["bucket"]["name"]
        key    = rec["object"]["key"]
    else:
        bucket = event["bucket"]
        key    = event["key"]

    dims = {"Function": context.function_name, "Bucket": bucket}
    metrics = {}
    attempt = 0
    secret = _get_secret(SECRET_ID)

    while True:
        attempt += 1
        try:
            sftp = _connect_sftp(SFTP_HOST, SFTP_PORT, SFTP_USERNAME, secret,
                                 CONNECT_TIMEOUT_SEC, TCP_KEEPALIVE_SEC)

            sent, total, part_path, final_path = _upload_slice(
                bucket, key, sftp, SFTP_TARGET_DIR, CHUNK_SIZE_BYTES,
                remaining_ms=context.get_remaining_time_in_millis,
                safety_ms=SAFETY_TIME_MS
            )

            if sent >= total:
                _publish_atomic(sftp, part_path, final_path, total)
                try: sftp.close()
                except Exception: pass
                dur_ms = int((time.time()-t0)*1000)
                metrics.update({"bytesSent": float(total), "runs": 1.0, "durationMs": float(dur_ms)})
                _emit_emf("S3ToSFTP", dims, metrics)
                log.info(f"SUCCESS: {final_path} ({total} bytes) in {dur_ms} ms")
                return {"status":"ok","bucket":bucket,"key":key,"remote_path":final_path,
                        "bytes":total,"duration_ms":dur_ms,"attempts":attempt}

            # Not finished → chain
            _self_invoke(context.function_name, {"bucket": bucket, "key": key})
            try: sftp.close()
            except Exception: pass

            dur_ms = int((time.time()-t0)*1000)
            metrics.update({"bytesSent": float(sent), "runs": 1.0, "durationMs": float(dur_ms)})
            _emit_emf("S3ToSFTP", dims, metrics)
            log.info(f"CHAINED: {sent}/{total} bytes")
            return {"status":"chained","bucket":bucket,"key":key,"sent":sent,"total":total,
                    "duration_ms":dur_ms,"attempts":attempt}

        except Exception as e:
            log.error(f"Attempt {attempt} failed: {e}", exc_info=True)
            if attempt >= MAX_RETRIES:
                dur_ms = int((time.time()-t0)*1000)
                metrics.update({"bytesSent": 0.0, "runs": float(attempt), "durationMs": float(dur_ms)})
                _emit_emf("S3ToSFTP", dims, metrics)
                raise
            delay = RETRY_BASE_DELAY_SEC * (2 ** (attempt - 1))
            time.sleep(delay + delay*0.1)
