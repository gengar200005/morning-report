"""Bounded Drive retries with allowlisted public diagnostics."""
import hashlib
import io
import json
import random
import time
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

REASONS = frozenset((
    "rateLimitExceeded", "userRateLimitExceeded", "backendError",
    "internalError", "dailyLimitExceeded", "storageQuotaExceeded",
    "insufficientPermissions", "authError", "notFound", "forbidden",
    "invalid", "badRequest", "fileNotDownloadable",
))
RATE_REASONS = frozenset(("rateLimitExceeded", "userRateLimitExceeded"))
TRANSPORT = (OSError, TimeoutError, ConnectionError)

def diagnostic(exc):
    if isinstance(exc, HttpError):
        status = int(exc.resp.status)
        try:
            error = json.loads(exc.content).get("error", {})
            reasons = {x.get("reason") for x in error.get("errors", [])}
        except (ValueError, TypeError, AttributeError):
            reasons = set()
        safe = sorted(reasons & REASONS)
        return status, safe
    return 0, ["transport"] if isinstance(exc, TRANSPORT) else ["unclassified"]

def retryable(exc):
    status, reasons = diagnostic(exc)
    return status == 429 or status in (500, 502, 503, 504) or (
        status == 403 and bool(set(reasons) & RATE_REASONS)
    ) or isinstance(exc, TRANSPORT)

def log_error(exc, operation, attempt):
    status, reasons = diagnostic(exc)
    # Never print exception repr, content, request URL or provider message.
    print(f"DRIVE_ERROR operation={operation} attempt={attempt} http={status} "
          f"reason={','.join(reasons) or 'unclassified'}", flush=True)

def pause(attempt):
    time.sleep(min(32, 2 ** attempt) + random.random())

def read_retry(call, operation="read"):
    for attempt in range(6):
        try:
            return call()
        except Exception as exc:
            log_error(exc, operation, attempt + 1)
            if not retryable(exc) or attempt == 5:
                raise
            pause(attempt)

def upload_archive(drive, fid, name, description, data, find, verify):
    """Use one pre-generated ID for all attempts, then re-read full contents."""
    file_id = read_retry(
        lambda: drive.files().generateIds(count=1, space="drive", type="files").execute()
    )["ids"][0]
    for attempt in range(6):
        # Recheck immutable name before any create, including uncertain retries.
        prior = read_retry(lambda: find(drive, fid, name))
        if prior is not None:
            verify(prior)
            return prior
        try:
            result = drive.files().create(
                body={"id": file_id, "name": name, "parents": [fid],
                      "description": description},
                media_body=MediaIoBaseUpload(io.BytesIO(data),
                    mimetype="application/gzip", resumable=True),
                fields="id,name,md5Checksum,size,shared,description",
            ).execute()
        except Exception as exc:
            log_error(exc, "upload", attempt + 1)
            status, _ = diagnostic(exc)
            # Commit may have succeeded despite loss of its response. Query
            # the same ID before retrying, and never allocate a replacement ID.
            if retryable(exc) or status == 409:
                try:
                    result = read_retry(lambda: drive.files().get(
                        fileId=file_id,
                        fields="id,name,md5Checksum,size,shared,description",
                    ).execute())
                except HttpError as lookup:
                    if int(lookup.resp.status) != 404:
                        raise
                    if attempt == 5:
                        raise exc
                    pause(attempt)
                    continue
            else:
                raise
        verify(result)
        return result
    raise RuntimeError("Drive upload recovery exhausted")
