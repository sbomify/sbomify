<#import "template.ftl" as layout>
<@layout.registrationLayout; section>
    <#if section = "header">
        ${msg("pageExpiredTitle")}
    <#elseif section = "form">
        <div class="login-split-layout">
            <!-- Left Panel: Info -->
            <div class="info-panel">
                <div class="info-content">
                    <div class="brand-logo">
                        <img src="${url.resourcesPath}/img/sbomify.svg" alt="sbomify" />
                    </div>
                    <h1 class="info-title">Session Expired</h1>
                    <p class="info-tagline">Your login session has timed out.</p>
                </div>
            </div>

            <!-- Right Panel: Actions -->
            <div class="form-panel">
                <div class="form-card">
                    <div class="info-message-container">
                        <div class="info-icon-wrapper" style="color: #f59e0b; background: #fef3c7;">
                            <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" xmlns="http://www.w3.org/2000/svg">
                                <path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" stroke-linecap="round" stroke-linejoin="round"/>
                            </svg>
                        </div>

                        <h2 class="info-message-title">
                            ${msg("pageExpiredTitle")}
                        </h2>

                        <div class="info-message-body">
                            <p class="instruction">${msg("pageExpiredMsg1")} <a id="loginRestartLink" href="${url.loginRestartFlowUrl}">${msg("doClickHere")}</a>.<br/>${msg("pageExpiredMsg2")} <a id="loginContinueLink" href="${url.loginAction}">${msg("doClickHere")}</a>.</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </#if>
</@layout.registrationLayout>
