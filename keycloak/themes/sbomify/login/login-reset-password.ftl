<#--
  The "forgot password" form. Keycloak resolves this page by filename, so the
  name is fixed: login-reset-password.ftl. The form posts to url.loginAction and
  the field is prefilled from auth.attemptedUsername, both per the base theme.
-->
<#import "template.ftl" as layout>
<#import "components.ftl" as components>
<@layout.registrationLayout displayInfo=false displayMessage=!messagesPerField.existsError('username'); section>
    <#if section = "header">
        <#-- The heading lives in the card, so this section stays empty. -->
    <#elseif section = "form">
        <div class="login-split-layout">
            <!-- Left Panel: App Info -->
            <div class="info-panel">
                <div class="info-content">
                    <div class="brand-logo">
                        <@components.brandLogo />
                    </div>
                    <h1 class="info-title">Reset your password</h1>
                    <p class="info-tagline">We'll email you a link to set a new one.</p>
                </div>
            </div>

            <!-- Right Panel: Reset Form -->
            <div class="form-panel">
                <div class="form-card">
                    <!-- Mobile Logo (hidden on desktop) -->
                    <div class="mobile-logo">
                        <@components.brandLogo />
                    </div>
                    <h2 class="form-title">Forgot your password?</h2>

                    <@components.alertBanner />

                    <form id="kc-reset-password-form" action="${url.loginAction}" method="post">
                        <@components.formScripts formId="kc-reset-password-form" submittingText="Sending..." />

                        <div class="form-group">
                            <label for="username" class="form-label">
                                <#if !realm.loginWithEmailAllowed>${msg("username")}<#elseif !realm.registrationEmailAsUsername>${msg("usernameOrEmail")}<#else>${msg("email")}</#if> *
                            </label>
                            <input tabindex="1" id="username" class="form-control" name="username"
                                   type="text" dir="ltr"
                                   value="${(auth.attemptedUsername!'')}"
                                   autocomplete="username"
                                   autofocus
                                   required
                                   aria-invalid="<#if messagesPerField.existsError('username')>true<#else>false</#if>"
                                   aria-describedby="reset-hint<#if messagesPerField.existsError('username')> username-error</#if>" />
                            <#if messagesPerField.existsError('username')>
                                <span id="username-error" class="input-error" aria-live="polite" role="alert">${kcSanitize(messagesPerField.get('username'))?no_esc}</span>
                            </#if>
                        </div>

                        <div class="info-message-body">
                            <p id="reset-hint">We'll email you a link to set a new password. It expires in a few hours.</p>
                        </div>

                        <#if realm.duplicateEmailsAllowed>
                            <div class="info-notice">
                                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <circle cx="12" cy="12" r="10"></circle>
                                    <path d="M12 8v4M12 16h.01"></path>
                                </svg>
                                <span>
                                    <strong>More than one account?</strong>
                                    Enter your username instead. One email address can cover several accounts.
                                </span>
                            </div>
                        </#if>

                        <div class="form-actions">
                            <button tabindex="2" type="submit" class="btn-submit">
                                Send reset link
                            </button>
                        </div>
                    </form>

                    <div class="form-links">
                        <div class="login-link">
                            <span>Remember your password?</span>
                            <a href="${url.loginUrl}">${msg("doLogIn")}</a>
                        </div>

                        <#if realm.password && realm.registrationAllowed && !registrationDisabled??>
                            <div class="register-link">
                                <span>${msg("noAccount")}</span>
                                <a href="${url.registrationUrl}">${msg("doRegister")}</a>
                            </div>
                        </#if>
                    </div>
                </div>
            </div>
        </div>
    </#if>
</@layout.registrationLayout>
