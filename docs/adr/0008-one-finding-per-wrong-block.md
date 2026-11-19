# 0008 A wrong B/L cargo block is reported once

Status: accepted (2026-11-19)

## Context
A wrong block on a multi-invoice B/L gave a block finding and a total finding for the same error.

## Decision
Owner decision 2026-11-19: `BL_BLOCK` (naming the invoice) replaces the total finding of the same figure; the total check is `blocked_by BL_CARGO_BLOCK`.

## Consequences
The reviewer sees one finding at the right invoice.
