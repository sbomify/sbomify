<#macro formScripts formId submittingText passwordMatch=false passwordId="" passwordConfirmId="">
<script>
(function() {
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
})();
</script>
</#macro>

<#macro emailVerificationContent>
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

        <!-- Right Panel: Verification Message -->
        <div class="form-panel">
            <div class="form-card">
                <!-- Mobile Logo (hidden on desktop) -->
                <div class="mobile-logo">
                    <img src="${url.resourcesPath}/img/sbomify.svg" alt="sbomify" />
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
                                The verification link will expire in a few minutes. You can request a new one if needed.
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
