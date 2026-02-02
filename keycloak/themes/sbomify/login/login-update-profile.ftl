<#import "template.ftl" as layout>
<#import "components.ftl" as components>
<@layout.registrationLayout displayMessage=!messagesPerField.existsError('username','email','firstName','lastName'); section>
    <#if section = "header">
        ${msg("loginProfileTitle")}
    <#elseif section = "form">
        <div class="login-split-layout">
            <!-- Left Panel: Branding -->
            <div class="info-panel">
                <div class="info-content">
                    <div class="brand-logo">
                        <img src="${url.resourcesPath}/img/sbomify.svg" alt="sbomify" />
                    </div>
                    <h1 class="info-title">Update Your Profile</h1>
                    <p class="info-tagline">Please update your account information to continue.</p>
                </div>
            </div>

            <!-- Right Panel: Form -->
            <div class="form-panel">
                <div class="form-card">
                    <!-- Mobile Logo (hidden on desktop) -->
                    <div class="mobile-logo">
                        <img src="${url.resourcesPath}/img/sbomify.svg" alt="sbomify" />
                    </div>
                    <h2 class="form-title">Complete Profile</h2>

                    <form id="kc-update-profile-form" class="login-form" action="${url.loginAction}" method="post">
                        <@components.formScripts formId="kc-update-profile-form" submittingText="Updating..." />
                        <#if user.editUsernameAllowed>
                            <div class="form-group">
                                <label for="username" class="form-label">${msg("username")} *</label>
                                <input type="text" id="username" name="username" value="${(user.username!'')}" class="form-control" autocomplete="username"
                                       required
                                       minlength="3"
                                       maxlength="255"
                                       placeholder="Enter your username"
                                       title="Username is required"
                                       aria-invalid="<#if messagesPerField.existsError('username')>true</#if>"
                                       aria-describedby="<#if messagesPerField.existsError('username')>username-error</#if>" />
                                <#if messagesPerField.existsError('username')>
                                    <span id="username-error" class="input-error" role="alert">${kcSanitize(messagesPerField.getFirstError('username'))}</span>
                                </#if>
                            </div>
                        </#if>

                        <div class="form-group">
                            <label for="email" class="form-label">${msg("email")} *</label>
                            <input type="email" id="email" name="email" value="${(user.email!'')}" class="form-control" autocomplete="email"
                                   required
                                   maxlength="255"
                                   placeholder="Enter your email"
                                   title="Please enter a valid email address"
                                   aria-invalid="<#if messagesPerField.existsError('email')>true</#if>"
                                   aria-describedby="<#if messagesPerField.existsError('email')>email-error</#if>" />
                            <#if messagesPerField.existsError('email')>
                                <span id="email-error" class="input-error" role="alert">${kcSanitize(messagesPerField.getFirstError('email'))}</span>
                            </#if>
                        </div>

                        <div class="form-group">
                            <label for="firstName" class="form-label">${msg("firstName")} *</label>
                            <input type="text" id="firstName" name="firstName" value="${(user.firstName!'')}" class="form-control" autocomplete="given-name"
                                   required
                                   minlength="1"
                                   maxlength="255"
                                   placeholder="Enter your first name"
                                   title="First name is required"
                                   aria-invalid="<#if messagesPerField.existsError('firstName')>true</#if>"
                                   aria-describedby="<#if messagesPerField.existsError('firstName')>firstName-error</#if>" />
                            <#if messagesPerField.existsError('firstName')>
                                <span id="firstName-error" class="input-error" role="alert">${kcSanitize(messagesPerField.getFirstError('firstName'))}</span>
                            </#if>
                        </div>

                        <div class="form-group">
                            <label for="lastName" class="form-label">${msg("lastName")} *</label>
                            <input type="text" id="lastName" name="lastName" value="${(user.lastName!'')}" class="form-control" autocomplete="family-name"
                                   required
                                   minlength="1"
                                   maxlength="255"
                                   placeholder="Enter your last name"
                                   title="Last name is required"
                                   aria-invalid="<#if messagesPerField.existsError('lastName')>true</#if>"
                                   aria-describedby="<#if messagesPerField.existsError('lastName')>lastName-error</#if>" />
                            <#if messagesPerField.existsError('lastName')>
                                <span id="lastName-error" class="input-error" role="alert">${kcSanitize(messagesPerField.getFirstError('lastName'))}</span>
                            </#if>
                        </div>

                        <div class="form-actions">
                            <#if isAppInitiatedAction??>
                                <button type="submit" class="btn-submit" name="submitAction" value="save">${msg("doSubmit")}</button>
                                <button type="submit" class="btn-back" name="submitAction" value="cancel" style="margin-top: 0.75rem;">${msg("doCancel")}</button>
                            <#else>
                                <button type="submit" class="btn-submit">${msg("doSubmit")}</button>
                            </#if>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    </#if>
</@layout.registrationLayout>
