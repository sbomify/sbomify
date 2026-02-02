<#import "template.ftl" as layout>
<#import "components.ftl" as components>
<@layout.registrationLayout displayMessage=true displayInfo=false; section>
    <#if section = "header">
        <!-- Header is handled in the info panel -->
    <#elseif section = "form">
        <div class="login-split-layout">
            <!-- Left Panel: App Info -->
            <div class="info-panel">
                <div class="info-content">
                    <div class="brand-logo">
                        <img src="${url.resourcesPath}/img/sbomify.svg" alt="sbomify" />
                    </div>
                    <h1 class="info-title">Recover Username</h1>
                    <p class="info-tagline">Find your account using email</p>
                </div>
            </div>

            <!-- Right Panel: Username Recovery Form -->
            <div class="form-panel">
                <div class="form-card">
                    <!-- Mobile Logo (hidden on desktop) -->
                    <div class="mobile-logo">
                        <img src="${url.resourcesPath}/img/sbomify.svg" alt="sbomify" />
                    </div>
                    <h2 class="form-title">Forgot Your Username?</h2>

                    <#if message?has_content && (message.type != 'warning' || !isAppInitiatedAction??)>
                        <div class="alert alert-${message.type}" role="alert" aria-live="polite">
                            <#if message.type = 'success'><span class="alert-icon" aria-hidden="true">✓</span></#if>
                            <#if message.type = 'warning'><span class="alert-icon" aria-hidden="true">⚠</span></#if>
                            <#if message.type = 'error'><span class="alert-icon" aria-hidden="true">✕</span></#if>
                            <#if message.type = 'info'><span class="alert-icon" aria-hidden="true">ℹ</span></#if>
                            <span class="alert-text">${kcSanitize(message.summary)}</span>
                        </div>
                    </#if>

                    <form id="kc-recover-username-form" action="${url.loginAction}" method="post">
                        <@components.formScripts formId="kc-recover-username-form" submittingText="Finding Username..." />

                        <#if realm.registrationEmailAsUsername>
                            <div class="form-group">
                                <label for="email" class="form-label">Email *</label>
                                <input tabindex="1" type="email" id="email" class="form-control" name="email"
                                       value="${(email!'')}" autocomplete="email"
                                       required
                                       placeholder="Enter your email address"
                                       title="Please enter a valid email address"
                                       aria-invalid="<#if messagesPerField.existsError('email')>true</#if>"
                                       aria-describedby="<#if messagesPerField.existsError('email')>email-error</#if>" />
                                <#if messagesPerField.existsError('email')>
                                    <span id="email-error" class="input-error" role="alert">${kcSanitize(messagesPerField.getFirstError('email'))}</span>
                                </#if>
                            </div>
                        <#else>
                            <div class="form-group">
                                <label for="email" class="form-label">Email *</label>
                                <input tabindex="1" type="email" id="email" class="form-control" name="email"
                                       value="${(email!'')}" autocomplete="email"
                                       required
                                       placeholder="Enter your email address"
                                       title="Please enter a valid email address"
                                       aria-invalid="<#if messagesPerField.existsError('email')>true</#if>"
                                       aria-describedby="<#if messagesPerField.existsError('email')>email-error</#if>" />
                                <#if messagesPerField.existsError('email')>
                                    <span id="email-error" class="input-error" role="alert">${kcSanitize(messagesPerField.getFirstError('email'))}</span>
                                </#if>
                            </div>
                        </#if>

                        <div class="info-message-body">
                            <p>We'll send you an email with your username.</p>
                            
                            <div class="email-tips">
                                <h3>What happens:</h3>
                                <ul>
                                    <li>
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <path d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
                                        </svg>
                                        <span>Email with username will be sent</span>
                                    </li>
                                    <li>
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                                        </svg>
                                        <span>Link expires in a few hours</span>
                                    </li>
                                    <li>
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
                                        </svg>
                                        <span>Return here to log in</span>
                                    </li>
                                </ul>
                            </div>
                        </div>

                        <div class="form-actions">
                            <button tabindex="2" type="submit" class="btn-submit" aria-label="Find Username">
                                Find My Username
                            </button>
                        </div>
                    </form>

                    <div class="form-links">
                        <div class="login-link">
                            <span>Remember your username?</span>
                            <a href="${url.loginUrl}">${msg("doLogIn")}</a>
                        </div>

                        <#if realm.password && realm.registrationAllowed && !registrationDisabled??>
                            <div class="register-link">
                                <span>Don't have an account?</span>
                                <a href="${url.registrationUrl}">${msg("doRegister")}</a>
                            </div>
                        </#if>
                    </div>
                </div>
            </div>
        </div>
    </#if>
</@layout.registrationLayout>
