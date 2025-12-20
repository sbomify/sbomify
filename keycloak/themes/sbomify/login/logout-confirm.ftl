<#import "template.ftl" as layout>
<@layout.registrationLayout; section>
    <#if section = "header">
        <#-- Empty header -->
    <#elseif section = "form">
        <#-- Auto-submit logout form to skip confirmation page -->
        <form id="kc-logout-form" action="${url.logoutConfirmAction}" method="POST" style="display:none;">
            <input type="hidden" name="session_code" value="${logoutConfirm.code}">
            <input type="hidden" name="confirmLogout" value="true">
        </form>
        <script>
            document.getElementById('kc-logout-form').submit();
        </script>
        <#-- Fallback message in case JS is disabled -->
        <noscript>
            <div class="login-split-layout">
                <div class="form-panel">
                    <div class="form-card">
                        <p>Logging out...</p>
                        <form action="${url.logoutConfirmAction}" method="POST">
                            <input type="hidden" name="session_code" value="${logoutConfirm.code}">
                            <button class="btn-submit" name="confirmLogout" type="submit">
                                Click here to logout
                            </button>
                        </form>
                    </div>
                </div>
            </div>
        </noscript>
    </#if>
</@layout.registrationLayout>
