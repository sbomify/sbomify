<#import "template.ftl" as layout>
<@layout.registrationLayout displayMessage=true displayInfo=false; section>
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
                    <h1 class="info-title">Terms & Conditions</h1>
                    <p class="info-tagline">Please review before continuing</p>
                </div>
            </div>

            <!-- Right Panel: Terms Display -->
            <div class="form-panel">
                <div class="form-card">
                    <div class="info-message-container">
                        <div class="info-icon-wrapper">
                            <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" xmlns="http://www.w3.org/2000/svg">
                                <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012 0m6 0a2 2 0 012 0m-6 4h.01M6 20h12" stroke-linecap="round" stroke-linejoin="round"/>
                            </svg>
                        </div>

                        <h2 class="info-message-title">User Agreement</h2>

                        <div class="info-message-body terms-content">
                            <#if message?has_content>
                                <p>${kcSanitize(message.summary)}</p>
                            <#else>
                                <p>By continuing, you agree to sbomify's terms of service and privacy policy.</p>
                            </#if>

                            <div class="email-tips">
                                <h3>Key Points:</h3>
                                <ul>
                                    <li>
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <path d="M5 13l4 4L19 7"/>
                                        </svg>
                                        <span>Use of services is subject to acceptance</span>
                                    </li>
                                    <li>
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                                        </svg>
                                        <span>Your data is handled per privacy policy</span>
                                    </li>
                                    <li>
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                                        </svg>
                                        <span>You can opt out at any time</span>
                                    </li>
                                    <li>
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <circle cx="12" cy="12" r="10"></circle>
                                            <path d="M12 6v6l4 2"></path>
                                        </svg>
                                        <span>Contact support for questions</span>
                                    </li>
                                </ul>
                            </div>

                            <div class="info-notice">
                                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <circle cx="12" cy="12" r="10"></circle>
                                    <path d="M12 8v4M12 16h.01"></path>
                                </svg>
                                <span>
                                    <strong>Need Help?</strong> 
                                    Review our full terms of service or contact support if you have questions.
                                </span>
                            </div>
                        </div>

                        <form action="${url.loginAction}" method="post">
                            <input type="hidden" name="action" value="accept">
                            
                            <div class="form-actions">
                                <button type="submit" class="btn-submit" aria-label="Accept Terms">
                                    Accept & Continue
                                </button>
                            </div>
                        </form>

                        <div class="info-footer">
                            <a href="${url.loginUrl}" class="btn-back">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M10 19l-7-7m0 0l7-7m-7 7h18"></path>
                                </svg>
                                <span>Cancel</span>
                            </a>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </#if>
</@layout.registrationLayout>
