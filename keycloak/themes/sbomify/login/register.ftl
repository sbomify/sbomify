<#import "template.ftl" as layout>
<#import "components.ftl" as components>
<@layout.registrationLayout displayMessage=!messagesPerField.existsError('firstName','lastName','email','username','password','password-confirm'); section>
    <#if section = "header">
        <#-- Empty header to hide "Register" title -->
    <#elseif section = "form">
        <div class="login-split-layout">
            <!-- Left Panel: App Info -->
            <div class="info-panel">
                <div class="info-content">
                    <div class="brand-logo">
                        <img src="${url.resourcesPath}/img/sbomify.svg" alt="sbomify" />
                    </div>
                    <h1 class="info-title">Join sbomify Today</h1>
                    <p class="info-tagline">Create your account and start managing your SBOMs in minutes.</p>
                    
                    <div class="features-list">
                        <div class="feature-item">
                            <div class="feature-icon">
                                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
                                </svg>
                            </div>
                            <div class="feature-text">
                                <strong>Free to Start</strong>
                                <span>Get started with our free tier</span>
                            </div>
                        </div>
                        <div class="feature-item">
                            <div class="feature-icon">
                                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                                </svg>
                            </div>
                            <div class="feature-text">
                                <strong>Quick Setup</strong>
                                <span>Be up and running in under 5 minutes</span>
                            </div>
                        </div>
                        <div class="feature-item">
                            <div class="feature-icon">
                                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                                </svg>
                            </div>
                            <div class="feature-text">
                                <strong>Enterprise Security</strong>
                                <span>Your data is protected with industry standards</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Right Panel: Registration Form -->
            <div class="form-panel">
                <div class="form-card">
                    <!-- Mobile Logo (hidden on desktop) -->
                    <div class="mobile-logo">
                        <img src="${url.resourcesPath}/img/sbomify.svg" alt="sbomify" />
                    </div>
                    <h2 class="form-title">Create Account</h2>

                    <#if messagesPerField.existsError('firstName','lastName','email','username','password','password-confirm')>
                        <div class="alert alert-error" role="alert" aria-live="polite">
                            ${kcSanitize(messagesPerField.getFirstError('firstName','lastName','email','username','password','password-confirm'))}
                        </div>
                    </#if>

                    <form id="kc-register-form" action="${url.registrationAction}" method="post">
                        <@components.formScripts formId="kc-register-form" submittingText="Creating Account..." passwordMatch=true passwordId="password" passwordConfirmId="password-confirm" />
                        <div class="form-group">
                            <label for="firstName" class="form-label">First Name *</label>
                            <input tabindex="1" type="text" id="firstName" class="form-control" name="firstName"
                                   value="${(register.formData.firstName!'')}"
                                   autocomplete="given-name" placeholder="Enter your first name"
                                   required
                                   minlength="1"
                                   maxlength="255"
                                   pattern="[A-Za-z\s\-']+"
                                   title="First name is required and should only contain letters, spaces, hyphens, or apostrophes"
                                   aria-invalid="<#if messagesPerField.existsError('firstName')>true</#if>"
                                   aria-describedby="<#if messagesPerField.existsError('firstName')>firstName-error</#if>" />
                            <#if messagesPerField.existsError('firstName')>
                                <span id="firstName-error" class="input-error" role="alert">${kcSanitize(messagesPerField.get('firstName'))}</span>
                            </#if>
                        </div>

                        <div class="form-group">
                            <label for="lastName" class="form-label">Last Name *</label>
                            <input tabindex="2" type="text" id="lastName" class="form-control" name="lastName"
                                   value="${(register.formData.lastName!'')}"
                                   autocomplete="family-name" placeholder="Enter your last name"
                                   required
                                   minlength="1"
                                   maxlength="255"
                                   pattern="[A-Za-z\s\-']+"
                                   title="Last name is required and should only contain letters, spaces, hyphens, or apostrophes"
                                   aria-invalid="<#if messagesPerField.existsError('lastName')>true</#if>"
                                   aria-describedby="<#if messagesPerField.existsError('lastName')>lastName-error</#if>" />
                            <#if messagesPerField.existsError('lastName')>
                                <span id="lastName-error" class="input-error" role="alert">${kcSanitize(messagesPerField.get('lastName'))}</span>
                            </#if>
                        </div>

                        <div class="form-group">
                            <label for="email" class="form-label">Email *</label>
                            <input tabindex="3" type="email" id="email" class="form-control" name="email"
                                   value="${(register.formData.email!'')}"
                                   autocomplete="email" placeholder="Enter your email"
                                   required
                                   maxlength="255"
                                   title="Please enter a valid email address"
                                   aria-invalid="<#if messagesPerField.existsError('email')>true</#if>"
                                   aria-describedby="<#if messagesPerField.existsError('email')>email-error</#if>" />
                            <#if messagesPerField.existsError('email')>
                                <span id="email-error" class="input-error" role="alert">${kcSanitize(messagesPerField.get('email'))}</span>
                            </#if>
                        </div>

                        <#if !realm.registrationEmailAsUsername>
                            <div class="form-group">
                                <label for="username" class="form-label">Username *</label>
                                <input tabindex="4" type="text" id="username" class="form-control" name="username"
                                       value="${(register.formData.username!'')}"
                                       autocomplete="username" placeholder="Choose a username"
                                       required
                                       minlength="3"
                                       maxlength="255"
                                       pattern="[a-zA-Z0-9_\-.]+"
                                       title="Username must be at least 3 characters and can only contain letters, numbers, underscores, hyphens, and periods"
                                       aria-invalid="<#if messagesPerField.existsError('username')>true</#if>"
                                       aria-describedby="<#if messagesPerField.existsError('username')>username-error</#if>" />
                                <#if messagesPerField.existsError('username')>
                                    <span id="username-error" class="input-error" role="alert">${kcSanitize(messagesPerField.get('username'))}</span>
                                </#if>
                            </div>
                        </#if>

                        <#if passwordRequired??>
                            <div class="form-group">
                                <label for="password" class="form-label">Password *</label>
                                <input tabindex="5" type="password" id="password" class="form-control" name="password"
                                       autocomplete="new-password" placeholder="Create a password (min 8 chars)"
                                       required
                                       minlength="8"
                                       maxlength="128"
                                       title="Password must be at least 8 characters long"
                                       aria-invalid="<#if messagesPerField.existsError('password')>true</#if>"
                                       aria-describedby="<#if messagesPerField.existsError('password')>password-error</#if>" />
                                <#if messagesPerField.existsError('password')>
                                    <span id="password-error" class="input-error" role="alert">${kcSanitize(messagesPerField.get('password'))}</span>
                                </#if>
                            </div>

                            <div class="form-group">
                                <label for="password-confirm" class="form-label">Confirm Password *</label>
                                <input tabindex="6" type="password" id="password-confirm" class="form-control" name="password-confirm"
                                       autocomplete="new-password" placeholder="Confirm your password"
                                       required
                                       minlength="8"
                                       maxlength="128"
                                       title="Please confirm your password"
                                       aria-invalid="<#if messagesPerField.existsError('password-confirm')>true</#if>"
                                       aria-describedby="<#if messagesPerField.existsError('password-confirm')>password-confirm-error</#if>" />
                                <#if messagesPerField.existsError('password-confirm')>
                                    <span id="password-confirm-error" class="input-error" role="alert">${kcSanitize(messagesPerField.get('password-confirm'))}</span>
                                </#if>
                            </div>
                        </#if>

                        <#if recaptchaRequired??>
                            <div class="form-group">
                                <div class="g-recaptcha" data-size="compact" data-sitekey="${recaptchaSiteKey}"></div>
                            </div>
                        </#if>

                        <div class="form-actions">
                            <button tabindex="7" type="submit" class="btn-submit" aria-label="Create Account">Create Account</button>
                        </div>
                    </form>

                    <div class="register-link">
                        <span>Already have an account?</span>
                        <a tabindex="8" href="${url.loginUrl}">Log In</a>
                    </div>
                </div>
            </div>
        </div>
    </#if>
</@layout.registrationLayout>
