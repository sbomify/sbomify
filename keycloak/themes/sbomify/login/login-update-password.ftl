<#--
  The "set a new password" form, reached from a reset link or a required action.
  Keycloak resolves this page by filename, so the name is fixed:
  login-update-password.ftl.

  Two details come from the base theme and must not drift: field errors are keyed
  on 'password' (not 'password-new'), and an app-initiated action needs its own
  cancel button, otherwise the user is trapped on the page.
-->
<#import "template.ftl" as layout>
<#import "components.ftl" as components>
<@layout.registrationLayout displayMessage=!messagesPerField.existsError('password','password-confirm'); section>
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
                    <h1 class="info-title">Set a new password</h1>
                    <p class="info-tagline">Choose one you don't use anywhere else.</p>
                </div>
            </div>

            <!-- Right Panel: Update Password Form -->
            <div class="form-panel">
                <div class="form-card">
                    <!-- Mobile Logo (hidden on desktop) -->
                    <div class="mobile-logo">
                        <@components.brandLogo />
                    </div>
                    <h2 class="form-title">Set a new password</h2>

                    <@components.alertBanner />

                    <form id="kc-passwd-update-form" action="${url.loginAction}" method="post">
                        <@components.formScripts formId="kc-passwd-update-form" submittingText="Saving..." passwordMatch=true passwordId="password-new" passwordConfirmId="password-confirm" />

                        <div class="form-group">
                            <label for="password-new" class="form-label">New password *</label>
                            <input tabindex="1" type="password" id="password-new" class="form-control" name="password-new"
                                   autocomplete="new-password"
                                   autofocus
                                   required
                                   minlength="8"
                                   maxlength="128"
                                   title="Use at least 8 characters"
                                   aria-invalid="<#if messagesPerField.existsError('password','password-confirm')>true<#else>false</#if>"
                                   aria-describedby="password-tips<#if messagesPerField.existsError('password')> password-new-error</#if>" />
                            <#if messagesPerField.existsError('password')>
                                <span id="password-new-error" class="input-error" aria-live="polite" role="alert">${kcSanitize(messagesPerField.get('password'))?no_esc}</span>
                            </#if>
                        </div>

                        <div class="form-group">
                            <label for="password-confirm" class="form-label">Confirm new password *</label>
                            <input tabindex="2" type="password" id="password-confirm" class="form-control" name="password-confirm"
                                   autocomplete="new-password"
                                   required
                                   minlength="8"
                                   maxlength="128"
                                   title="Type the same password again"
                                   aria-invalid="<#if messagesPerField.existsError('password-confirm')>true<#else>false</#if>"
                                   <#if messagesPerField.existsError('password-confirm')>aria-describedby="password-confirm-error"</#if> />
                            <#if messagesPerField.existsError('password-confirm')>
                                <span id="password-confirm-error" class="input-error" aria-live="polite" role="alert">${kcSanitize(messagesPerField.get('password-confirm'))?no_esc}</span>
                            </#if>
                        </div>

                        <div id="password-tips" class="email-tips">
                            <h3>A good password</h3>
                            <ul>
                                <li>
                                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                        <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                                    </svg>
                                    <span>Is at least 8 characters</span>
                                </li>
                                <li>
                                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                        <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                                    </svg>
                                    <span>Mixes letters, numbers and symbols</span>
                                </li>
                                <li>
                                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                        <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                                    </svg>
                                    <span>Is not one you use elsewhere</span>
                                </li>
                            </ul>
                        </div>

                        <div class="checkbox-row mt-5">
                            <input tabindex="3" type="checkbox" id="logout-sessions" name="logout-sessions" value="on" checked>
                            <label for="logout-sessions">${msg("logoutOtherSessions")}</label>
                        </div>

                        <div class="form-actions">
                            <button tabindex="4" type="submit" name="login" class="btn-submit">
                                Update password
                            </button>
                            <#if isAppInitiatedAction??>
                                <button tabindex="5" type="submit" name="cancel-aia" value="true" class="btn-skip mt-3">
                                    ${msg("doCancel")}
                                </button>
                            </#if>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    </#if>
</@layout.registrationLayout>
