# 0002 Separate field status and check status

Status: accepted (2026-11-19)

## Context
A missing input made a check disappear, and 'missing' could not be told from 'mismatch'.

## Decision
`FieldStatus` (READ, UNREADABLE, ABSENT, NOT_FOUND, SUSPECT) describes a value; `CheckStatus` (PASS, FAIL, REVIEW_REQUIRED, NOT_RUN, NOT_APPLICABLE) describes a check execution. Every registered check leaves one record per group.

## Consequences
Guards record their reason; PASS needs every input READ and a comparison. The blank-out sweep proves no PASS without inputs.
