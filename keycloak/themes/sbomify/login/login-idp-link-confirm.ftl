<#import "template.ftl" as layout>
<@layout.registrationLayout; section>
    <#if section = "header">
        ${msg("confirmLinkIdpTitle")}
    <#elseif section = "form">
        <div class="login-split-layout">
            <!-- Left Panel: Info -->
            <div class="info-panel">
                <div class="info-content">
                    <div class="brand-logo">
                        <img src="${url.resourcesPath}/img/sbomify.svg" alt="sbomify" />
                    </div>
                    <h1 class="info-title">Link Account</h1>
                    <p class="info-tagline">Link your external account with your existing profile.</p>
                </div>
            </div>

            <!-- Right Panel: Form -->
            <div class="form-panel">
                <div class="form-card">
                    <h2 class="form-title">Confirm Account Linking</h2>

                    <form id="kc-register-form" action="${url.loginAction}" method="post">
                        <div class="info-message-body info-message-body--spaced">
                            <p>${msg("confirmLinkIdpReviewProfile", idpAlias)}</p>
                        </div>

                        <div class="form-actions">
                            <button type="submit" class="btn-submit" name="submitAction" id="confirm" value="updateProfile">${msg("confirmLinkIdpReviewProfile")}</button>
                            <button type="submit" class="btn-back" name="submitAction" id="link-account" value="linkAccount" style="margin-top: 0.75rem;">${msg("confirmLinkIdpContinue", idpAlias)}</button>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    </#if>
</@layout.registrationLayout>
