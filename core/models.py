from django.contrib.auth.models import AbstractUser
from django.db import models

# Import the original models to create proxy models
from sboms.models import (
    Component as SbomComponent,
)
from sboms.models import (
    Product as SbomProduct,
)
from sboms.models import (
    ProductProject as SbomProductProject,
)
from sboms.models import (
    Project as SbomProject,
)
from sboms.models import (
    ProjectComponent as SbomProjectComponent,
)


class User(AbstractUser):
    """Custom user model."""

    email_verified = models.BooleanField(default=False)
    """Whether the user's email has been verified."""

    class Meta:
        db_table = "core_users"


# Proxy models for sbom entities - provides clean core app interface
# while keeping data in original sbom tables for backward compatibility


class Product(SbomProduct):
    """Proxy model for sboms.Product - moved to core app for better organization."""

    class Meta:
        proxy = True
        app_label = "core"


class Project(SbomProject):
    """Proxy model for sboms.Project - moved to core app for better organization."""

    class Meta:
        proxy = True
        app_label = "core"


class Component(SbomComponent):
    """Proxy model for sboms.Component - moved to core app for better organization."""

    class Meta:
        proxy = True
        app_label = "core"


class ProductProject(SbomProductProject):
    """Proxy model for sboms.ProductProject - moved to core app for better organization."""

    class Meta:
        proxy = True
        app_label = "core"


class ProjectComponent(SbomProjectComponent):
    """Proxy model for sboms.ProjectComponent - moved to core app for better organization."""

    class Meta:
        proxy = True
        app_label = "core"
