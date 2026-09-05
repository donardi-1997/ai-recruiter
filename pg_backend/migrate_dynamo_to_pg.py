"""DynamoDB → PostgreSQL migration script.

Reads DynamoDB JSON exports from S3, normalizes the type-annotated
fields, and bulk-inserts into PostgreSQL via COPY or batched INSERT.

Usage:
    python -m pg_backend.migrate_dynamo_to_pg --dry-run
    python -m pg_backend.migrate_dynamo_to_pg --tables candidates jobs
    python -m pg_backend.migrate_dynamo_to_pg --batch-size 2000
"""

import argparse
import csv
import gzip
import io
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

import boto3
import botocore.exceptions
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# ============================================================
# CONFIGURATION
# ============================================================

REEMPLAZAR_S3_BUCKET = os.getenv(
    "REEMPLAZAR_S3_BUCKET", "REEMPLAZAR_S3_BUCKET"
)
REEMPLAZAR_DB_URL = os.getenv(
    "REEMPLAZAR_DB_URL",
    "postgresql://postgres:postgres@localhost:5432/ai_recruiter",
)
REEMPLAZAR_AWS_REGION = os.getenv(
    "REEMPLAZAR_AWS_REGION", "us-east-2"
)

# S3 prefix where DynamoDB export places files
EXPORT_PREFIX = os.getenv("EXPORT_PREFIX", "AWSDynamoDB/exports")

# DynamoDB table name → PostgreSQL table name mapping
TABLE_MAP: dict[str, str] = {
    "ai-recruiter-candidates":   "REEMPLAZAR_DB_TABLE_CANDIDATES",
    "ai-recruiter-jobs":         "REEMPLAZAR_DB_TABLE_JOBS",
    "ai-recruiter-evaluations":  "REEMPLAZAR_DB_TABLE_EVALUATIONS",
    "ai-recruiter-job-candidates": "REEMPLAZAR_DB_TABLE_JOB_CANDIDATES",
    "ai-recruiter-rankings":     "REEMPLAZAR_DB_TABLE_RANKINGS",
}

# Column ordering per table for COPY / batch insert
TABLE_COLUMNS: dict[str, list[str]] = {
    "REEMPLAZAR_DB_TABLE_CANDIDATES": [
        "candidate_id", "owner_id", "name", "filename",
        "s3_location", "metadata_location", "ingestion_job_id",
        "ingestion_status", "indexed", "created_at", "updated_at",
    ],
    "REEMPLAZAR_DB_TABLE_JOBS": [
        "job_id", "owner_id", "title", "description",
        "created_at", "updated_at",
    ],
    "REEMPLAZAR_DB_TABLE_EVALUATIONS": [
        "job_id", "candidate_id", "owner_id", "job_title",
        "job_description", "candidate_name", "status",
        "evaluated_at", "match_score", "recommendation",
        "requirements", "strengths", "gaps", "summary",
    ],
    "REEMPLAZAR_DB_TABLE_JOB_CANDIDATES": [
        "job_id", "candidate_id", "owner_id", "status", "assigned_at",
    ],
    "REEMPLAZAR_DB_TABLE_RANKINGS": [
        "job_id", "ranking_generated_at", "ranking_version",
    ],
}

BATCH_SIZE = int(os.getenv("MIGRATE_BATCH_SIZE", "1000"))
MAX_RETRIES = int(os.getenv("MIGRATE_MAX_RETRIES", "3"))
RETRY_DELAY = float(os.getenv("MIGRATE_RETRY_DELAY", "2.0"))

# ============================================================
# LOGGING
# ============================================================

logger = logging.getLogger("migrate_dynamo_to_pg")

if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s  %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# ============================================================
# DYNAMODB JSON → PYTHON NORMALIZER
# ============================================================

def normalize_dynamo_value(dynamo_val: dict) -> Any:
    """Convert a DynamoDB-typed value to a plain Python type.

    Handles: S, N, BOOL, NULL, SS, NS, BS, L, M.
    """
    if "S" in dynamo_val:
        return dynamo_val["S"]
    if "N" in dynamo_val:
        raw = dynamo_val["N"]
        try:
            if "." in raw:
                return float(raw)
            return int(raw)
        except ValueError:
            return raw
    if "BOOL" in dynamo_val:
        return dynamo_val["BOOL"]
    if "NULL" in dynamo_val:
        return None
    if "SS" in dynamo_val:
        return dynamo_val["SS"]
    if "NS" in dynamo_val:
        return [int(x) for x in dynamo_val["NS"]]
    if "L" in dynamo_val:
        return [normalize_dynamo_value(item) for item in dynamo_val["L"]]
    if "M" in dynamo_val:
        return {
            k: normalize_dynamo_value(v)
            for k, v in dynamo_val["M"].items()
        }
    return dynamo_val


def normalize_dynamo_item(item: dict) -> dict:
    """Convert a full DynamoDB item (type-annotated) to a flat dict."""
    return {key: normalize_dynamo_value(val) for key, val in item.items()}


# ============================================================
# JSON LINES / GZIP READER
# ============================================================

def iter_s3_json_lines(
    s3_client,
    bucket: str,
    key: str,
) -> list[dict]:
    """Download an S3 object and yield parsed JSON lines.

    Handles both gzipped and plain text files.
    """
    logger.debug("Downloading s3://%s/%s", bucket, key)
    resp = s3_client.get_object(Bucket=bucket, Key=key)
    body = resp["Body"].read()

    if key.endswith(".gz"):
        body = gzip.decompress(body)

    lines: list[dict] = []
    for raw_line in body.decode("utf-8").splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            lines.append(json.loads(raw_line))
        except json.JSONDecodeError as exc:
            logger.warning("Skipping malformed JSON line in %s: %s", key, exc)
    return lines


# ============================================================
# S3 MANIFEST / EXPORT DISCOVERY
# ============================================================

def list_export_files(
    s3_client,
    bucket: str,
    prefix: str,
    dynamo_table: str,
) -> list[str]:
    """List all data files for *dynamo_table* under the export prefix.

    DynamoDB exports place files at:
        {prefix}/{dynamo_table}/aws-export-*.{json,gz}
    """
    paginator = s3_client.get_paginator("list_objects_v2")
    keys: list[str] = []

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if dynamo_table in key and key.endswith((".json", ".json.gz")):
                keys.append(key)

    keys.sort()
    logger.info(
        "Found %d data file(s) for table '%s'",
        len(keys),
        dynamo_table,
    )
    return keys


def read_export_files(
    s3_client,
    bucket: str,
    keys: list[str],
) -> list[dict]:
    """Read all export files and return normalized items."""
    all_items: list[dict] = []
    for key in keys:
        raw_items = iter_s3_json_lines(s3_client, bucket, key)
        normalized = [normalize_dynamo_item(item) for item in raw_items]
        all_items.extend(normalized)
        logger.info(
            "  %s → %d items",
            key.split("/")[-1],
            len(normalized),
        )
    return all_items


# ============================================================
# POSTGRESQL INSERT STRATEGIES
# ============================================================

def _quote_ident(name: str) -> str:
    """Quote a PostgreSQL identifier."""
    return f'"{name}"'


def _pg_string(val: Any) -> str:
    """Escape a value for PostgreSQL COPY text format."""
    if val is None:
        return "\\N"
    s = str(val)
    s = s.replace("\\", "\\\\")
    s = s.replace("\t", "\\t")
    s = s.replace("\n", "\\n")
    s = s.replace("\r", "\\r")
    return s


def _json_dumps(val: Any) -> str:
    """JSON-serialize for JSONB columns."""
    if val is None:
        return "\\N"
    return json.dumps(val, ensure_ascii=False)


def build_copy_buffer(
    pg_table: str,
    columns: list[str],
    rows: list[dict],
    jsonb_columns: set[str] | None = None,
) -> io.StringIO:
    """Build a PostgreSQL COPY text buffer from rows.

    jsonb_columns: set of column names that should be JSON-serialized.
    """
    jsonb_cols = jsonb_columns or set()
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter="\t", quoting=csv.QUOTE_MINIMAL)

    for row in rows:
        record: list[str] = []
        for col in columns:
            val = row.get(col)
            if col in jsonb_cols:
                record.append(_json_dumps(val))
            else:
                record.append(_pg_string(val))
        writer.writerow(record)

    buf.seek(0)
    return buf


def copy_batch(
    engine: Engine,
    pg_table: str,
    columns: list[str],
    rows: list[dict],
    jsonb_columns: set[str] | None = None,
) -> int:
    """Insert rows using PostgreSQL COPY for maximum throughput."""
    if not rows:
        return 0

    buf = build_copy_buffer(pg_table, columns, rows, jsonb_columns)
    col_list = ", ".join(_quote_ident(c) for c in columns)
    copy_sql = f"COPY {_quote_ident(pg_table)} ({col_list}) FROM STDIN WITH (FORMAT text)"

    with engine.connect() as conn:
        raw_conn = conn.connection.connection  # psycopg2 connection
        cursor = raw_conn.cursor()
        cursor.copy_expert(copy_sql, buf)
        inserted = cursor.rowcount
        conn.commit()

    return inserted


def insert_batch(
    engine: Engine,
    pg_table: str,
    columns: list[str],
    rows: list[dict],
    jsonb_columns: set[str] | None = None,
) -> int:
    """Fallback: batch INSERT with parameterized queries."""
    if not rows:
        return 0

    jsonb_cols = jsonb_columns or set()
    col_list = ", ".join(_quote_ident(c) for c in columns)
    placeholders = ", ".join(f":{c}" for c in columns)
    sql = text(
        f"INSERT INTO {_quote_ident(pg_table)} ({col_list}) "
        f"VALUES ({placeholders})"
    )

    inserted = 0
    with engine.begin() as conn:
        for row in rows:
            params: dict[str, Any] = {}
            for col in columns:
                val = row.get(col)
                if col in jsonb_cols and val is not None:
                    val = json.dumps(val, ensure_ascii=False)
                params[col] = val
            conn.execute(sql, params)
            inserted += 1

    return inserted


def insert_with_retry(
    engine: Engine,
    pg_table: str,
    columns: list[str],
    rows: list[dict],
    jsonb_columns: set[str] | None = None,
    use_copy: bool = True,
) -> int:
    """Insert with retry logic for transient failures."""
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if use_copy:
                return copy_batch(engine, pg_table, columns, rows, jsonb_columns)
            return insert_batch(engine, pg_table, columns, rows, jsonb_columns)
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Attempt %d/%d failed for %s: %s",
                attempt,
                MAX_RETRIES,
                pg_table,
                exc,
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)

    raise RuntimeError(
        f"Failed to insert into {pg_table} after {MAX_RETRIES} attempts"
    ) from last_error


# ============================================================
# COUNT VALIDATION
# ============================================================

def validate_count(
    engine: Engine,
    pg_table: str,
    expected: int,
    tolerance_pct: float = 0.0,
) -> bool:
    """Verify row count matches expected within tolerance.

    Returns True if valid, logs warning on mismatch.
    """
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT COUNT(*) FROM {_quote_ident(pg_table)}"))
        actual = result.scalar()

    diff = abs(actual - expected)
    threshold = max(1, int(expected * tolerance_pct / 100))

    if diff <= threshold:
        logger.info(
            "  ✓ COUNT %s = %d (expected %d, diff %d ≤ threshold %d)",
            pg_table,
            actual,
            expected,
            diff,
            threshold,
        )
        return True

    logger.error(
        "  ✗ COUNT MISMATCH %s: actual=%d expected=%d diff=%d > threshold=%d",
        pg_table,
        actual,
        expected,
        diff,
        threshold,
    )
    return False


# ============================================================
# PER-TABLE NORMALIZERS
# ============================================================

def normalize_candidates(items: list[dict]) -> list[dict]:
    """Normalize candidate items from DynamoDB export format.

    Accepts both raw DynamoDB-typed items ({"S": "val"}) and
    already-normalized plain dicts.
    """
    result = []
    for raw in items:
        item = raw if "S" in raw or "N" in raw else raw
        # Check if it looks like a DynamoDB-typed item
        first_val = next(iter(raw.values()), None)
        if isinstance(first_val, dict) and ("S" in first_val or "N" in first_val):
            item = normalize_dynamo_item(raw)
        else:
            item = raw
        row = {
            "candidate_id":     item.get("candidate_id", ""),
            "owner_id":         item.get("owner_id", item.get("user_sub", "")),
            "name":             item.get("name", ""),
            "filename":         item.get("filename", ""),
            "s3_location":      item.get("s3_location", ""),
            "metadata_location": item.get("metadata_location"),
            "ingestion_job_id": item.get("ingestion_job_id"),
            "ingestion_status": item.get("ingestion_status"),
            "indexed":          item.get("indexed", False),
            "created_at":       item.get("created_at"),
            "updated_at":       item.get("updated_at"),
        }
        result.append(row)
    return result


def normalize_jobs(items: list[dict]) -> list[dict]:
    """Normalize job items."""
    result = []
    for raw in items:
        first_val = next(iter(raw.values()), None)
        if isinstance(first_val, dict) and ("S" in first_val or "N" in first_val):
            item = normalize_dynamo_item(raw)
        else:
            item = raw
        row = {
            "job_id":      item.get("job_id", ""),
            "owner_id":    item.get("owner_id", ""),
            "title":       item.get("title", ""),
            "description": item.get("description", ""),
            "created_at":  item.get("created_at"),
            "updated_at":  item.get("updated_at"),
        }
        result.append(row)
    return result


def normalize_evaluations(items: list[dict]) -> list[dict]:
    """Normalize evaluation items — JSON fields stay as Python objects."""
    result = []
    for raw in items:
        first_val = next(iter(raw.values()), None)
        if isinstance(first_val, dict) and ("S" in first_val or "N" in first_val):
            item = normalize_dynamo_item(raw)
        else:
            item = raw
        # Parse JSON strings that DynamoDB stored as plain strings
        requirements = item.get("requirements", [])
        if isinstance(requirements, str):
            try:
                requirements = json.loads(requirements)
            except (json.JSONDecodeError, TypeError):
                requirements = []

        strengths = item.get("strengths", [])
        if isinstance(strengths, str):
            try:
                strengths = json.loads(strengths)
            except (json.JSONDecodeError, TypeError):
                strengths = []

        gaps = item.get("gaps", [])
        if isinstance(gaps, str):
            try:
                gaps = json.loads(gaps)
            except (json.JSONDecodeError, TypeError):
                gaps = []

        row = {
            "job_id":          item.get("job_id", ""),
            "candidate_id":    item.get("candidate_id", ""),
            "owner_id":        item.get("owner_id", ""),
            "job_title":       item.get("job_title", ""),
            "job_description": item.get("job_description", ""),
            "candidate_name":  item.get("candidate_name", ""),
            "status":          item.get("status", "COMPLETED"),
            "evaluated_at":    item.get("evaluated_at"),
            "match_score":     item.get("match_score", 0),
            "recommendation":  item.get("recommendation", "LOW_MATCH"),
            "requirements":    requirements,
            "strengths":       strengths,
            "gaps":            gaps,
            "summary":         item.get("summary", ""),
        }
        result.append(row)
    return result


def normalize_job_candidates(items: list[dict]) -> list[dict]:
    """Normalize job-candidate assignment items."""
    result = []
    for raw in items:
        first_val = next(iter(raw.values()), None)
        if isinstance(first_val, dict) and ("S" in first_val or "N" in first_val):
            item = normalize_dynamo_item(raw)
        else:
            item = raw
        row = {
            "job_id":       item.get("job_id", ""),
            "candidate_id": item.get("candidate_id", ""),
            "owner_id":     item.get("owner_id", ""),
            "status":       item.get("status", "PENDING_EVALUATION"),
            "assigned_at":  item.get("assigned_at"),
        }
        result.append(row)
    return result


def normalize_rankings(items: list[dict]) -> list[dict]:
    """Normalize ranking metadata items."""
    result = []
    for raw in items:
        first_val = next(iter(raw.values()), None)
        if isinstance(first_val, dict) and ("S" in first_val or "N" in first_val):
            item = normalize_dynamo_item(raw)
        else:
            item = raw
        row = {
            "job_id":                 item.get("job_id", ""),
            "ranking_generated_at":   item.get("ranking_generated_at"),
            "ranking_version":        item.get("ranking_version", 0),
        }
        result.append(row)
    return result


NORMALIZERS: dict[str, callable] = {
    "REEMPLAZAR_DB_TABLE_CANDIDATES":      normalize_candidates,
    "REEMPLAZAR_DB_TABLE_JOBS":            normalize_jobs,
    "REEMPLAZAR_DB_TABLE_EVALUATIONS":     normalize_evaluations,
    "REEMPLAZAR_DB_TABLE_JOB_CANDIDATES":  normalize_job_candidates,
    "REEMPLAZAR_DB_TABLE_RANKINGS":        normalize_rankings,
}

# Which columns are JSONB per table
JSONB_COLUMNS: dict[str, set[str]] = {
    "REEMPLAZAR_DB_TABLE_EVALUATIONS": {"requirements", "strengths", "gaps"},
}


# ============================================================
# MAIN MIGRATION ORCHESTRATOR
# ============================================================

def migrate_table(
    s3_client,
    engine: Engine,
    dynamo_name: str,
    pg_table: str,
    *,
    dry_run: bool = False,
) -> dict:
    """Migrate a single DynamoDB table to PostgreSQL.

    Returns a summary dict with counts.
    """
    logger.info("━━━ Migrating %s → %s ━━━", dynamo_name, pg_table)

    # 1. Discover export files
    keys = list_export_files(s3_client, REEMPLAZAR_S3_BUCKET, EXPORT_PREFIX, dynamo_name)
    if not keys:
        logger.warning("No export files found for '%s'. Skipping.", dynamo_name)
        return {"table": pg_table, "s3_files": 0, "raw_items": 0, "inserted": 0}

    # 2. Read and normalize
    raw_items = read_export_files(s3_client, REEMPLAZAR_S3_BUCKET, keys)
    normalizer = NORMALIZERS.get(pg_table)
    if normalizer:
        rows = normalizer(raw_items)
    else:
        rows = raw_items
        logger.warning("No normalizer for %s — inserting raw items.", pg_table)

    logger.info(
        "  Raw items: %d  →  Normalized rows: %d",
        len(raw_items),
        len(rows),
    )

    if dry_run:
        logger.info("  DRY RUN — skipping database insert.")
        if rows:
            logger.info("  Sample row: %s", json.dumps(rows[0], default=str, indent=2))
        return {"table": pg_table, "s3_files": len(keys), "raw_items": len(raw_items), "inserted": 0}

    # 3. Batch insert
    columns = TABLE_COLUMNS.get(pg_table)
    if not columns:
        logger.error("No column mapping for %s. Cannot insert.", pg_table)
        return {"table": pg_table, "s3_files": len(keys), "raw_items": len(raw_items), "inserted": 0}

    jsonb_cols = JSONB_COLUMNS.get(pg_table)
    total_inserted = 0

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        try:
            inserted = insert_with_retry(
                engine,
                pg_table,
                columns,
                batch,
                jsonb_columns=jsonb_cols,
                use_copy=True,
            )
            total_inserted += inserted
            logger.info(
                "  Batch %d–%d: %d rows inserted",
                i + 1,
                min(i + BATCH_SIZE, len(rows)),
                inserted,
            )
        except RuntimeError as exc:
            logger.error("  Batch failed at offset %d: %s", i, exc)
            # Try fallback to INSERT
            try:
                inserted = insert_with_retry(
                    engine,
                    pg_table,
                    columns,
                    batch,
                    jsonb_columns=jsonb_cols,
                    use_copy=False,
                )
                total_inserted += inserted
                logger.info("  Batch %d–%d (fallback): %d rows inserted", i + 1, min(i + BATCH_SIZE, len(rows)), inserted)
            except RuntimeError as exc2:
                logger.error("  Fallback also failed: %s", exc2)
                raise

    # 4. Validate count
    validate_count(engine, pg_table, len(rows), tolerance_pct=0.0)

    summary = {
        "table": pg_table,
        "s3_files": len(keys),
        "raw_items": len(raw_items),
        "inserted": total_inserted,
    }
    logger.info("  Summary: %s", summary)
    return summary


def run_migration(
    tables: list[str] | None = None,
    dry_run: bool = False,
) -> list[dict]:
    """Run migration for one or all tables."""
    logger.info("=" * 60)
    logger.info("DynamoDB → PostgreSQL Migration")
    logger.info("  S3 bucket:      %s", REEMPLAZAR_S3_BUCKET)
    logger.info("  S3 prefix:      %s", EXPORT_PREFIX)
    logger.info("  DB URL:         %s", REEMPLAZAR_DB_URL.split("@")[-1] if "@" in REEMPLAZAR_DB_URL else REEMPLAZAR_DB_URL)
    logger.info("  AWS region:     %s", REEMPLAZAR_AWS_REGION)
    logger.info("  Batch size:     %d", BATCH_SIZE)
    logger.info("  Dry run:        %s", dry_run)
    logger.info("=" * 60)

    s3_client = boto3.client("s3", region_name=REEMPLAZAR_AWS_REGION)
    engine = create_engine(REEMPLAZAR_DB_URL, pool_pre_ping=True)

    # Determine which tables to migrate
    if tables:
        target_tables = {}
        for t in tables:
            # Allow both DynamoDB names and PG names
            if t in TABLE_MAP:
                target_tables[t] = TABLE_MAP[t]
            elif t in TABLE_MAP.values():
                rev = {v: k for k, v in TABLE_MAP.items()}
                target_tables[rev[t]] = t
            else:
                logger.error("Unknown table: %s", t)
                sys.exit(1)
    else:
        target_tables = TABLE_MAP

    summaries: list[dict] = []
    total_start = time.time()

    for dynamo_name, pg_table in target_tables.items():
        t0 = time.time()
        summary = migrate_table(s3_client, engine, dynamo_name, pg_table, dry_run=dry_run)
        summary["elapsed_s"] = round(time.time() - t0, 2)
        summaries.append(summary)

    elapsed = round(time.time() - total_start, 2)
    logger.info("=" * 60)
    logger.info("Migration complete in %.2fs", elapsed)
    for s in summaries:
        logger.info(
            "  %s: %d files → %d items → %d inserted",
            s["table"],
            s["s3_files"],
            s["raw_items"],
            s["inserted"],
        )
    logger.info("=" * 60)

    engine.dispose()
    return summaries


# ============================================================
# CLI
# ============================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate DynamoDB exports from S3 to PostgreSQL.",
    )
    parser.add_argument(
        "--tables",
        nargs="*",
        help="Specific DynamoDB table names to migrate (default: all).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read S3 and normalize, but skip DB inserts.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help=f"Rows per batch (default: {BATCH_SIZE}).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG logging.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    global BATCH_SIZE
    BATCH_SIZE = args.batch_size

    try:
        run_migration(tables=args.tables, dry_run=args.dry_run)
    except KeyboardInterrupt:
        logger.info("Migration interrupted by user.")
        sys.exit(130)
    except Exception as exc:
        logger.exception("Migration failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
