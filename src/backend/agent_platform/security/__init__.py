"""Credential resolution, authentication and authorisation.

Responsibility
    Isolates *how* the platform proves who it is. ``DefaultAzureCredential``
    covers both local development (``az login``) and production (Managed
    Identity) without the application code differing between them
    (``architecture.md`` §55).

Design rule
    No credential, key or connection string is ever constructed outside this
    package, and none is ever logged.

Filled in from Milestone 05; authorisation (RBAC) is deferred but not designed out.
"""
