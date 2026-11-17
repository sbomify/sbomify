<#--
    The same layout as the app's mail, sbomify/apps/core/templates/core/emails/base.html.j2,
    so a password reset reads as the same product as a billing notice. Keep the two in step.

    Mail clients cannot read CSS custom properties, so the design tokens are written
    out as hex. Every value is the app's light-theme token from
    sbomify/assets/css/tailwind.src.css, named alongside it, and test_email_palette.py
    fails on one that is not.
-->
<#macro emailLayout>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <meta name="color-scheme" content="light">
    <meta name="supported-color-schemes" content="light">
    <title>${msg("emailTitle", realmName)}</title>
    <#-- Figtree, the app's typeface. Clients that ignore web fonts use the system stack. -->
    <link href="https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body {
            font-family: 'Figtree', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            line-height: 1.6;
            color: #51546b; /* --color-text-secondary */
            margin: 0;
            padding: 0;
            background-color: #eef0f4; /* --color-surface-hover */
            -webkit-font-smoothing: antialiased;
        }

        .email-wrapper {
            background-color: #eef0f4; /* --color-surface-hover */
        }

        .email-wrapper-cell {
            padding: 20px;
        }

        .email-container {
            background-color: #ffffff; /* --color-surface */
            border: 1px solid #e9eaec; /* --color-border */
            border-radius: 12px; /* --radius-xl */
            overflow: hidden;
        }

        .email-body {
            padding: 40px;
        }

        h1 {
            color: #25293f; /* --color-text */
            font-size: 24px;
            line-height: 1.3;
            margin-top: 0;
            margin-bottom: 16px;
            font-weight: 600;
        }

        p {
            margin-top: 16px;
            margin-bottom: 16px;
            color: #51546b; /* --color-text-secondary */
        }

        strong {
            color: #25293f; /* --color-text */
        }

        ul {
            margin-top: 16px;
            margin-bottom: 16px;
            padding-left: 24px;
            color: #51546b; /* --color-text-secondary */
        }

        a {
            color: #25293f; /* --color-primary */
            text-decoration: underline;
        }

        /* The app's primary button on the light theme. Clients that drop the
           gradient keep the solid fill underneath. */
        a.button {
            display: inline-block;
            padding: 12px 24px;
            background-color: #25293f; /* --color-primary-fill */
            background-image: linear-gradient(135deg, #25293f 0%, #1a1d2e 100%); /* --color-primary-fill, -end */
            border: 0.5px solid #25293f; /* --color-primary */
            border-radius: 8px; /* --radius-lg */
            color: #ffffff;
            text-decoration: none;
            margin-top: 16px;
            margin-bottom: 16px;
            font-weight: 500;
            font-size: 15px;
            text-align: center;
        }

        .text-secondary {
            color: #6e7180; /* --color-text-muted */
            font-size: 14px;
        }

        .expiry-notice {
            background-color: #fdf3e1; /* --color-warning-light */
            border-left: 3px solid #8e6014; /* --color-warning */
            border-radius: 8px; /* --radius-lg */
            color: #8e6014; /* --color-warning */
            padding: 12px;
            margin-top: 16px;
            margin-bottom: 16px;
            font-size: 14px;
        }

        .footer {
            background-color: #eef0f4; /* --color-surface-hover */
            border-top: 1px solid #e9eaec; /* --color-border */
            padding: 24px 40px;
            text-align: center;
            color: #6e7180; /* --color-text-muted */
            font-size: 14px;
        }

        .footer p {
            color: #6e7180; /* --color-text-muted */
        }

        @media only screen and (max-width: 620px) {
            .email-container {
                width: 100%;
                max-width: 100%;
            }

            .email-wrapper-cell {
                padding: 12px;
            }

            .email-body {
                padding: 24px;
            }

            .footer {
                padding: 20px 24px;
            }

            a.button {
                display: block;
            }
        }
    </style>
</head>
<body>
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" bgcolor="#eef0f4" class="email-wrapper">
<tr>
<td align="center" class="email-wrapper-cell">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="600" bgcolor="#ffffff" class="email-container">
<tr>
<#-- PNG, not SVG: Gmail, Outlook and Yahoo do not render SVG in mail. The file is
     flattened onto the same navy as this cell, since Outlook gets alpha wrong. -->
<td align="center" bgcolor="#25293f" style="background-color: #25293f; padding: 24px; color: #ffffff">
<img src="${url.resourcesUrl}/img/sbomify-white-email.png" alt="sbomify" height="40" width="214" border="0" style="color: #ffffff; font-weight: 600; font-size: 20px">
</td>
</tr>
<tr>
<td align="center" bgcolor="#25293f" style="background-color: #25293f; color: #d3d4d9; padding: 0 24px 20px 24px; font-size: 14px">
The Security Artifact Hub
</td>
</tr>
<tr>
<td class="email-body">
<#nested>
<p>
Cheers,<br>
<strong>The sbomify Team</strong>
</p>
</td>
</tr>
<tr>
<td bgcolor="#eef0f4" align="center" style="background-color: #eef0f4; text-align: center; color: #6e7180; font-size: 14px" class="footer">
<p>Questions? We're here to help. <a href="https://sbomify.com/support/contact/">Get in touch</a></p>
<p>© sbomify. All rights reserved.</p>
</td>
</tr>
</table>
</td>
</tr>
</table>
</body>
</html>
</#macro>
