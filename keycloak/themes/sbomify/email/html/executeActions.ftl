<#import "template.ftl" as layout>
<@layout.emailLayout>
    <h1>Finish setting up your account</h1>
    <p>Hi ${user.firstName!user.username},</p>
    <p>Your administrator has requested that you complete the following action(s) on your sbomify account:</p>
    <ul>
        <#if requiredActions?seq_contains("VERIFY_EMAIL")><li>Verify your email address</li></#if>
        <#if requiredActions?seq_contains("UPDATE_PASSWORD")><li>Update your password</li></#if>
        <#if requiredActions?seq_contains("UPDATE_PROFILE")><li>Update your profile information</li></#if>
        <#if requiredActions?seq_contains("CONFIGURE_TOTP")><li>Configure two-factor authentication</li></#if>
    </ul>
    <p>Click the button below to complete these actions.</p>
    <p style="text-align: center;">
        <a href="${link}" class="button">Finish setup</a>
    </p>
    <p class="text-secondary">If you cannot click the button above, copy and paste this link into your browser:</p>
    <p class="text-secondary" style="word-break: break-all;">${link}</p>
    <div class="expiry-notice">
        This link will expire in ${linkExpirationFormatter(linkExpiration)}.
    </div>
    <p>If you did not expect this email, please contact your administrator.</p>
</@layout.emailLayout>
