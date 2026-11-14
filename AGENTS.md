# AGENTS.md

## Scope

- These instructions apply to the entire repository.
- Treat `plans/` as the primary and authoritative source of truth for project requirements, architecture, decisions, and implementation guidance.
- Always inspect relevant `plans/` documentation before planning, analyzing, or modifying code. Consult nearby code and other documentation for implementation context.
- If documentation, code, or instructions conflict with `plans/`, stop and explicitly report the mismatch before proceeding, unless the user explicitly overrides it.
- Do not assume undocumented behavior or expand scope without authorization.

## Working Rules

- Always use Ponytail skill, Graphify skill, and MCP.
- Inspect relevant documentation and nearby code before editing. Preserve unrelated user changes.
- Keep changes small, focused, and consistent with established repository conventions.
- Update adjacent documentation when behavior, configuration, migrations, or operational steps change.
- If conventions are absent, use idiomatic patterns, clear ownership, and explicit error handling.
- Never declare work complete while known failures, skipped required checks, or unresolved scope questions remain undisclosed.
- Never commit secrets, credentials, tokens, or real personal data. Use documented environment variables and safe local fixtures.

## Test Rules

- Identify the project's tech stack, test framework, and configured validation commands before making changes.
- Add or update appropriate tests alongside every code change requiring coverage.
- Run relevant tests after every meaningful code change, starting with the narrowest affected tests, then the broader applicable suite.
- Run the project's configured formatting, linting, static analysis, type checking, build, and test commands as applicable.
- For database changes, run relevant migration and integration tests, including blank-to-head and repeat/idempotence coverage when migrations are affected.
- For infrastructure or configuration changes, validate affected files and smoke-test relevant services or health endpoints when available.
- Add regression tests for bug fixes and coverage for new behavior. Never weaken or delete tests merely to make checks pass.
- Record every check in `WORKLOG.md`. For checks that cannot run, document the exact command, reason, and remaining risk.

## Worklog Rules

- Update `WORKLOG.md` in the same change after meaningful codebase work, including features, fixes, migrations, refactors, dependency/configuration changes, and significant documentation or operational decisions.
- Insert new entries at the top of the `Entries` section using an ISO 8601 UTC timestamp and the documented entry template.
- Keep entries factual: summarize outcomes, material files/components, validation results, and outstanding risks or follow-ups.
- Do not log routine exploration, read-only inspection, or trivial formatting alone.
- Do not rewrite older entries except to correct factual errors.

## Graphify Rules

- **Codebase Analysis:** Before global workspace searches, parse `graphify-out/graph.json` to understand repository structure.
- **Dependency & Import Maps:** Use `graphify-out/graph.json` exclusively to trace cross-file imports, function calls, and module relationships.
- **Token Efficiency:** Do not scan source files sequentially to discover architectural connections. Use the precompiled graph for navigation and inspect only relevant source files.
- **Source of Truth:** Graphify provides structural context; `plans/` remains authoritative for requirements, architecture, and decisions.
- **Workspace Updates:** After structural changes or new components, remind the user to run `graphify . --code-only` to refresh the graph and `graphify cluster-only .` to regenerate `GRAPH_REPORT.md`.