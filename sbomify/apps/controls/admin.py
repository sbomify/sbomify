from sbomify.apps.controls.models import Control, ControlCatalog, ControlStatus
from sbomify.apps.core.admin import admin_site

admin_site.register(ControlCatalog)
admin_site.register(Control)
admin_site.register(ControlStatus)
