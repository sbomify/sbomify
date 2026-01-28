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
                                        <span>${action}</span>
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

                        <#if message?has_content && (message.type != 'warning' || !(isAppInitiatedAction??))>
                            <div class="alert alert-${message.type}" role="alert" aria-live="polite">
                                <#if message.type = 'success'><span class="alert-icon" aria-hidden="true">✓</span></#if>
                                <#if message.type = 'warning'><span class="alert-icon" aria-hidden="true">⚠</span></#if>
                                <#if message.type = 'error'><span class="alert-icon" aria-hidden="true">✕</span></#if>
                                <#if message.type = 'info'><span class="alert-icon" aria-hidden="true">ℹ</span></#if>
                                <span class="alert-text">${kcSanitize(message.summary)}</span>
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
    <script>
        document.addEventListener('DOMContentLoaded', function() {
            // Check if there is a success message
            <#if message?has_content && message.type == 'success'>
                const messageText = "${kcSanitize(message.summary)?js_string}";
                
                // Create toast element
                const toast = document.createElement('div');
                toast.className = 'toast-banner';
                toast.innerHTML = `
                    <div class="toast-content">
                        <svg class="toast-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                            <polyline points="22 4 12 14.01 9 11.01"></polyline>
                        </svg>
                        <span>` + messageText + `</span>
                    </div>
                `;

                // Add styles dynamically
                const style = document.createElement('style');
                style.textContent = `
                    .toast-banner {
                        position: fixed;
                        top: 24px;
                        left: 50%;
                        transform: translateX(-50%) translateY(-100%);
                        background: #10B981;
                        color: white;
                        padding: 12px 24px;
                        border-radius: 8px;
                        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
                        z-index: 9999;
                        opacity: 0;
                        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                        display: flex;
                        align-items: center;
                        font-family: inherit;
                        font-weight: 500;
                    }
                    .toast-banner.show {
                        transform: translateX(-50%) translateY(0);
                        opacity: 1;
                    }
                    .toast-content {
                        display: flex;
                        align-items: center;
                        gap: 12px;
                    }
                    .toast-icon {
                        flex-shrink: 0;
                    }
                `;
                document.head.appendChild(style);
                document.body.appendChild(toast);

                // Show toast
                requestAnimationFrame(() => {
                    toast.classList.add('show');
                });

                // Hide after 2 seconds
                setTimeout(() => {
                    toast.classList.remove('show');
                    setTimeout(() => {
                        toast.remove();
                    }, 300);
                }, 2000);
            </#if>
        });
    </script>
</@layout.registrationLayout>
