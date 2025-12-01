# Migration (Vue.js → Django + HTMX + Alpine.js) Guide

## Goal

Fully replace Vue.js with **Django Templates + HTMX + Alpine.js**,
while **preserving UI, behavior, and CSS exactly**.

Frontend logic is minimized. Complexity moves to the server.

---

## Core Rules (Non-Negotiable)

1. **Full migration** — Vue.js must be completely removed; no Vue components remain on the client.
2. **Class-Based Views only** — function-based views are not allowed.
3. **Data access via API / service functions only** — views must not access the ORM directly.
4. **Server-driven data** — data comes from Django Views; no client-side fetch or API calls.
5. **HTMX for dynamic content** — used for rendering partial components and handling form submissions, enabling server-driven updates without full page reloads.
6. **CSS must not change** — scoped styles from Vue are copied as-is.
7. **Alpine.js for component state** — provides lightweight reactivity for managing local state, computed properties, and methods within components.
8. **HTML structure must match Vue** — markup and class names remain identical to preserve UI.

---

## Migration Flow

1. Review the Vue component and its dependencies.
2. Extract scoped CSS to a static file.
3. Copy HTML structure to Django template.
4. Implement CBV using API functions.
5. Port Vue reactivity to Alpine.js (TypeScript file).
6. Register Alpine.js component in `main.ts`.
7. Add HTMX for form submissions and dynamic updates.
8. Verify visual & behavioral parity.
9. Remove Vue component if it's no longer used.

---

## 2. CSS Extraction

**Rule:** Copy `<style scoped>` from Vue component **exactly as-is** to a CSS file.

**Example path:**

* `sbomify/static/css/components/[component-name].css`

**Include in template:**

```django
{% load static %}
<link rel="stylesheet" href="{% static 'css/components/[component-name].css' %}">
```

---

## 3. Template Structure

**Example path:**

* `sbomify/apps/{app}/templates/[component].html.j2`

---

## 4. Django CBV Implementation

**Rules:**

* Class-based views only.
* Use API/service functions for all data access.

**Example path:**

* `sbomify/apps/{app}/views/[component].py`

---

## 5. Alpine.js State Conversion

### 5.1 TypeScript File Structure

**Example path:**

* `sbomify/apps/{app}/js/[component].ts`

### 5.2 State Initialization

**Data is passed via `x-data` in the template:**

```django
<div x-data="alpineDataFunction('{{ data|escapejs }}')">
```

### 5.3 Computed Properties

**Vue:**

```js
const isEmpty = computed(() => !file.value && !existingUrl.value)
```

**Alpine.js:**

```typescript
get isEmpty() {
    return !this.file && !this.existingUrl;
}
```

### 5.4 Component Registration and Connection

**Example:**

* `sbomify/apps/{app}/js/main.ts`

**In Django templates**, connect via `vite_asset` in the `scripts` block:

```django
{% block scripts %}
    {% vite_asset 'sbomify/apps/{app}/js/main.ts' %}
{% endblock %}
```

---

## 6. Forms + HTMX

**Rules:**

* Validation handled by Django Forms.
* Submission via HTMX.
* Client-side behavior via Alpine.js only.
