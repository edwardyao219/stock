# Candidate Actionability Rank Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align displayed and consumed candidate ranks with actionability, and prevent old plans from overriding current candidate status.

**Architecture:** Filter plans at workspace assembly using the existing candidate batch date tag. Rewrite existing rank tags after tier construction, preserving order inside each tier.

**Tech Stack:** Python 3.12, SQLAlchemy, pytest.

---

### Task 1: Match plans to automatic candidate batches

**Files:**
- Modify: `services/engine/workspace/repository.py`
- Test: `tests/test_workspace_api.py`

- [x] Add a failing test where a July 27 plan and July 28 risk-reject candidate share a symbol.
- [x] Verify the workspace incorrectly reports the stale plan as planned.
- [x] Add a small helper that keeps only plans matching the automatic candidate date tag.
- [x] Verify the workspace reports `risk_reject` and returns no plans.

### Task 2: Persist tier-ordered candidate ranks

**Files:**
- Modify: `services/jobs/pipeline.py`
- Test: `tests/test_jobs_pipeline.py`

- [x] Add a failing test with stale ranks across all four candidate tiers.
- [x] Verify tier tag application leaves the stale ranks unchanged.
- [x] Rewrite one `rank:` tag per candidate in tier order while preserving tier-local order.
- [x] Verify focused workspace and pipeline tests.

### Task 3: Regression and delivery

- [x] Run workspace, pipeline, intraday candidate, and paper simulator tests.
- [x] Run the full Python suite.
- [x] Commit and push `main`.
