---
trigger: always_on
---

Use "uv run" to run any python related cmds and tests
use "uv run pytest -n auto" if you want to run all the test.

- Class-Based Views only — function-based views are not allowed.
- Data access via API / service functions only — views must not access the ORM directly.
- Server-driven data — data comes from Django Views; no client-side fetch or API calls.
- HTMX for dynamic content — used for rendering partial components and handling form submissions, enabling server-driven updates without full page reloads.
- Alpine.js for component state — provides lightweight reactivity for managing local state, computed properties, and methods within components.
- Validation handled by Django Forms.
- Submission via HTMX.
- Client-side behavior via Alpine.js only.
- Avoid adding unnecessary code comments and logs.

- For github operation use gh cmd line tool

Note: Application is running on the docker. If there is the change is the css specifically run the following cmd

- bun run copy-deps && bun x vite build
- uv run python manage.py collectstatic --noinput
And restart the container.
