<#import "template.ftl" as layout>
<@layout.registrationLayout displayMessage=false; section>
    <#if section = "header">
        ${msg("errorTitle")}
    <#elseif section = "form">
        <div class="login-split-layout">
            <!-- Left Panel: Error Info -->
            <div class="info-panel">
                <div class="info-content">
                    <div class="brand-logo">
                        <img src="${url.resourcesPath}/img/sbomify.svg" alt="sbomify" />
                    </div>
                    <h1 class="info-title">Something Went Wrong</h1>
                    <p class="info-tagline">We encountered an unexpected issue.</p>
                </div>
            </div>

            <!-- Right Panel: Error Message -->
            <div class="form-panel">
                <div class="form-card">
                    <!-- Mobile Logo (hidden on desktop) -->
                    <div class="mobile-logo">
                        <img src="${url.resourcesPath}/img/sbomify.svg" alt="sbomify" />
                    </div>
                    <div class="info-message-container">
                        <div class="info-icon-wrapper info-icon-wrapper--error">
                            <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" xmlns="http://www.w3.org/2000/svg">
                                <path d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" stroke-linecap="round" stroke-linejoin="round"/>
                            </svg>
                        </div>

                        <h2 class="info-message-title">
                            ${msg("errorTitle")}
                        </h2>

                        <div class="info-message-body">
                            <p class="instruction">${kcSanitize(message.summary)}</p>
                        </div>

                        <div class="info-footer">
                            <a href="${url.loginRestartFlowUrl!url.loginUrl}" class="btn-back">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M10 19l-7-7m0 0l7-7m-7 7h18"></path>
                                </svg>
                                <span>Back to Login</span>
                            </a>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </#if>
</@layout.registrationLayout>
