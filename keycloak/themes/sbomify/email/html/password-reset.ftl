<#import "template.ftl" as layout>
<@layout.emailLayout>
    <h1>Reset Your Password</h1>
    <p>Dear ${user.firstName!user.username},</p>
    <p>We received a request to reset your password for your sbomify account. Click the button below to create a new password.</p>
    <p style="text-align: center;">
        <a href="${link}" class="button">Reset Password</a>
    </p>
    <p class="text-secondary">If you cannot click the button above, copy and paste this link into your browser:</p>
    <p class="text-secondary" style="word-break: break-all;">${link}</p>
    <div class="expiry-notice">
        This link will expire in ${linkExpiration} minutes. If it expires, you can request a new password reset from the login page.
    </div>
    <p>If you did not request a password reset, please ignore this email. Your password will remain unchanged.</p>
</@layout.emailLayout>
