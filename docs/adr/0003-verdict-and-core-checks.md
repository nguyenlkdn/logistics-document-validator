# 0003 Three-state verdict from configurable core checks

Status: accepted (2026-11-19)

## Context
'No open error' was shown even when important checks never ran.

## Decision
RED = open ERROR (any check); AMBER = a core check NOT_RUN or REVIEW_REQUIRED; GREEN = every applicable core check PASS. Core list in `config.json "core_checks"`. Plain sign-off only on GREEN.

## Consequences
Packages that looked clean can now be AMBER; reviewers sign them off as exceptions with a reason.
