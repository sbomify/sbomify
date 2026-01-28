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
                    <h2 class="form-title">Complete Profile</h2>

                    <form id="kc-update-profile-form" class="login-form" action="${url.loginAction}" method="post">
                        <#if user.editUsernameAllowed>
                            <div class="form-group <#if messagesPerField.existsError('username')>has-error</#if>">
                                <label for="username" class="form-label">${msg("username")}</label>
                                <input type="text" id="username" name="username" value="${(user.username!'')}" class="form-control" autocomplete="username">
                                <#if messagesPerField.existsError('username')>
                                    <span class="input-error">${kcSanitize(messagesPerField.getFirstError('username'))}</span>
                                </#if>
                            </div>
                        </#if>

                        <div class="form-group <#if messagesPerField.existsError('email')>has-error</#if>">
                            <label for="email" class="form-label">${msg("email")}</label>
                            <input type="text" id="email" name="email" value="${(user.email!'')}" class="form-control" autocomplete="email">
                            <#if messagesPerField.existsError('email')>
                                <span class="input-error">${kcSanitize(messagesPerField.getFirstError('email'))}</span>
                            </#if>
                        </div>

                        <div class="form-group <#if messagesPerField.existsError('firstName')>has-error</#if>">
                            <label for="firstName" class="form-label">${msg("firstName")}</label>
                            <input type="text" id="firstName" name="firstName" value="${(user.firstName!'')}" class="form-control" autocomplete="given-name">
                            <#if messagesPerField.existsError('firstName')>
                                <span class="input-error">${kcSanitize(messagesPerField.getFirstError('firstName'))}</span>
                            </#if>
                        </div>

                        <div class="form-group <#if messagesPerField.existsError('lastName')>has-error</#if>">
                            <label for="lastName" class="form-label">${msg("lastName")}</label>
                            <input type="text" id="lastName" name="lastName" value="${(user.lastName!'')}" class="form-control" autocomplete="family-name">
                            <#if messagesPerField.existsError('lastName')>
                                <span class="input-error">${kcSanitize(messagesPerField.getFirstError('lastName'))}</span>
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
        <@components.formScripts formId="kc-update-profile-form" submittingText="'Updating...'" />
    </#if>
</@layout.registrationLayout>
