<#import "template.ftl" as layout>
<#import "components.ftl" as components>
<@layout.registrationLayout displayMessage=true displayInfo=false; section>
    <#if section = "header">
        <!-- Header is handled in info panel -->
    <#elseif section = "form">
        <div class="login-split-layout">
            <!-- Left Panel: App Info -->
            <div class="info-panel">
                <div class="info-content">
                    <div class="brand-logo">
                        <img src="${url.resourcesPath}/img/sbomify.svg" alt="sbomify" />
                    </div>
                    <h1 class="info-title">Update Password</h1>
                    <p class="info-tagline">Create a new secure password</p>
                </div>
            </div>

            <!-- Right Panel: Update Password Form -->
            <div class="form-panel">
                <div class="form-card">
                    <h2 class="form-title">Set New Password</h2>

                    <#if message?has_content && (message.type != 'warning' || !isAppInitiatedAction??)>
                        <div class="alert alert-${message.type}" role="alert" aria-live="polite">
                            <#if message.type = 'success'><span class="alert-icon" aria-hidden="true">✓</span></#if>
                            <#if message.type = 'warning'><span class="alert-icon" aria-hidden="true">⚠</span></#if>
                            <#if message.type = 'error'><span class="alert-icon" aria-hidden="true">✕</span></#if>
                            <#if message.type = 'info'><span class="alert-icon" aria-hidden="true">ℹ</span></#if>
                            <span class="alert-text">${kcSanitize(message.summary)}</span>
                        </div>
                    </#if>

                    <form id="kc-update-password-form" action="${url.loginAction}" method="post">
                        <@components.formScripts formId="kc-update-password-form" submittingText="Updating Password..." passwordMatch=true passwordId="password-new" passwordConfirmId="password-confirm" />

                        <#if passwordRequired??>
                            <div class="form-group">
                                <label for="password-new" class="form-label">New Password *</label>
                                <input tabindex="1" type="password" id="password-new" class="form-control" name="password-new" 
                                       autocomplete="new-password" placeholder="Enter your new password"
                                       aria-invalid="<#if messagesPerField.existsError('password-new','password-confirm')>true</#if>"
                                       aria-describedby="<#if messagesPerField.existsError('password-new','password-confirm')>password-new-error</#if>" />
                                <#if messagesPerField.existsError('password-new')>
                                    <span id="password-new-error" class="input-error" role="alert">${kcSanitize(messagesPerField.getFirstError('password-new'))}</span>
                                </#if>
                            </div>

                            <div class="form-group">
                                <label for="password-confirm" class="form-label">Confirm Password *</label>
                                <input tabindex="2" type="password" id="password-confirm" class="form-control" name="password-confirm" 
                                       autocomplete="new-password" placeholder="Confirm your new password"
                                       aria-invalid="<#if messagesPerField.existsError('password-new','password-confirm')>true</#if>"
                                       aria-describedby="<#if messagesPerField.existsError('password-new','password-confirm')>password-confirm-error</#if>" />
                                <#if messagesPerField.existsError('password-confirm')>
                                    <span id="password-confirm-error" class="input-error" role="alert">${kcSanitize(messagesPerField.getFirstError('password-confirm'))}</span>
                                </#if>
                            </div>
                        </#if>

                        <div class="info-message-body">
                            <p>Your new password must be at least 8 characters long.</p>
                            
                            <div class="email-tips">
                                <h3>Password Tips:</h3>
                                <ul>
                                    <li>
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                                        </svg>
                                        <span>Use at least 8 characters</span>
                                    </li>
                                    <li>
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <path d="M5 13l4 4L19 7"/>
                                        </svg>
                                        <span>Mix letters, numbers & symbols</span>
                                    </li>
                                    <li>
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                                        </svg>
                                        <span>Avoid common words & patterns</span>
                                    </li>
                                    <li>
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <path d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>
                                        </svg>
                                        <span>Use different password than before</span>
                                    </li>
                                </ul>
                            </div>
                        </div>

                        <div class="form-actions">
                            <button tabindex="3" type="submit" class="btn-submit" aria-label="Update Password">
                                Update Password
                            </button>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    </#if>
</@layout.registrationLayout>
