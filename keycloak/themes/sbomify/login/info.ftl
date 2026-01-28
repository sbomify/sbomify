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
                    <h1 class="info-title">Verify Your Email</h1>
                    <p class="info-tagline">Please check your inbox to complete registration</p>
                </div>
            </div>

            <!-- Right Panel: Info Message -->
            <div class="form-panel">
                <div class="form-card">
                    <div class="info-message-container">
                        <div class="info-icon-wrapper">
                            <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" xmlns="http://www.w3.org/2000/svg">
                                <path d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" stroke-linecap="round" stroke-linejoin="round"/>
                            </svg>
                        </div>

                        <h2 class="info-message-title">
                            <#if message?has_content>
                                ${kcSanitize(message.summary)}
                            <#else>
                                Check Your Email
                            </#if>
                        </h2>

                        <div class="info-message-body">
                            <#if message?has_content && message.summary?contains("email") && message.summary?contains("verify")>
                                <p>We've sent a verification email to your inbox. Please follow the instructions in the email to complete your registration.</p>
                                
                                <div class="email-tips">
                                    <h3>What to do next:</h3>
                                    <ul>
                                        <li>
                                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                                <circle cx="12" cy="12" r="10"></circle>
                                                <path d="M12 6v6l4 2"></path>
                                            </svg>
                                            <span>Check your email inbox (and spam folder)</span>
                                        </li>
                                        <li>
                                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                                <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                                            </svg>
                                            <span>Click the verification link in the email</span>
                                        </li>
                                        <li>
                                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                                <path d="M13 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V9z"></path>
                                                <path d="M13 7V2"></path>
                                            </svg>
                                            <span>Return here after verification to sign in</span>
                                        </li>
                                    </ul>
                                </div>

                                <div class="info-notice">
                                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                        <circle cx="12" cy="12" r="10"></circle>
                                        <path d="M12 8v4M12 16h.01"></path>
                                    </svg>
                                    <span>
                                        <strong>Didn't receive the email?</strong> 
                                        The link will expire in a few minutes. You can request a new verification email if needed.
                                    </span>
                                </div>
                            <#elseif message?has_content>
                                <p>${kcSanitize(message.summary)}</p>
                            <#else>
                                <p>Check your inbox for further instructions.</p>
                            </#if>
                        </div>

                        <#if requiredActions??>
                            <div class="required-actions">
                                <h3>Required Actions:</h3>
                                <#list requiredActions as action>
                                    <div class="action-item">
                                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012 0m6 0a2 2 0 012 0m-6 4h.01M6 20h12"></path>
                                        </svg>
                                        <span>${kcSanitize(action)}</span>
                                    </div>
                                </#list>
                            </div>
                        </#if>

                        <#if skipLink??>
                            <div class="info-actions">
                                <a href="${skipLink}" class="btn-skip">
                                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                        <path d="M17 8l4 4m0 0l-4 4m4-4H3"></path>
                                    </svg>
                                    <span>Skip</span>
                                </a>
                            </div>
                        </#if>



                        <div class="info-footer">
                            <a href="${(client.baseUrl)!url.loginRestartFlowUrl!url.loginUrl}" class="btn-back">
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
    <#if message?has_content && message.type == 'success'>
        <div data-toast-message="${kcSanitize(message.summary)?html}" style="display: none;" aria-hidden="true"></div>
    </#if>
    <script src="${url.resourcesPath}/js/toast.js"></script>
</@layout.registrationLayout>
