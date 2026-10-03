# Coding conventions

Verified on 2026-08-03.

This is a generic coding conventions. 

Comments should be short and minimal, purely descriptive avoiding verbose comments.

## Fail fast and loudly

- Raise an error with enough context to identify the bad row, entity, or invariant.
- Never use `except Exception: pass`, silent `continue`, or a fallback that turns a broken contract into incomplete output.
- Empty-result guards must return the exact schema expected downstream.
- Use `ValueError` for invalid user data and `RuntimeError` when the program or upstream producer violated an internal contract.

## Put validation in the right layer

- Business and data rules belong in the backend validator, where they can become clear user-facing errors.
- Structural checks belong in the algorithm data reader: referenced master entities, topology, and required input shape must resolve before simulation.
- Physical impossibilities and accumulated-state invariants belong inside the simulator.
- Do not duplicate the same business validation in several layers.

## Trust explicit internal contracts

Do not use `getattr(..., None)`, `.get(key, fallback)`, `hasattr`, or broad `try/except` around the team's own dataclasses, SQLModel rows, Pydantic models, or simulation objects. A missing required field is a bug and should fail where it is first observed.

Fallback access is acceptable only at a real boundary, such as optional user configuration or external JSON. Add a comment naming that boundary.

## Numeric and datetime comparisons

Use the project `aux_math` helpers for floating-point and datetime comparisons. Direct equality and hand-written tolerances are easy to make inconsistent across services.
