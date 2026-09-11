# Security Policy

This document describes how to report a security vulnerability in sbomify and what happens after you do. It covers the hosted platform at [app.sbomify.com](https://app.sbomify.com), self-hosted deployments of this repository, and the open source projects in the [sbomify GitHub org](https://github.com/sbomify).

**Our canonical security contact record is [`security.txt`](https://trust.sbomify.com/.well-known/security.txt), published on the [sbomify trust center](https://trust.sbomify.com) per [RFC 9116](https://www.rfc-editor.org/rfc/rfc9116).** Where this document and `security.txt` ever disagree about how to reach us, `security.txt` is authoritative.

- [Reporting a Vulnerability](#reporting-a-vulnerability)
- [What Happens Next](#what-happens-next)
- [Disclosure Policy](#disclosure-policy)
- [API Access Tokens](#api-access-tokens)

## Reporting a Vulnerability

The sbomify team takes all security vulnerabilities seriously. Thank you for improving the security of our software. We appreciate your effort and your responsible disclosure, and we will make every effort to acknowledge your contribution.

**Report security vulnerabilities by emailing the sbomify security team at [security@sbomify.com](mailto:security@sbomify.com).**

That address is the one published in the `Contact` field of [`security.txt`](https://trust.sbomify.com/.well-known/security.txt). **To encrypt your report, use the OpenPGP key its `Encryption` field points to** — we deliberately do not repeat the key URL here, so that there is one place to change it.

Please tell us what you found, how to reproduce it, what you believe the impact is, and include any proof of concept you have. Timestamps in UTC help us line your report up against our own logs.

Please report vulnerabilities in third-party modules to the person or team maintaining the module.

## What Happens Next

sbomify is a small team. We would rather describe how we actually work than publish a response clock we cannot hold to.

- We acknowledge every report, and we tell you the outcome — including when we conclude that what you found is not a vulnerability.
- We triage on whether an issue is being exploited and whether it is reachable from the Internet, rather than on score alone. That judgement sets the remediation deadline under our internal vulnerability management policy, which we share with customers and assessors on request.
- An actively exploited vulnerability is handled as a security incident rather than as a routine ticket, with the escalation that implies.
- We will keep you informed of progress towards a fix and an advisory, and we may come back to you for more information or guidance.

Reporting in good faith is never held against the person reporting, including where the finding turns out to be nothing.

## Disclosure Policy

When we receive a security report, one person takes ownership of it and coordinates the fix and the release:

- Confirm the problem and determine which versions and deployments are affected.
- Audit the surrounding code for similar problems.
- Prepare the fix. For [app.sbomify.com](https://app.sbomify.com) a fix reaches you when we deploy it; for self-hosted deployments it ships in a new container image and, where relevant, a new chart release.
- Publish a [security advisory](https://github.com/sbomify/sbomify/security/advisories) on the affected repository once a fix is available.

Please give us a reasonable opportunity to fix an issue before disclosing it publicly. We will credit you in the advisory unless you would rather we did not.

sbomify does not currently run a paid bug bounty programme.

## API Access Tokens

For using and rotating API access tokens safely (scoping, expiry, rotation, and the legacy unscoped-token migration), see [docs/access-tokens.md](docs/access-tokens.md).
