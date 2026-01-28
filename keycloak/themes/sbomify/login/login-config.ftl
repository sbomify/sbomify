<#import "template.ftl" as layout>
<@layout.registrationLayout; section>
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
                    <h1 class="info-title">Authentication Required</h1>
                    <p class="info-tagline">Please complete the required steps</p>
                </div>
            </div>

            <!-- Right Panel: Required Actions -->
            <div class="form-panel">
                <div class="form-card">
                    <div class="info-message-container">
                        <div class="info-icon-wrapper">
                            <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" xmlns="http://www.w3.org/2000/svg">
                                <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012 0m6 0a2 2 0 012 0m-6 4h.01M6 20h12" stroke-linecap="round" stroke-linejoin="round"/>
                            </svg>
                        </div>

                        <h2 class="info-message-title">Additional Information Required</h2>

                        <div class="info-message-body">
                            <p>To continue, please complete the following steps:</p>
                            
                            <#if requiredActions??>
                                <div class="required-actions">
                                    <#list requiredActions as action>
                                        <div class="action-item">
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                                <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                                            </svg>
                                            <span>${kcSanitize(action)}</span>
                                        </div>
                                    </#list>
                                </div>
                            </#if>
                        </div>

                        <div class="info-footer">
                            <a href="${url.loginRestartFlowUrl!url.loginUrl}" class="btn-back">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M10 19l-7-7m0 0l7-7m-7 7h18"/>
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
