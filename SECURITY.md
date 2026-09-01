# Security policy

## Supported versions

| Version | Security updates |
| --- | --- |
| 0.3.x | Supported |
| Earlier versions | Unsupported |

## Report a vulnerability

Use GitHub private vulnerability reporting when it is available for this repository. If it is unavailable, open a minimal public security issue without confidential details and request a private reporting channel. Include the affected version, the smallest reproducible input, the observed result, and the expected result. Do not include credentials, private biological data, provider account records, or unrelated local files.

Use a public issue for ordinary bugs that do not expose confidential data or create a security boundary failure.

## Release boundary

The bundled Python code validates local files and writes local artifacts. Codex Binder Lane 0.3.5 contains no provider executor. Default capability inventory does not invoke the Codex CLI or execute code from discovered optional repositories. The explicit Codex CLI probe invokes the selected local executable. The explicit BioSymphony probe executes one user-selected checkout and must be used only after that repository's instructions are reviewed and treated as untrusted input. Optional external tools and hosted services have separate security, authentication, data-egress, and licensing requirements.
