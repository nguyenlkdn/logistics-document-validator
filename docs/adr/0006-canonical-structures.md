# 0006 Cargo blocks, packages and item ids as typed structures

Status: accepted (2026-11-19)

## Context
B/L cargo per invoice, cartons shared by several packing-list lines and part-number lines did not fit the flat line dicts.

## Decision
`CargoBlock`, `Package`, `ItemId` on `Doc` are the source for new rules; `items` / `pl_items` remain the line view. Item ids are kept in parallel lists so the approved extracted values did not change.

## Consequences
Rules use `_units()` / `_bl_block()` / `item_ids`; old layouts (one line = one unit, one block) behave as before.
