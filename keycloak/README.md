# SBOMify Keycloak Theme

A modern, professional Keycloak authentication theme for SBOMify application.

## Features

- **Modern Two-Column Layout**: Consistent branding left panel with form/info right panel
- **Responsive Design**: Optimized for desktop, tablet, and mobile devices
- **Smooth Animations**: Staggered entrance animations, hover effects, and micro-interactions
- **Professional Styling**: Glassmorphism cards, gradient backgrounds, and polished UI components
- **Accessibility**: ARIA labels, keyboard navigation, and screen reader support
- **Brand Consistency**: Matches SBOMify application's color scheme and design language

## Theme Structure

```text
themes/sbomify/
├── login/
│   ├── theme.properties           # Theme configuration
│   ├── template.ftl              # Base layout template
│   ├── messages/                 # Message bundles
│   │   └── Messages.properties   # Custom messages (English)
│   ├── login.ftl                # Login page
│   ├── register.ftl              # Registration page
│   ├── forgot-password.ftl        # Forgot password page
│   ├── update-password.ftl        # Update password page
│   ├── login-username.ftl        # Forgot username page
│   ├── verify-email.ftl          # Email verification page
│   ├── update-email.ftl          # Email update page
│   ├── info.ftl                  # Generic info page
│   ├── login-config.ftl          # Required actions page
│   ├── terms.ftl                 # Terms of service page
│   ├── logout-confirm.ftl        # Logout confirmation
│   └── resources/
│       ├── css/
│       │   ├── sbomify.src.css   # Tailwind CSS source
│       │   └── sbomify.css       # Compiled CSS
│       └── img/
│           └── sbomify.svg        # Logo
└── theme.properties              # Parent theme properties
```

## Pages Overview

### Authentication Pages

1. **Login Page** (`login.ftl`)
   - Username/email and password fields
   - Remember me checkbox
   - Forgot password link
   - Social login providers (if configured)
   - Register account link

2. **Register Page** (`register.ftl`)
   - First name, last name, email fields
   - Username field (if not using email as username)
   - Password and confirm password fields
   - Feature highlights on left panel

3. **Forgot Password** (`forgot-password.ftl`)
   - Email/username input field
   - Clear process explanation with steps
   - Back to login and register links
   - Multiple email notice (if configured)

4. **Update Password** (`update-password.ftl`)
   - New password field
   - Confirm password field
   - Real-time validation
   - Password strength tips

5. **Forgot Username** (`login-username.ftl`)
   - Email input field
   - Username recovery process
   - Navigation links

### Information Pages

1. **Verify Email** (`verify-email.ftl`)
   - Large email icon
   - Step-by-step instructions
   - Expiration warning
   - Visual tips with icons

2. **Update Email** (`update-email.ftl`)
   - Email update confirmation
   - Process steps
   - Clear expectations

3. **Info Page** (`info.ftl`)
   - Generic information display
   - Supports messages and alerts
   - Required actions display

4. **Login Config** (`login-config.ftl`)
   - Required authentication actions
   - Checklist style with icons
   - Multiple action support

5. **Terms Page** (`terms.ftl`)
   - Document icon
   - Key points with icons
   - Accept button
   - Cancel/back link

6. **Logout Confirm** (`logout-confirm.ftl`)
   - Auto-submit logout
   - Fallback for no-JS

## Design System

### Colors

```css
--sbomify-brand: #3b7ddd;          /* Primary blue */
--sbomify-brand-hover: #2f64b1;     /* Darker blue for hover */
--sbomify-success: #1cbb8c;         /* Green */
--sbomify-warning: #fcb92c;         /* Amber */
--sbomify-danger: #dc3545;           /* Red */
--sbomify-surface-dark: #111a2d;     /* Dark background */
--sbomify-surface-card: rgba(14, 22, 38, 0.94);  /* Glass card */
--sbomify-contrast: #f8fafc;        /* White text */
--sbomify-muted: #94a3b8;           /* Gray text */
```

### Typography

- **Font Family**: Inter, Helvetica Neue, Arial, sans-serif
- **Heading Sizes**: text-4xl (36px), text-2xl (24px), text-xl (20px)
- **Body Sizes**: text-base (16px), text-sm (14px), text-xs (12px)
- **Weights**: Regular (400), Medium (500), Semibold (600), Bold (700)

### Animations

- **fadeInBackground**: 0.8s ease-out (page load)
- **scaleIn**: 0.5s ease-out (icon appearance)
- **slideInUp**: 0.5s ease-out (content rise)
- **slideInLeft**: 0.6s ease-out (left panel)
- **slideInRight**: 0.6s ease-out (right panel)
- **shake**: 0.4s ease-in-out (error feedback)

### Component Styles

- **Buttons**: Multi-step gradient, shimmer effect, hover lift
- **Inputs**: Glow focus, slide animations, error states
- **Cards**: Glassmorphism with backdrop blur
- **Alerts**: Color-coded with icons and shadows
- **Links**: Animated underlines, hover colors

## Building the Theme

### Development Mode

```bash
cd keycloak
bun run dev
```

This watches for changes and recompiles CSS automatically.

### Production Build

```bash
cd keycloak
bun run build
```

This compiles and minifies CSS for production.

## Deployment

The theme is automatically deployed in the development environment via Docker Compose:

```yaml
keycloak:
  volumes:
    - ./keycloak/themes:/opt/keycloak/themes:ro
```

Keycloak uses the theme specified in `theme.properties`:

- `parent=keycloak` - Inherits base Keycloak styling
- `loginTheme=sbomify` - Applied via Keycloak bootstrap script

## Customization

### Modifying Styles

1. Edit `login/resources/css/sbomify.src.css`
2. Run `bun run dev` (watch mode) or `bun run build` (production)
3. Changes automatically compile to `sbomify.css`

### Modifying Templates

1. Edit any `.ftl` template in `login/` directory
2. Changes are picked up on container restart
3. No compilation needed

### Updating Branding

1. Replace `login/resources/img/sbomify.svg` with your logo
2. Update CSS color variables in `.src.css`
3. Rebuild CSS with `bun run build`

### Custom Messages

Edit `login/messages/Messages.properties` to override default Keycloak messages.

## Browser Support

- Modern browsers (Chrome, Firefox, Safari, Edge)
- CSS Grid and Flexbox
- CSS Custom Properties
- Backdrop Filter (glassmorphism)
- Reduced motion support

## Accessibility

- WCAG 2.1 AA compliant
- Semantic HTML structure
- ARIA labels and live regions
- Keyboard navigation support
- Screen reader friendly
- Focus indicators
- Sufficient color contrast

## Performance

- GPU-accelerated animations (transform, opacity)
- Minimal repaints and reflows
- Optimized CSS selectors
- Minified production CSS
- Efficient keyframe animations

## License

This theme follows the SBOMify project license.
