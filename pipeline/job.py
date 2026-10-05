"""The shared job file every role agent reads and writes.

One job = one batch of raw footage. It lives at jobs/<job_id>/job.json.
Each stage only writes its own key and marks itself done in "stages", so any
stage can be re-run without touching the others.
"""
import json
import os
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOBS = os.path.join(ROOT, "jobs")

STAGES = ["intake", "cutter", "visuals", "audio", "packager", "approval", "posted"]


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def job_dir(job_id):
    return os.path.join(JOBS, job_id)


def job_path(job_id):
    return os.path.join(job_dir(job_id), "job.json")


def new_job(job_id, note=""):
    return {
        "id": job_id,
        "created": now(),
        "note": note,
        "stages": {s: {"status": "pending"} for s in STAGES},
        "trends": {},
        "sources": [],
        "candidates": [],
        "cuts": {},
        "visuals": {},
        "audio": {},
        "package": {},
        "approval": {"approved": False, "by": None, "at": None, "items": []},
    }


def load(job_id):
    with open(job_path(job_id)) as f:
        return json.load(f)


def save(job):
    os.makedirs(job_dir(job["id"]), exist_ok=True)
    tmp = job_path(job["id"]) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(job, f, indent=1)
        f.write("\n")
    os.replace(tmp, job_path(job["id"]))


def mark(job, stage, status, **extra):
    job["stages"][stage] = {"status": status, "at": now(), **extra}
