Complete Your Account Setup

Dear ${user.firstName!user.username},

Your administrator has requested that you complete the following action(s) on your sbomify account:

<#if requiredActions?seq_contains("VERIFY_EMAIL")>- Verify your email address
</#if><#if requiredActions?seq_contains("UPDATE_PASSWORD")>- Update your password
</#if><#if requiredActions?seq_contains("UPDATE_PROFILE")>- Update your profile information
</#if><#if requiredActions?seq_contains("CONFIGURE_TOTP")>- Configure two-factor authentication
</#if>

Click the link below to complete these actions:

${link}

This link will expire in ${linkExpiration} minutes.

If you did not expect this email, please contact your administrator.

Regards,
The sbomify Team

------------------------------
Need help? Visit https://sbomify.com/support/contact/
