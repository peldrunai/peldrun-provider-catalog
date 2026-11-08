<!-- 
  File: SECURITY.md
  Path: SECURITY.md
-->

# Security Policy

## Supported Versions

This repository hosts the official remote catalog (`catalog.json`), its JSON schema, and the validation scripts for PELDRUN. 

Security updates are applied to the `main` branch and the current schema version.

| Component | Supported Versions | Notes |
| :--- | :--- | :--- |
| `catalog.json` (Schema) | `schema_version: 1` | Older schema versions are deprecated. |
| Validation Scripts | `main` branch | Always use the latest commit. |
| Provider Packages | *Varies* | Packages are hosted in their own repositories. See below. |

## Scope

### What is in scope?
- Vulnerabilities in the JSON schema (`schema/catalog.schema.json`) that could lead to arbitrary code execution or bypass validation.
- Vulnerabilities in the validation scripts (`scripts/validate.py`, `scripts/fix_hashes_from_github.py`).
- Vulnerabilities in the CI/CD workflows (`.github/workflows/`) that could lead to supply chain attacks.
- **Supply Chain Integrity**: Bypassing the `checksum_sha256` verification mechanism.

### What is out of scope?
- Vulnerabilities within the **Provider Packages themselves** (e.g., the `gigachat` package). If you find a vulnerability in a specific provider package, please report it directly to that package's repository (e.g., `peldrunai/peldrun-provider-gigachat`).
- Denial of Service (DoS) attacks against GitHub's infrastructure.
- Issues related to the PELDRUN backend application (please report those to the main `peldrunai/peldrun` repository).

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

We use GitHub's Private Vulnerability Reporting to handle security issues securely. 

To report a vulnerability:
1. Go to the **Security** tab of this repository.
2. Click on **Advisories** in the left sidebar.
3. Click the **Report a vulnerability** button.
4. Provide a detailed description of the issue, including steps to reproduce, potential impact, and any suggested fixes.

### What to expect
- **Acknowledgment**: We will acknowledge receipt of your vulnerability report within **48 hours**.
- **Updates**: We will provide an update on the status of the vulnerability within **5 business days**.
- **Resolution**: If the vulnerability is accepted, we will work on a fix and coordinate a disclosure timeline with you. We aim to release patches as quickly as possible, depending on the severity.
- **Declined Reports**: If the vulnerability is declined (e.g., it is out of scope or a duplicate), we will explain the reasoning.

We kindly ask that you do not disclose the vulnerability publicly until we have had a chance to address it.

## Security Best Practices for Contributors

When contributing to this repository, please adhere to the following:
- Never commit secrets, API keys, or tokens.
- Ensure all `download_url` fields use `https://`.
- Always provide a valid `checksum_sha256` for any package. Pull requests without a checksum will be rejected by the CI.

Thank you for helping keep PELDRUN and its community safe!
