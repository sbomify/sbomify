<#import "template.ftl" as layout>
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
                    <h1 class="info-title">Reset Password</h1>
                    <p class="info-tagline">Securely recover your account access</p>
                </div>
            </div>

            <!-- Right Panel: Forgot Password Form -->
            <div class="form-panel">
                <div class="form-card">
                    <h2 class="form-title">Forgot Password?</h2>

                    <#if message?has_content && (message.type != 'warning' || !isAppInitiatedAction??)>
                        <div class="alert alert-${message.type}" role="alert" aria-live="polite">
                            <#if message.type = 'success'><span class="alert-icon" aria-hidden="true">✓</span></#if>
                            <#if message.type = 'warning'><span class="alert-icon" aria-hidden="true">⚠</span></#if>
                            <#if message.type = 'error'><span class="alert-icon" aria-hidden="true">✕</span></#if>
                            <#if message.type = 'info'><span class="alert-icon" aria-hidden="true">ℹ</span></#if>
                            <span class="alert-text">${kcSanitize(message.summary)}</span>
                        </div>
                    </#if>

                    <#if realm.duplicateEmailsAllowed>
                        <div class="info-notice mb-5">
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <circle cx="12" cy="12" r="10"></circle>
                                <path d="M12 8v4M12 16h.01"></path>
                            </svg>
                            <span>
                                <strong>Multiple accounts?</strong> 
                                Enter all your email addresses to receive recovery instructions.
                            </span>
                        </div>
                    </#if>

                    <form id="kc-reset-password-form" action="${url.loginResetCredentialsUrl}" method="post">
                        <script>
                            document.getElementById('kc-reset-password-form').addEventListener('submit', function(e) {
                                const submitBtn = this.querySelector('button[type="submit"]');
                                if (submitBtn) {
                                    submitBtn.disabled = true;
                                    submitBtn.innerHTML = 'Sending Instructions...';
                                }
                            });
                            
                            // Add floating label animation
                            document.querySelectorAll('.form-control').forEach(input => {
                                const label = input.previousElementSibling;
                                if (label && label.classList.contains('form-label')) {
                                    input.addEventListener('focus', () => {
                                        label.classList.add('focused');
                                    });
                                    input.addEventListener('blur', () => {
                                        if (!input.value) {
                                            label.classList.remove('focused');
                                        }
                                    });
                                    if (input.value) {
                                        label.classList.add('focused');
                                    }
                                }
                            });
                        </script>

                        <#if realm.loginWithEmailAllowed>
                            <#if !realm.duplicateEmailsAllowed>
                                <div class="form-group">
                                    <label for="username" class="form-label">
                                        <#if !realm.loginWithEmailAllowed>${msg("username")}<#elseif !realm.registrationEmailAsUsername>${msg("usernameOrEmail")}<#else>${msg("email")}</#if>
                                    </label>
                                    <input tabindex="1" id="username" class="form-control" name="username" 
                                           value="${(username!'')}" type="text" autocomplete="username"
                                           placeholder="Enter your username or email"
                                           aria-invalid="<#if messagesPerField.existsError('username')>true</#if>"
                                           aria-describedby="<#if messagesPerField.existsError('username')>username-error</#if>" />
                                    <#if messagesPerField.existsError('username')>
                                        <span id="username-error" class="input-error" role="alert">${kcSanitize(messagesPerField.getFirstError('username'))}</span>
                                    </#if>
                                </div>
                            <#else>
                                <div class="form-group">
                                    <label for="username" class="form-label">${msg("email")}</label>
                                    <input tabindex="1" id="username" class="form-control" name="username" 
                                           value="${(username!'')}" type="text" autocomplete="username"
                                           placeholder="Enter your email address"
                                           aria-invalid="<#if messagesPerField.existsError('username')>true</#if>"
                                           aria-describedby="<#if messagesPerField.existsError('username')>username-error</#if>" />
                                    <#if messagesPerField.existsError('username')>
                                        <span id="username-error" class="input-error" role="alert">${kcSanitize(messagesPerField.getFirstError('username'))}</span>
                                    </#if>
                                </div>
                            </#if>
                        <#else>
                            <div class="form-group">
                                <label for="username" class="form-label">${msg("username")}</label>
                                <input tabindex="1" id="username" class="form-control" name="username" 
                                       value="${(username!'')}" type="text" autocomplete="username"
                                       placeholder="Enter your username"
                                       aria-invalid="<#if messagesPerField.existsError('username')>true</#if>"
                                       aria-describedby="<#if messagesPerField.existsError('username')>username-error</#if>" />
                                <#if messagesPerField.existsError('username')>
                                    <span id="username-error" class="input-error" role="alert">${kcSanitize(messagesPerField.getFirstError('username'))}</span>
                                </#if>
                            </div>
                        </#if>

                        <div class="info-message-body">
                            <p>We'll send you instructions to reset your password.</p>
                            
                            <div class="email-tips">
                                <h3>What happens next:</h3>
                                <ul>
                                    <li>
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <path d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
                                        </svg>
                                        <span>You'll receive a reset link via email</span>
                                    </li>
                                    <li>
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
                                        </svg>
                                        <span>Link will expire in a few hours</span>
                                    </li>
                                    <li>
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                                        </svg>
                                        <span>Follow link to create a new password</span>
                                    </li>
                                </ul>
                            </div>
                        </div>

                        <div class="form-actions">
                            <button tabindex="2" type="submit" class="btn-submit" aria-label="Send Reset Instructions">
                                Send Reset Instructions
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
