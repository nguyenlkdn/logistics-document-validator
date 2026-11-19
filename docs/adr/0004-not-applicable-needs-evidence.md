# 0004 NOT_APPLICABLE needs positive evidence

Status: accepted (2026-11-19)

## Context
Treating 'not read' as 'not applicable' hides reading gaps.

## Decision
NOT_APPLICABLE only from independent evidence: the document prints no such section (text trace), the reader's 'absent' list, the contract's list of documents, one invoice only, an F.O.C marking (owner rule).

## Consequences
Unread values give NOT_RUN with a reading reason, never NOT_APPLICABLE.
