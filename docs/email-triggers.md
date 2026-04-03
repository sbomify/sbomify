# Email Trigger Map

Comprehensive diagram of all emails sent by sbomify, their triggers, conditions, and recipients.

## Overview

sbomify sends **25 distinct emails** across 5 categories:

| Category | Count | Trigger Type |
|----------|-------|-------------|
| Billing | 7 | Stripe webhooks |
| Onboarding | 6 | User signup + daily cron drip |
| Team Invitations | 3 | User actions |
| Document Access | 4 | Access request lifecycle |
| Enterprise Inquiry | 1 | Contact form |

---

## 1. Billing Emails

Triggered by Stripe webhook events, processed in `billing_processing.py`. All billing emails are sent to **team owners** via `notify_team_owners()`.

```mermaid
flowchart TD
    subgraph Stripe Webhooks
        W1[customer.subscription.updated]
        W2[customer.subscription.deleted]
        W3[invoice.payment_failed]
        W4[invoice.payment_succeeded]
    end

    W1 --> HSU[handle_subscription_updated]
    W2 --> HSD[handle_subscription_deleted]
    W3 --> HPF[handle_payment_failed]
    W4 --> HPS[handle_payment_succeeded]

    HSU --> |"status == past_due"| E1["📧 Payment Past Due\nSubject: Payment past due for {team}"]
    HSU --> |"status == active"| E2["📧 Payment Succeeded\nSubject: Payment received for {team}"]
    HSU --> |"status == canceled"| E3["📧 Subscription Cancelled\nSubject: Your sbomify subscription has been cancelled"]
    HSU --> |"status == incomplete/incomplete_expired"| E4["📧 Payment Failed\nSubject: Payment failed for {team}"]
    HSU --> |"trial ending <= N days"| E5["📧 Trial Ending\nSubject: Your sbomify trial ends in {days} days"]
    HSU --> |"trial expired"| E6["📧 Trial Expired\nSubject: Your sbomify trial has expired"]

    HSD --> E7["📧 Subscription Ended\nSubject: Your sbomify subscription has ended"]

    HPF --> E4
    HPS --> E2

    E1 --> R1[To: Team owners/admins]
    E2 --> R1
    E3 --> R1
    E4 --> R1
    E5 --> R1
    E6 --> R1
    E7 --> R1

    style E1 fill:#fee2e2
    style E2 fill:#d1fae5
    style E3 fill:#fef3c7
    style E4 fill:#fee2e2
    style E5 fill:#fef3c7
    style E6 fill:#fee2e2
    style E7 fill:#fef3c7
```

### Billing Email Details

| Email | Template | Has CTA | Plain Text |
|-------|----------|---------|------------|
| Payment Past Due | `payment_past_due` | ✅ Update Payment | ✅ |
| Payment Failed | `payment_failed` | ✅ Update Payment | ✅ |
| Payment Succeeded | `payment_succeeded` | ❌ | ✅ |
| Trial Ending | `trial_ending` | ✅ Upgrade Now | ✅ |
| Trial Expired | `trial_expired` | ✅ Upgrade Now | ✅ |
| Subscription Cancelled | `subscription_cancelled` | ✅ Reactivate | ✅ |
| Subscription Ended | `subscription_ended` | ✅ Renew | ✅ |

---

## 2. Onboarding Emails

Welcome email triggered by user signup signal. Drip sequence processed by daily cron at **9:00 AM UTC**. All sent to **primary workspace owners** only.

```mermaid
flowchart TD
    subgraph Signup
        S1[User Created Signal\nonboarding/signals.py]
    end

    subgraph "Daily Cron (9:00 AM UTC)"
        C1[daily_onboarding_reminders\nonboarding/cron.py]
    end

    S1 --> |"10s delay"| E1["📧 Welcome\nSubject: Welcome to sbomify - Let's Get Started!\nTrigger: Immediately after signup"]

    C1 --> CHECK{Check each\nprimary owner}

    CHECK --> |"Day 1+\nwelcome sent"| E2["📧 Quick Start Guide\nSubject: Your quick start guide - sbomify"]

    CHECK --> |"Day 3+\nno components"| E3["📧 First Component Reminder\nSubject: Ready to create your first component?"]

    CHECK --> |"Day 7+\nhas component, no SBOM"| E4["📧 First SBOM Reminder\nSubject: Time to upload your first SBOM"]

    CHECK --> |"Day 3+ no component\nOR Day 7+ no SBOM"| E5["📧 Component/SBOM Combined\nSubject: Adaptive based on progress"]

    CHECK --> |"Day 10+\nsolo workspace"| E6["📧 Collaboration\nSubject: Invite your team to sbomify"]

    E1 --> R1[To: New user]
    E2 --> R1
    E3 --> R1
    E4 --> R1
    E5 --> R1
    E6 --> R1

    style E1 fill:#dbeafe
    style E2 fill:#dbeafe
    style E3 fill:#fef3c7
    style E4 fill:#fef3c7
    style E5 fill:#fef3c7
    style E6 fill:#e0e7ff
```

### Onboarding Drip Timeline

```mermaid
gantt
    title Onboarding Email Drip Schedule
    dateFormat X
    axisFormat Day %s

    section Emails
    Welcome (signup)           :done, 0, 1
    Quick Start (Day 1+)       :active, 1, 2
    First Component (Day 3+)   :crit, 3, 4
    First SBOM (Day 7+)        :crit, 7, 8
    Collaboration (Day 10+)    :10, 11
```

### Onboarding Conditions

| Email | Condition | Dedup |
|-------|-----------|-------|
| Welcome | User created | OnboardingStatus.welcome_email_sent |
| Quick Start | Day 1+, welcome sent | OnboardingEmail record |
| First Component | Day 3+, no components created | OnboardingEmail record |
| First SBOM | Day 7+, has component, no SBOM uploaded | OnboardingEmail record |
| Component/SBOM Combined | Day 3+ (no component) OR Day 7+ (no SBOM) | OnboardingEmail record |
| Collaboration | Day 10+, solo workspace (only 1 member) | OnboardingEmail record |

---

## 3. Team & Invitation Emails

Triggered by user actions in workspace settings.

```mermaid
flowchart TD
    subgraph User Actions
        A1[Owner invites member\nteams/views]
        A2[User signs up\nteams/signals.py\nensure_user_has_team]
        A3[Admin sends Trust Center invite\ndocuments/views/access_requests.py]
    end

    A1 --> E1["📧 Team Invite\nSubject: Invitation to join {team} at sbomify"]
    A2 --> E2["📧 New User Welcome\nSubject: Welcome to sbomify - Your Business Plan Trial"]
    A3 --> E3["📧 Trust Center Invite\nSubject: Invitation to access {team}'s Trust Center"]

    E1 --> R1[To: Invitee email]
    E2 --> R2[To: New user email]
    E3 --> R3[To: External invitee email]

    E1 --> EXP1["Expires: invitation.expires_at"]
    E3 --> EXP2["Expires: invitation.expires_at"]

    style E1 fill:#e0e7ff
    style E2 fill:#dbeafe
    style E3 fill:#e0e7ff
```

---

## 4. Document Access Emails

Triggered by the access request lifecycle for gated Trust Center content. Sent via views in `documents/views/access_requests.py` and APIs in `documents/access_apis.py`.

```mermaid
flowchart TD
    subgraph "Access Request Lifecycle"
        A1[External user\nrequests access]
        A2[Admin/Owner\napproves request]
        A3[Admin/Owner\nrejects request]
        A4[Admin/Owner\nrevokes access]
    end

    A1 --> E1["📧 Access Request Notification\nSubject: New Access Request - {team}"]
    A2 --> E2["📧 Access Approved\nSubject: Access Approved - {team}"]
    A3 --> E3["📧 Access Rejected\nSubject: Access Request Rejected - {team}"]
    A4 --> E4["📧 Access Revoked\nSubject: Access Revoked - {team}"]

    E1 --> R1[To: All team owners & admins]
    E2 --> R2[To: Requester]
    E3 --> R2
    E4 --> R2

    A1 --> NDA{NDA required?}
    NDA --> |Yes| NDA_STATUS[Shows NDA status\nin notification]
    NDA --> |No| NO_NDA[No NDA info shown]

    style E1 fill:#fef3c7
    style E2 fill:#d1fae5
    style E3 fill:#fee2e2
    style E4 fill:#fee2e2
```

---

## 5. Enterprise Inquiry Email

Triggered by the enterprise contact form. Processed async via Dramatiq task with max 3 retries.

```mermaid
flowchart TD
    subgraph "Contact Form"
        F1[Authenticated user\nsubmits form]
        F2[Public visitor\nsubmits form]
    end

    F1 --> T1[send_enterprise_inquiry_email\nDramatiq task]
    F2 --> T1

    T1 --> E1["📧 Enterprise Inquiry (to Sales)\nSubject: Enterprise Inquiry from {company}"]
    T1 --> E2["📧 Confirmation (to User)\nSubject: Thank you for your Enterprise inquiry"]

    E1 --> R1["To: ENTERPRISE_SALES_EMAIL"]
    E2 --> R2["To: Inquirer's email"]

    F2 --> NOTE["Adds '(Public Form)' to subject\n+ source IP & user agent"]

    style E1 fill:#e0e7ff
    style E2 fill:#d1fae5
```

---

## Sending Mechanisms

| Category | Mechanism | Async | Retry |
|----------|-----------|-------|-------|
| Billing | `send_mail()` via `send_billing_email()` | No (sync in webhook handler) | No |
| Onboarding | `send_mail()` via Dramatiq tasks | Yes | 3 retries |
| Team Invite | `send_mail()` directly in view | No (sync) | No |
| New User Welcome | `send_mail()` in signal handler | No (sync) | No |
| Trust Center Invite | `send_mail()` directly in view | No (sync) | No |
| Document Access | `send_mail()` directly in view/API | No (sync) | No |
| Enterprise Inquiry | `EmailMessage` via Dramatiq task | Yes | 3 retries |

---

## Key Files

| File | Role |
|------|------|
| `core/templates/core/emails/base.html.j2` | Base HTML email template |
| `billing/email_notifications.py` | Billing email sender functions |
| `billing/billing_processing.py` | Stripe webhook handlers (trigger billing emails) |
| `billing/tasks/__init__.py` | Enterprise inquiry Dramatiq task |
| `onboarding/signals.py` | Welcome email trigger (post-signup) |
| `onboarding/cron.py` | Daily drip cron job (9 AM UTC) |
| `onboarding/services/__init__.py` | Onboarding email service (send + eligibility) |
| `onboarding/tasks/__init__.py` | Onboarding Dramatiq tasks |
| `teams/signals.py` | New user welcome email trigger |
| `teams/views/__init__.py` | Team invite email sender |
| `documents/views/access_requests.py` | Document access emails (views) |
| `documents/access_apis.py` | Document access emails (API) |
