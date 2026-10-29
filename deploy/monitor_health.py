"""Turn a /health or /health/jobs document into the problems it reports.

Used by monitor.sh, which pipes the response body in and records each line
printed as a failed check. Both endpoints answer 200 while degraded, on
purpose — a stale job or a dead Redis is not the API being down — so the
status code says nothing and the body has to be read.

    curl -s .../api/v1/health/jobs | python3 monitor_health.py jobs [max_depth]
    curl -s .../api/v1/health      | python3 monitor_health.py health

Prints nothing when all is well. Exit status is always 0: a problem is
something to report, not a failure of this script.
"""
from __future__ import annotations

import json
import sys

# The dependencies a request needs. "ai" and "integrations" are features a
# deployment may leave switched off, and /health already says so.
CORE_CHECKS = ("database", "redis", "storage")


def job_problems(doc: object, max_depth: int) -> list[str]:
    if not isinstance(doc, dict):
        return ["background-job health did not come back as a JSON object"]
    found: list[str] = []
    workers = doc.get("workers") if isinstance(doc.get("workers"), dict) else {}
    queue = doc.get("queue") if isinstance(doc.get("queue"), dict) else {}
    if doc.get("celery_enabled") and not workers.get("reachable"):
        found.append("no Celery worker answers a ping; uploads queue and are never parsed")
    if doc.get("celery_enabled") and not queue.get("reachable"):
        found.append("the task queue cannot be read; the broker may be down")
    depth = queue.get("depth")
    if isinstance(depth, int) and depth > max_depth:
        found.append(f"{depth} tasks are waiting in the queue (more than {max_depth})")
    for job in doc.get("jobs") or []:
        if isinstance(job, dict) and job.get("stale"):
            found.append(
                f"scheduled job {job.get('name')} has not run on time "
                f"(last run {job.get('last_run') or 'never'})"
            )
    if not found and doc.get("health") != "ok":
        found.append(f"background jobs report {doc.get('health')!r}")
    return found


def health_problems(doc: object) -> list[str]:
    if not isinstance(doc, dict):
        return ["/health did not come back as a JSON object"]
    checks = doc.get("checks") if isinstance(doc.get("checks"), dict) else {}
    found = []
    for name in CORE_CHECKS:
        check = checks.get(name)
        status = check.get("status") if isinstance(check, dict) else None
        if status != "ok":
            found.append(f"{name} is {status or 'not reported'} according to /health")
    return found


def main(argv: list[str], stdin: str) -> list[str]:
    try:
        doc = json.loads(stdin)
    except ValueError:
        doc = None
    if argv[1] == "jobs":
        return job_problems(doc, int(argv[2]) if len(argv) > 2 else 100)
    return health_problems(doc)


if __name__ == "__main__":
    for line in main(sys.argv, sys.stdin.read()):
        print(line)
