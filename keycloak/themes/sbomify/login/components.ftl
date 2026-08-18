<#--
  The message banner every form page opens with. One caller, one recipe: the
  variant class sets --alert-accent and the stylesheet derives fill, border and
  text from it. Kept here rather than repeated per page so the markup and the
  aria wiring cannot drift between pages.
-->
<#macro alertBanner>
    <#if message?has_content && (message.type != 'warning' || !isAppInitiatedAction??)>
        <div class="alert alert-${message.type}" role="alert" aria-live="polite">
            <#if message.type = 'success'><span class="alert-icon" aria-hidden="true">✓</span></#if>
            <#if message.type = 'warning'><span class="alert-icon" aria-hidden="true">⚠</span></#if>
            <#if message.type = 'error'><span class="alert-icon" aria-hidden="true">✕</span></#if>
            <#if message.type = 'info'><span class="alert-icon" aria-hidden="true">ℹ</span></#if>
            <span class="alert-text">${kcSanitize(message.summary)}</span>
        </div>
    </#if>
</#macro>

<#--
  Client-side validation for a form. Callers place this at the top of the form,
  so the fields below it are not in the DOM yet when the script runs: everything
  has to wait for the document to finish parsing, or getElementById returns null
  and the listeners silently never attach.
-->
<#macro formScripts formId submittingText passwordMatch=false passwordId="" passwordConfirmId="">
<script>
(function() {
    const init = function() {
    const form = document.getElementById('${formId}');
    if (!form) return;

    // Helper function to show validation error styling
    const showError = function(input) {
        input.classList.add('input-invalid');
        input.setAttribute('aria-invalid', 'true');
    };

    // Helper function to clear validation error styling
    const clearError = function(input) {
        input.classList.remove('input-invalid');
        input.setAttribute('aria-invalid', 'false');
    };

    // Handle form submission
    form.addEventListener('submit', function(e) {
        const submitBtn = this.querySelector('button[type="submit"]');

        // Check HTML5 form validity first
        if (!form.checkValidity()) {
            e.preventDefault();
            // Find the first invalid field and focus it
            const firstInvalid = form.querySelector(':invalid');
            if (firstInvalid) {
                firstInvalid.focus();
                showError(firstInvalid);
                // Report validity to show browser tooltip
                firstInvalid.reportValidity();
            }
            return;
        }

        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.textContent = '${submittingText?js_string}';
        }
    });

    // Add real-time validation feedback for all form controls
    form.querySelectorAll('.form-control').forEach(function(input) {
        const label = input.previousElementSibling;

        // Focus state management
        if (label && label.classList.contains('form-label')) {
            input.addEventListener('focus', function() { label.classList.add('focused'); });
            input.addEventListener('blur', function() {
                if (!input.value) label.classList.remove('focused');
            });
            if (input.value) label.classList.add('focused');
        }

        // Real-time validation on blur
        input.addEventListener('blur', function() {
            if (input.value && !input.validity.valid) {
                showError(input);
            } else if (input.validity.valid) {
                clearError(input);
            }
        });

        // Clear error on input when field becomes valid
        input.addEventListener('input', function() {
            if (input.validity.valid) {
                clearError(input);
            }
        });
    });

    <#if passwordMatch && passwordId?has_content && passwordConfirmId?has_content>
    // Password matching validation
    (function() {
        const password = document.getElementById('${passwordId}');
        const passwordConfirm = document.getElementById('${passwordConfirmId}');
        if (password && passwordConfirm) {
            let debounceTimer = null;

            const checkMatch = function() {
                // Only validate password match when both fields have values
                // This prevents premature validation errors while the user is still typing
                if (password.value && passwordConfirm.value) {
                    const isMatch = password.value === passwordConfirm.value;
                    // Set custom validity only for mismatch, empty string clears it
                    passwordConfirm.setCustomValidity(isMatch ? '' : "Passwords don't match");

                    // Update visual feedback
                    if (!isMatch) {
                        showError(passwordConfirm);
                    } else {
                        clearError(passwordConfirm);
                    }
                } else {
                    // If either field is empty, clear custom validity
                    // Let the HTML5 'required' attribute handle empty field validation and show
                    // its default message (for example, "Please fill out this field") instead of
                    // a password-specific message. This intentionally does not override native
                    // required validation behavior.
                    passwordConfirm.setCustomValidity('');
                }
            };

            const checkMatchDebounced = function() {
                // Clear any existing timer
                if (debounceTimer) {
                    clearTimeout(debounceTimer);
                }

                // Debounce validation by 300ms to avoid premature errors while typing
                debounceTimer = setTimeout(checkMatch, 300);
            };

            // Validate on input with debounce (for better UX while typing)
            password.addEventListener('input', checkMatchDebounced);
            passwordConfirm.addEventListener('input', checkMatchDebounced);

            // Validate immediately on blur (when user leaves the field)
            password.addEventListener('blur', checkMatch);
            passwordConfirm.addEventListener('blur', checkMatch);

            // Validate on form submit (immediate feedback before submission)
            form.addEventListener('submit', function(e) {
                // Clear any pending debounce so validation runs synchronously
                if (debounceTimer) {
                    clearTimeout(debounceTimer);
                    debounceTimer = null;
                }
                checkMatch();
                if (!passwordConfirm.validity.valid) {
                    e.preventDefault();
                    passwordConfirm.focus();
                    showError(passwordConfirm);
                }
            });
        }
    })();
    </#if>
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
</script>
</#macro>

<#macro emailVerificationContent>
    <div class="login-split-layout">
        <!-- Left Panel: App Info -->
        <div class="info-panel">
            <div class="info-content">
                <div class="brand-logo">
                    <@brandLogo />
                </div>
                <h1 class="info-title">Verify Your Email</h1>
                <p class="info-tagline">Please check your inbox to complete registration</p>
            </div>
        </div>

        <!-- Right Panel: Verification Message -->
        <div class="form-panel">
            <div class="form-card">
                <!-- Mobile Logo (hidden on desktop) -->
                <div class="mobile-logo">
                    <@brandLogo />
                </div>
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
                            Check Your Inbox
                        </#if>
                    </h2>

                    <div class="info-message-body">
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
                                The verification link expires after a while. You can request a new one if needed.
                            </span>
                        </div>
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
</#macro>

<#--
  Inline animated sbomify logo. Inlined (not <img>/<object>) because Chrome
  freezes CSS animations inside external SVG documents. Fill follows
  currentColor; colour and sizing come from .brand-logo / .mobile-logo CSS.
-->
<#macro brandLogo>
<svg class="brand-anim" viewBox="0 0 571.45 107" role="img" aria-label="sbomify">
    <path class="bar b1" d="M.92,9.93C-.31,7.83-.31,5.12.92,3.02,2.05,1.08,4.04-.03,6.39,0h27.87c2.35-.02,4.35,1.06,5.48,3.01,1.23,2.1,1.23,4.82,0,6.92-1.12,1.92-3.08,3.01-5.38,3.01H6.39c-2.35.02-4.34-1.07-5.47-3.02Z"/>
    <path class="bar b2 from-right" d="M47.71,9.93c-1.22-2.1-1.22-4.81,0-6.91C48.85,1.07,50.84-.04,53.19,0h.68s69.45,0,69.45,0c3.56,0,6.46,2.91,6.46,6.48s-2.9,6.46-6.46,6.46H53.09c-2.3,0-4.26-1.09-5.38-3.01Z"/>
    <path class="bar b3" d="M1.02,28.36c-1.23-2.09-1.23-4.81,0-6.91,1.14-1.95,3.14-3.07,5.47-3.03h50.96c1.73,0,3.35.68,4.57,1.9,1.22,1.23,1.89,2.86,1.88,4.59,0,3.55-2.9,6.45-6.45,6.45H6.4c-2.3,0-4.26-1.09-5.38-3.01Z"/>
    <path class="bar b4" d="M1.02,46.75c-1.22-2.09-1.22-4.79,0-6.89,1.14-1.95,3.14-3.06,5.48-3.02h.68s69.77,0,69.77,0c3.56,0,6.46,2.9,6.46,6.46s-2.9,6.46-6.46,6.46H6.41c-2.31,0-4.27-1.09-5.39-3.01Z"/>
    <path class="bar b5 from-right" d="M46.36,61.69c0-3.56,2.9-6.46,6.46-6.46h70.49c2.35-.02,4.34,1.07,5.47,3.01,1.22,2.09,1.22,4.79,0,6.89-1.12,1.92-3.08,3.02-5.38,3.02h-.76s-69.8,0-69.8,0c-3.56,0-6.46-2.9-6.46-6.45Z"/>
    <path class="bar b6 from-right" d="M67.76,84.67c-1.22-1.23-1.89-2.86-1.89-4.59,0-3.55,2.9-6.45,6.46-6.45h50.97c2.34-.03,4.33,1.06,5.47,3.01,1.23,2.09,1.23,4.81,0,6.91-1.12,1.93-3.08,3.03-5.39,3.03h-51.05c-1.73,0-3.35-.68-4.57-1.9Z"/>
    <path class="bar b7" d="M82.06,95.07c1.22,2.1,1.22,4.81,0,6.91-1.12,1.93-3.08,3.02-5.38,3.02H6.46C2.9,104.99,0,102.09,0,98.52s2.89-6.45,6.44-6.47h70.15c2.35-.02,4.33,1.07,5.46,3.01Z"/>
    <path class="bar b8 from-right" d="M128.86,101.98c-1.13,1.95-3.12,3.06-5.47,3.02h-27.97c-2.3,0-4.26-1.09-5.38-3.01-1.23-2.1-1.23-4.82,0-6.92,1.14-1.95,3.14-3.03,5.48-3.01h27.87c2.35-.03,4.34,1.07,5.47,3.02,1.22,2.09,1.22,4.8,0,6.9Z"/>
    <path class="ltr l1" d="M238.43,67.44c0,12.3-10.69,17.53-22.24,17.53-10.09,0-17.89-3.62-22.24-11.3-.44-.77-.16-1.75.61-2.19l10.98-6.25c.79-.45,1.8-.15,2.22.66,1.58,3.08,4.37,4.76,8.43,4.76,3.85,0,5.77-1.18,5.77-3.31,0-5.88-26.3-2.78-26.3-21.28,0-11.65,9.84-17.53,20.95-17.53,8.07,0,15.31,3.35,19.89,9.95.54.78.26,1.86-.57,2.31l-10.82,5.83c-.72.39-1.62.17-2.08-.51-1.45-2.1-3.44-3.48-6.42-3.48-2.78,0-4.49,1.07-4.49,2.99,0,6.09,26.3,2.03,26.3,21.81Z"/>
    <path class="ltr l2" d="M301.35,56.75c0,15.93-11.55,28.23-25.55,28.23-7.16,0-12.4-2.46-15.93-6.52v3.42c0,.89-.72,1.61-1.61,1.61h-12.82c-.89,0-1.61-.72-1.61-1.61V10.25c0-.89.72-1.61,1.61-1.61h12.82c.89,0,1.61.72,1.61,1.61v24.8c3.53-4.06,8.77-6.52,15.93-6.52,14.01,0,25.55,12.3,25.55,28.23ZM285.31,56.75c0-8.02-5.35-13.04-12.72-13.04s-12.72,5.02-12.72,13.04,5.35,13.04,12.72,13.04,12.72-5.02,12.72-13.04Z"/>
    <path class="ltr l3" d="M306.15,56.75c0-15.93,12.62-28.23,28.33-28.23s28.33,12.3,28.33,28.23-12.62,28.23-28.33,28.23-28.33-12.3-28.33-28.23ZM346.78,56.75c0-7.59-5.35-12.62-12.3-12.62s-12.3,5.03-12.3,12.62,5.35,12.62,12.3,12.62,12.3-5.03,12.3-12.62Z"/>
    <path class="ltr l4" d="M449.64,50.66v31.21c0,.89-.72,1.61-1.61,1.61h-12.82c-.89,0-1.61-.72-1.61-1.61v-29.82c0-5.35-2.57-8.77-7.7-8.77s-8.34,3.74-8.34,10.05v28.54c0,.89-.72,1.61-1.61,1.61h-12.82c-.89,0-1.61-.72-1.61-1.61v-29.82c0-5.35-2.57-8.77-7.7-8.77s-8.34,3.74-8.34,10.05v28.54c0,.89-.72,1.61-1.61,1.61h-12.82c-.89,0-1.61-.72-1.61-1.61V31.63c0-.89.72-1.61,1.61-1.61h12.82c.89,0,1.61.72,1.61,1.61v3.31c2.46-3.63,7.16-6.41,14.33-6.41,6.31,0,11.01,2.57,14.01,7.06,2.99-4.28,7.91-7.06,15.5-7.06,12.3,0,20.31,8.77,20.31,22.13Z"/>
    <path class="ltr l5" d="M456.43,18.23c-1.94-7.13,4.68-13.75,11.81-11.81,3.26.88,5.87,3.49,6.75,6.75,1.94,7.13-4.68,13.75-11.81,11.81-3.26-.88-5.87-3.49-6.75-6.75ZM459.3,30.02h12.82c.89,0,1.61.72,1.61,1.61v50.24c0,.89-.72,1.61-1.61,1.61h-12.82c-.89,0-1.61-.72-1.61-1.61V31.63c0-.89.72-1.61,1.61-1.61Z"/>
    <path class="ltr l6" d="M503.7,30.02h6.7c.89,0,1.61.72,1.61,1.61v12.18c0,.89-.72,1.61-1.61,1.61h-6.7v36.45c0,.89-.72,1.61-1.61,1.61h-12.82c-.89,0-1.61-.72-1.61-1.61v-36.45h-5.56c-.89,0-1.61-.72-1.61-1.61v-12.18c0-.89.72-1.61,1.61-1.61h5.56c0-14.52,7.75-23.41,24.41-22.95.87.02,1.57.74,1.57,1.61v12.16c0,.89-.73,1.62-1.62,1.61-5.07-.07-8.33,1.95-8.33,7.57Z"/>
    <path class="ltr l7" d="M569.84,30.02c1.11,0,1.89,1.1,1.52,2.14l-17.53,49.71c-5.77,16.39-14.82,23.24-28.87,23.04-.88-.01-1.6-.73-1.6-1.61v-11.84c0-.86.68-1.56,1.54-1.6,6.44-.32,9.64-2.78,11.82-8.84l-20.35-48.77c-.44-1.06.34-2.23,1.48-2.23h14.1c.68,0,1.28.42,1.51,1.06l11.48,31.66,9.7-31.58c.21-.68.83-1.14,1.54-1.14h13.65Z"/>
</svg>
</#macro>
