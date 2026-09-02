# AI Mode Host Port Conflict Design

## Goal

Allow the team Docker Compose application to start on macOS when Control Center is already using host port 7000.

## Selected approach

Change only the root `docker-compose.yml` host mapping for `ai-mode` from `7000:7000` to `7001:7000`.

- Host access to AI Mode will use `http://localhost:7001`.
- The AI Mode process will continue listening on port 7000 inside its container.
- Other containers will continue using `http://ai-mode:7000` through the Compose network.
- No Java, Python, environment-variable, health-check, or Student 1/2 API changes are required.

## Alternatives considered

1. Disable macOS AirPlay Receiver to free port 7000. This preserves the existing host port but changes a system-level feature.
2. Remove the AI Mode host mapping. Container-to-container calls would work, but developers could not call AI Mode directly from the host.

The selected mapping is the smallest project-local change and does not require changing macOS settings.

## Validation

1. Run `docker compose config -q` from the repository root.
2. Confirm the rendered mapping is host port 7001 to container port 7000.
3. Start the relevant Compose services and confirm `ai-mode` becomes healthy.
4. Confirm Student 1 and Student 2 remain healthy and the catalogue lookup still succeeds.

## Rollback

Restore the mapping to `7000:7000` after host port 7000 is available.
