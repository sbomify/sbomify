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
            font-size: 28px;
            font-weight: bold;
            color: #2563eb;
            margin-bottom: 8px;
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
            background-color: #2563eb;
            color: white !important;
            text-decoration: none;
            border-radius: 6px;
            margin: 16px 0;
            font-weight: 500;
            text-align: center;
        }

        .button:hover {
            background-color: #1d4ed8;
        }

        .text-secondary {
            color: #64748b;
            font-size: 14px;
        }

        a {
            color: #2563eb;
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
            <div class="logo">sbomify</div>
            <div class="tagline">The Security Artifact Hub</div>
        </div>
        <#nested>
        <div class="footer">
            <p>sbomify. All rights reserved.</p>
        </div>
    </div>
</body>
</html>
</#macro>
