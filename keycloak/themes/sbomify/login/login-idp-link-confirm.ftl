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
                    <div class="form-header">
                        <h2>Confirm Account Linking</h2>
                    </div>

                    <form id="kc-register-form" action="${url.loginAction}" method="post">
                        <div class="info-message-body" style="margin-bottom: 2rem;">
                            <p>${msg("confirmLinkIdpReviewProfile", idpAlias)}</p>
                        </div>

                        <div class="form-actions">
                            <button type="submit" class="btn btn-primary btn-block" name="submitAction" id="confirm" value="updateProfile">${msg("confirmLinkIdpReviewProfile")}</button>
                            <button type="submit" class="btn btn-secondary btn-block" name="submitAction" id="link-account" value="linkAccount">${msg("confirmLinkIdpContinue", idpAlias)}</button>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    </#if>
</@layout.registrationLayout>
