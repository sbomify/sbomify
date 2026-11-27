<#import "template.ftl" as layout>
<#import "components.ftl" as components>
<@layout.registrationLayout; section>
    <#if section = "header">
        <#-- Header is handled in the info panel -->
    <#elseif section = "form">
        <div class="login-split-layout">
            <!-- Left Panel: Info -->
            <div class="info-panel">
                <div class="info-content">
                    <div class="brand-logo">
                        <@components.brandLogo />
                    </div>
                    <h1 class="info-title">${msg("oauthGrantInfoTitle")}</h1>
                    <p class="info-tagline">${msg("oauthGrantInfoTagline")}</p>
                </div>
            </div>

            <!-- Right Panel: Consent -->
            <div class="form-panel">
                <div class="form-card">
                    <!-- Mobile Logo (hidden on desktop) -->
                    <div class="mobile-logo">
                        <@components.brandLogo />
                    </div>
                    <h2 class="form-title">
                        <#if client.name?has_content>
                            ${msg("oauthGrantTitle", advancedMsg(client.name))}
                        <#else>
                            ${msg("oauthGrantTitle", client.clientId)}
                        </#if>
                    </h2>

                    <div class="email-tips">
                        <h3>${msg("oauthGrantRequest")}</h3>
                        <ul>
                            <#if oauth.clientScopesRequested??>
                                <#list oauth.clientScopesRequested as clientScope>
                                    <li>
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                                            <path d="M5 13l4 4L19 7"/>
                                        </svg>
                                        <span>
                                            ${advancedMsg(clientScope.consentScreenText)}<#if clientScope.dynamicScopeParameter??>: <b>${clientScope.dynamicScopeParameter}</b></#if>
                                        </span>
                                    </li>
                                </#list>
                            </#if>
                        </ul>
                    </div>

                    <#-- The app registered these links itself, so only an https one is shown. -->
                    <#assign tosUri = client.attributes.tosUri!"">
                    <#assign policyUri = client.attributes.policyUri!"">
                    <#if tosUri?starts_with("https://") || policyUri?starts_with("https://")>
                        <div class="info-message-body">
                            <p>
                                ${msg("oauthGrantInformation")}
                                <#if tosUri?starts_with("https://")>
                                    <a href="${tosUri}" target="_blank" rel="noopener noreferrer">${msg("oauthGrantTos")}</a>
                                </#if>
                                <#if policyUri?starts_with("https://")>
                                    <a href="${policyUri}" target="_blank" rel="noopener noreferrer">${msg("oauthGrantPolicy")}</a>
                                </#if>
                            </p>
                        </div>
                    </#if>

                    <#-- Keycloak reads the choice off the button's name: "accept" or "cancel". -->
                    <form action="${url.oauthAction}" method="post">
                        <input type="hidden" name="code" value="${oauth.code}">
                        <div class="info-actions">
                            <button type="submit" class="btn-back" name="cancel" id="kc-cancel">${msg("oauthGrantDeny")}</button>
                            <button type="submit" class="btn-submit" name="accept" id="kc-login">${msg("oauthGrantAllow")}</button>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    </#if>
</@layout.registrationLayout>
