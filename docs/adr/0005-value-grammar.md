# 0005 One value grammar for all readers

Status: accepted (2026-11-19)

## Context
30+ hand-written number patterns differed and could read part of a number ('357.00' → '00').

## Decision
`engine/grammar.py` defines whole-token numbers, units, document numbers, dates and labels; readers build patterns from it; ambiguous numbers are not read.

## Consequences
Fixes in one place apply to every reader; `tests/run_grammar.py` covers the forms.
