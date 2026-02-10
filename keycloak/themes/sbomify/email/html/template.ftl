<#macro emailLayout>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <title>${msg("emailTitle", realmName)}</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f8fafc;
        }

        .email-container {
            background-color: #ffffff;
            border-radius: 8px;
            padding: 40px;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }

        .header {
            text-align: center;
            margin-bottom: 32px;
            padding-bottom: 24px;
            border-bottom: 1px solid #e2e8f0;
        }

        .logo {
            margin-bottom: 8px;
        }

        .logo img {
            height: 40px;
            max-width: 200px;
        }

        .logo-text {
            font-size: 28px;
            font-weight: bold;
            color: #4059d0;
        }

        .tagline {
            color: #64748b;
            font-size: 14px;
        }

        h1 {
            color: #1e293b;
            font-size: 24px;
            margin-bottom: 16px;
            font-weight: 600;
        }

        p {
            margin: 16px 0;
            color: #475569;
        }

        .button {
            display: inline-block;
            padding: 12px 24px;
            background-color: #4059d0;
            color: white !important;
            text-decoration: none;
            border-radius: 6px;
            margin: 16px 0;
            font-weight: 500;
            text-align: center;
        }

        .button:hover {
            background-color: #334ba6;
        }

        .text-secondary {
            color: #64748b;
            font-size: 14px;
        }

        a {
            color: #4059d0;
            text-decoration: none;
        }

        .footer {
            margin-top: 40px;
            padding-top: 24px;
            border-top: 1px solid #e2e8f0;
            text-align: center;
            color: #64748b;
            font-size: 14px;
        }

        .expiry-notice {
            background-color: #fef3c7;
            border: 1px solid #f59e0b;
            border-radius: 4px;
            padding: 12px;
            margin: 16px 0;
            font-size: 14px;
            color: #92400e;
        }

        @media only screen and (max-width: 600px) {
            body {
                padding: 10px;
            }

            .email-container {
                padding: 20px;
            }

            h1 {
                font-size: 20px;
            }

            .button {
                display: block;
                text-align: center;
                margin: 16px 0;
            }
        }
    </style>
</head>
<body>
    <div class="email-container">
        <div class="header">
            <div class="logo">
                <img src="${url.resourcesUrl}/img/logo.svg" alt="sbomify" height="40" style="max-width: 200px;">
            </div>
            <div class="tagline">The Security Artifact Hub</div>
        </div>
        <#nested>
        <p>
            Regards,<br>
            <strong>The sbomify Team</strong>
        </p>
        <div class="footer">
            <p>
                Need help? <a href="https://sbomify.com/support/contact/">Contact support</a> |
                <a href="https://sbomify.com/">Documentation</a>
            </p>
            <p>© sbomify. All rights reserved.</p>
        </div>
    </div>
</body>
</html>
</#macro>
