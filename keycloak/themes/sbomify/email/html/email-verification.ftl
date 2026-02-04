<#import "template.ftl" as layout>
<@layout.emailLayout>
    <h1>Verify Your Email Address</h1>
    <p>Dear ${user.firstName!user.username},</p>
    <p>Thank you for creating an account with sbomify. To complete your registration and access your account, please verify your email address by clicking the button below.</p>
    <p style="text-align: center;">
        <a href="${link}" class="button">Verify Email Address</a>
    </p>
    <p class="text-secondary">If you cannot click the button above, copy and paste this link into your browser:</p>
    <p class="text-secondary" style="word-break: break-all;">${link}</p>
    <div class="expiry-notice">
        This link will expire in ${linkExpiration} minutes. If it expires, you can request a new verification email from the login page.
    </div>
    <p>If you did not create an account with sbomify, please ignore this email.</p>
    <p>
        Regards,<br>
        The sbomify Team
    </p>
</@layout.emailLayout>
