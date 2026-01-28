<#macro formScripts formId submittingText passwordMatch=false passwordId="" passwordConfirmId="">
<script>
(function() {
    const form = document.getElementById('${formId}');
    if (!form) return;
    form.addEventListener('submit', function() {
        const submitBtn = this.querySelector('button[type="submit"]');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = ${submittingText?js_string};
        }
    });
    document.querySelectorAll('.form-control').forEach(function(input) {
        const label = input.previousElementSibling;
        if (label && label.classList.contains('form-label')) {
            input.addEventListener('focus', function() { label.classList.add('focused'); });
            input.addEventListener('blur', function() {
                if (!input.value) label.classList.remove('focused');
            });
            if (input.value) label.classList.add('focused');
        }
    });
    <#if passwordMatch && passwordId?has_content && passwordConfirmId?has_content>
    (function() {
        const password = document.getElementById('${passwordId}');
        const passwordConfirm = document.getElementById('${passwordConfirmId}');
        if (password && passwordConfirm) {
            var checkMatch = function() {
                if (password.value && passwordConfirm.value) {
                    passwordConfirm.setCustomValidity(password.value !== passwordConfirm.value ? "Passwords don't match" : '');
                }
            };
            password.addEventListener('input', checkMatch);
            passwordConfirm.addEventListener('input', checkMatch);
        }
    })();
    </#if>
})();
</script>
</#macro>
