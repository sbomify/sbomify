from django import template

register = template.Library()


@register.filter
def hex_to_rgb(hex_color):
    """Convert hex color to RGB string."""
    if not hex_color or not hex_color.startswith("#"):
        return "220, 220, 220"  # Default gray

    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return "220, 220, 220"  # Default gray

    try:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return f"{r}, {g}, {b}"
    except ValueError:
        return "220, 220, 220"  # Default gray


@register.filter
def lighten(hex_color, amount=0.1):
    """Lighten a hex color by a given amount (0.0 to 1.0)."""
    if not hex_color or not hex_color.startswith("#"):
        return hex_color

    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return hex_color

    try:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)

        # Lighten each component
        r = min(255, int(r + (255 - r) * amount))
        g = min(255, int(g + (255 - g) * amount))
        b = min(255, int(b + (255 - b) * amount))

        return f"#{r:02x}{g:02x}{b:02x}"
    except ValueError:
        return hex_color


@register.filter
def darken(hex_color, amount=0.1):
    """Darken a hex color by a given amount (0.0 to 1.0)."""
    if not hex_color or not hex_color.startswith("#"):
        return hex_color

    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return hex_color

    try:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)

        # Darken each component
        r = max(0, int(r * (1 - amount)))
        g = max(0, int(g * (1 - amount)))
        b = max(0, int(b * (1 - amount)))

        return f"#{r:02x}{g:02x}{b:02x}"
    except ValueError:
        return hex_color
