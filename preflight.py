"""Report deploy readiness without reading or displaying credential values."""
import json
import os
from pathlib import Path


def check(root=Path('.'), env=None):
    env = os.environ if env is None else env
    config = json.loads((root / 'candidate.json').read_text(encoding='utf-8-sig'))
    resume = root / config['master_resume_path']
    return {
        'resume_ready': resume.is_file() and bool(resume.read_text(encoding='utf-8-sig').strip()),
        'salary_floor_ready': isinstance(config.get('minimum_salary_inr_lpa'), (int, float)) and config['minimum_salary_inr_lpa'] > 0,
        'report_recipient_ready': bool(config.get('report_email')),
        'daily_application_limit': config.get('daily_application_limit'),
        'email_ready': all(bool(env.get(k)) for k in ('SMTP_HOST', 'SMTP_USERNAME', 'SMTP_PASSWORD')),
        'missing_email_secrets': [k for k in ('SMTP_HOST', 'SMTP_USERNAME', 'SMTP_PASSWORD') if not env.get(k)],
        'application_submission_ready': False,
        'application_reason': 'No supported authenticated submission integration is installed. Approval does not submit.',
        'expected_ctc_ready': config.get('expected_salary_inr_lpa') is not None,
        'paid_ai_enabled': bool(config.get('paid_ai_enabled')),
        'schedule': 'No schedule in public distribution; configure a private runner locally.',
    }


if __name__ == '__main__':
    result = check()
    Path('reports').mkdir(exist_ok=True)
    Path('reports/readiness.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    if not all(result[k] for k in ('resume_ready', 'salary_floor_ready', 'report_recipient_ready')):
        raise SystemExit('Required candidate setup is incomplete')

