from django.contrib import admin

from sbomify.apps.controls.models import Control, ControlCatalog, ControlStatus

admin.site.register(ControlCatalog)
admin.site.register(Control)
admin.site.register(ControlStatus)
