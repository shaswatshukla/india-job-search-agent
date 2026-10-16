import json
import os
import smtplib
import ssl
import urllib.request
from email.message import EmailMessage

def github_request(path, method='GET', body=None):
    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        raise RuntimeError('No GitHub token')
    request = urllib.request.Request('https://api.github.com/' + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                 'Content-Type': 'application/json', 'User-Agent': 'job-search-setup'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def update_review_issue(report):
    return None


def send_report(recipient, report, date):
    env = os.environ
    if not all(env.get(k) for k in ['SMTP_HOST', 'SMTP_USERNAME', 'SMTP_PASSWORD']):
        return 'Not sent: email credentials missing'
    message = EmailMessage()
    message['From'] = env['SMTP_USERNAME']
    message['To'] = recipient
    message['Subject'] = 'India Business Analyst job report - ' + date
    message.set_content(report)
    # Only encrypted SMTP is supported. Never fall back to plaintext login.
    port = int(env.get('SMTP_PORT') or '465')
    with smtplib.SMTP_SSL(env['SMTP_HOST'], port, context=ssl.create_default_context(), timeout=30) as smtp:
        smtp.login(env['SMTP_USERNAME'], env['SMTP_PASSWORD'])
        refused = smtp.send_message(message)
        if refused:
            raise RuntimeError('Recipient refused')
    return 'Accepted by SMTP server; inbox delivery not independently verified'



