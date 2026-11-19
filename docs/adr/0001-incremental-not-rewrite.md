# 0001 Incremental refactor instead of a rewrite

Status: accepted (2026-11-19)

## Context
The 2026-11-19 review found four design weaknesses (lines without columns, no shared value grammar, silent check skips, misreadings reported as document errors).

## Decision
Fix them at their source in phases P1–P6 on the existing engine; keep `Field` provenance, evidence, sessions and the approved baselines.

## Consequences
Each phase is reviewable and must keep the approved findings identical (or explain each change). A full rewrite was rejected by the owner.
