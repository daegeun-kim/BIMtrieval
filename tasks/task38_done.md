# Task 38: Secure self-hosted deployment package

## Goal

Make BIMtrieval release-ready and self-hostable without operating a public backend that spends the owner's OpenAI token.

Shared session context and constraints are defined in Task 32.

## Work

- Provide a production-oriented Compose profile or equivalent small extension of Task 35 for a user who clones the repository and supplies their own local `.env`.
- Do not deploy or design a shared OpenAI-key service. Do not collect API keys in the frontend or send them to any third-party service other than the configured OpenAI backend call.
- Keep database data and user IFC files local/persistent and excluded from images and source control.
- Apply appropriate container/runtime security, health checks, restart behavior, bounded requests, and production configuration without introducing a large infrastructure stack.
- Document a provider-neutral self-host procedure and the boundary between the public portfolio presentation and the user's own running instance.
- Ensure the app remains useful enough to inspect when no key or model has been configured, with truthful setup guidance rather than fabricated responses.

## Validation

Validate the release configuration from a clean local setup with temporary non-secret values derived from `.env.example`. Do not read the user's `.env`. Confirm images contain no secrets or user data and that the documented user-owned-key flow matches the implementation.
