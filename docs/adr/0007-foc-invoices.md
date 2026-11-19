# 0007 F.O.C invoices need no contract and no Form D

Status: accepted (2026-11-19)

## Context
A parts invoice under the same B/L had no contract and no Form D; 29 checks stayed 'requirement unknown'.

## Decision
Owner decision 2026-11-19: an invoice marked F.O.C / NO COMMERCIAL VALUE / FREE OF CHARGE makes the contract and Form D checks NOT_APPLICABLE (evidence `foc_invoice`).

## Consequences
Other invoices without a contract / Form D stay `requirement_unknown` (AMBER).
