# skills/ — single-source skill-system components

This directory holds reusable **skill** components for the assistant. A skill is a
small, named capability description that the engine can compose into a behavior.

## The single-source pattern (principle 2)
A complex behavior must **reference** separate single-source components rather than
baking copies of them in. So a skill never duplicates a fact that already lives in
an `authored/` file or another skill — it points at it. Updating the referenced
source then propagates everywhere the skill is used.

## Convention
- One skill per file: `skills/<skill-name>.md`.
- Start with a short header: what it does, when to use it, and which sources it
  references (by path), e.g. `references: authored/preferences.md`.
- Keep skills model-agnostic: describe the behavior, not a specific model's syntax.

This is set up now and used as the system grows; v1 ships the pattern + this README.
