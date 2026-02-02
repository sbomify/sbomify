<#import "template.ftl" as layout>
<#import "components.ftl" as components>
<@layout.registrationLayout displayMessage=!messagesPerField.existsError('username','password') displayInfo=realm.password && realm.registrationAllowed && !registrationDisabled??; section>
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
                    <h1 class="info-title">Sign in to sbomify</h1>
                    <p class="info-tagline">Manage your SBOMs and compliance documents in one place.</p>
                </div>
            </div>

            <!-- Right Panel: Login Form -->
            <div class="form-panel">
                <div class="form-card">
                    <!-- Mobile Logo (hidden on desktop) -->
                    <div class="mobile-logo">
                        <img src="${url.resourcesPath}/img/sbomify.svg" alt="sbomify" />
                    </div>
                    <h2 class="form-title">${msg("loginAccountTitle")}</h2>
                    
                    <#if message?has_content && (message.type != 'warning' || !isAppInitiatedAction??)>
                        <div class="alert alert-${message.type}" role="alert" aria-live="polite">
                            <#if message.type = 'success'><span class="alert-icon" aria-hidden="true">✓</span></#if>
                            <#if message.type = 'warning'><span class="alert-icon" aria-hidden="true">⚠</span></#if>
                            <#if message.type = 'error'><span class="alert-icon" aria-hidden="true">✕</span></#if>
                            <#if message.type = 'info'><span class="alert-icon" aria-hidden="true">ℹ</span></#if>
                            <span class="alert-text">${kcSanitize(message.summary)}</span>
                        </div>
                    </#if>

                    <form id="kc-form-login" action="${url.loginAction}" method="post">
                        <@components.formScripts formId="kc-form-login" submittingText="Signing in..." />
                        <div class="form-group">
                            <label for="username" class="form-label">
                                <#if !realm.loginWithEmailAllowed>${msg("username")} *<#elseif !realm.registrationEmailAsUsername>${msg("usernameOrEmail")} *<#else>${msg("email")} *</#if>
                            </label>
                            <input tabindex="1" id="username" class="form-control" name="username" value="${(login.username!'')}"
                                   type="<#if realm.loginWithEmailAllowed && realm.registrationEmailAsUsername>email<#else>text</#if>"
                                   autofocus autocomplete="username"
                                   required
                                   minlength="3"
                                   placeholder="<#if !realm.loginWithEmailAllowed>Enter your username<#elseif !realm.registrationEmailAsUsername>Enter your username or email<#else>Enter your email</#if>"
                                   title="<#if !realm.loginWithEmailAllowed>Username is required<#elseif !realm.registrationEmailAsUsername>Username or email is required<#else>Email is required</#if>"
                                   aria-invalid="<#if messagesPerField.existsError('username','password')>true</#if>"
                                   aria-describedby="<#if messagesPerField.existsError('username','password')>username-error</#if>" />
                            <#if messagesPerField.existsError('username','password')>
                                <span id="username-error" class="input-error" aria-live="polite" role="alert">${kcSanitize(messagesPerField.getFirstError('username','password'))}</span>
                            </#if>
                        </div>

                        <div class="form-group">
                            <label for="password" class="form-label">${msg("password")} *</label>
                            <input tabindex="2" id="password" class="form-control" name="password" type="password" autocomplete="current-password"
                                   required
                                   minlength="1"
                                   placeholder="Enter your password"
                                   title="Password is required"
                                   aria-invalid="<#if messagesPerField.existsError('username','password')>true</#if>"
                                   aria-describedby="<#if messagesPerField.existsError('username','password')>username-error</#if>" />
                        </div>

                        <div class="form-options">
                            <#if realm.rememberMe && !usernameHidden??>
                                <div class="remember-me">
                                    <input tabindex="3" id="rememberMe" name="rememberMe" type="checkbox" <#if login.rememberMe??>checked</#if>>
                                    <label for="rememberMe">${msg("rememberMe")}</label>
                                </div>
                            </#if>
                            <#if realm.resetPasswordAllowed>
                                <a tabindex="5" href="${url.loginResetCredentialsUrl}" class="forgot-password">${msg("doForgotPassword")}</a>
                            </#if>
                        </div>

                        <div class="form-actions">
                            <input type="hidden" id="id-hidden-input" name="credentialId" <#if auth.selectedCredential?has_content>value="${auth.selectedCredential}"</#if>/>
                            <button tabindex="4" class="btn-submit" name="login" id="kc-login" type="submit" aria-label="${msg("doLogIn")}">
                                ${msg("doLogIn")}
                            </button>
                        </div>
                    </form>

                    <#if social?? && social.providers?? && social.providers?has_content>
                        <div class="social-divider">
                            <span>or continue with</span>
                        </div>
                        <div class="social-providers">
                            <#list social.providers as p>
                                <a id="social-${p.alias}" class="social-btn" href="${p.loginUrl}" aria-label="${msg("doLogIn")} ${kcSanitize(p.displayName!p.alias)}">
                                    <#if p.iconClasses?has_content><i class="${p.iconClasses}" aria-hidden="true"></i></#if>
                                    <span>${kcSanitize(p.displayName!p.alias)}</span>
                                </a>
                            </#list>
                        </div>
                    </#if>

                    <#if realm.password && realm.registrationAllowed && !registrationDisabled??>
                        <div class="register-link">
                            <span>${msg("noAccount")}</span>
                            <a href="${url.registrationUrl}">${msg("doRegister")}</a>
                        </div>
                    </#if>
                </div>
            </div>
        </div>
    <#elseif section = "socialProviders">
        <#if social?? && social.providers?? && social.providers?has_content>
            <div class="social-providers-section">
                <#list social.providers as p>
                    <a id="social-${p.alias}" class="social-btn" href="${p.loginUrl}" aria-label="${msg("doLogIn")} ${kcSanitize(p.displayName!p.alias)}">
                        <#if p.iconClasses?has_content><i class="${p.iconClasses}" aria-hidden="true"></i></#if>
                        <span>${kcSanitize(p.displayName!p.alias)}</span>
                    </a>
                </#list>
            </div>
        </#if>
    </#if>
</@layout.registrationLayout>
