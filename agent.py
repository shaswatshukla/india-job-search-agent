"""Free daily discovery and resume drafts. Submission awaits authenticated integrations."""
import base64
import html
import json
import os
import re
import urllib.error
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from discovery import discover
from matching import assess, deduplicate, tailored_text
from transport import github_request, update_review_issue, send_report
from exports import export_run

BOARDS = ['LinkedIn', 'Naukri', 'Indeed', 'Foundit', 'Shine', 'Instahyre', 'Cutshort', 'Wellfound']
STATE_PATH = 'state/latest.json'


def blockers(config, env):
    pending = []
    for key, label in [('minimum_salary_inr_lpa', 'Minimum acceptable CTC'), ('work_eligible_india', 'India work eligibility'), ('willing_to_relocate', 'Relocation preference')]:
        if config.get(key) is None:
            pending.append(label + ' needs your answer in candidate.json.')
    if config.get('expected_salary_inr_lpa') is None:
        pending.append('Expected CTC is unspecified: hold only applications requiring a numeric answer.')
    pending.append('Paid AI disabled while budget is undecided. Free keyword matching and factual resume drafts are active.')
    if not email_connected(env):
        pending.append('Cloud email unavailable: add SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD to Actions secrets.')
    pending.append('Applications cannot be submitted yet: no supported authenticated application integration is connected.')
    return pending


def email_connected(env):
    return all(env.get(k) for k in ['SMTP_HOST', 'SMTP_USERNAME', 'SMTP_PASSWORD'])


def load_state():
    path = Path(STATE_PATH)
    return (json.loads(path.read_text()) if path.exists() else {'jobs': {}, 'emails': {}}), None


def save_state(state, sha):
    path = Path(STATE_PATH)
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding='utf-8')
    return None


def parse_review_commands(comments, owner, known_keys):
    commands = {}
    for comment in comments:
        if comment.get('user', {}).get('login', '').lower() != owner.lower():
            continue
        for line in comment.get('body', '').splitlines():
            match = re.fullmatch(r'/(applied|skip|approve) ([0-9a-f]{16})', line.strip())
            if match and match.group(2) in known_keys:
                commands[match.group(2)] = match.group(1)
    return commands


def read_review(state):
    return {}  # Public distribution keeps all candidate history local.


def safe(value):
    return html.escape(str(value)).replace('|', '\\|').replace('\n', ' ').replace('@', '&#64;')


def safe_url(value):
    if not value or not value.startswith('https://'):
        return ''
    return value.replace(')', '%29').replace('(', '%28').replace('\n', '').replace(' ', '%20')


def prepare_draft(resume, job, output):
    text, changes = tailored_text(resume, job)
    base = output / 'resumes' / job['job_key']
    base.parent.mkdir(parents=True, exist_ok=True)
    base.with_suffix('.txt').write_text(text, encoding='utf-8')
    content = '<!doctype html><meta charset="utf-8"><title>Resume review</title><style>body{font:12pt Arial;max-width:800px;margin:32px auto;line-height:1.5}pre{white-space:pre-wrap;font:inherit}@media print{body{margin:0;font-size:10pt}}</style><pre>' + html.escape(text) + '</pre>'
    base.with_suffix('.html').write_text(content, encoding='utf-8')
    base.with_suffix('.changes.json').write_text(json.dumps(changes, indent=2), encoding='utf-8')
    (output / (job['job_key'] + '.jd.txt')).write_text(job['description'] + '\n\nQualifications\n' + job['qualifications'], encoding='utf-8')
    return str(base.with_suffix('.txt'))


def build_report(now, config, jobs, selected, coverage, pending, run_url):
    shortlisted = sum(j['status'] == 'shortlisted' for j in jobs)
    rejected = sum(j['status'] == 'rejected' for j in jobs)
    report = '# India Business Analyst job report\n\n' + now.isoformat() + '\n\n'
    report += ('**Live descriptions evaluated: %s. Strong keyword matches: %s. Rejected: %s. Resume drafts: %s. Agent-submitted applications: 0.**\n\n') % (len(jobs), shortlisted, rejected, len(selected))
    report += 'Target: 20 relevant applications/day. No submission integration is connected, so the application target has not been met. Keyword matching is not an ATS score or interview probability. Review full JDs for unrecognised domain requirements. Undisclosed salary does not meet the confirmed â‚¹15 LPA floor.\n\n'
    report += '## Jobs to review\n\n'
    if not selected:
        report += 'No jobs met the current filter. No weak matches were promoted to fill the quota.\n\n'
    for job in selected:
        report += '### ' + safe(job['company']) + ' â€” ' + safe(job['title']) + '\n\n'
        report += '- Job key: `' + job['job_key'] + '`\n'
        report += '- ' + safe(job['location']) + '; source: ' + safe(job['source']) + '; posted: ' + safe(job['posted_at']) + '\n'
        report += '- Keyword match: ' + str(job['score']) + '/100; salary: ' + safe(job['salary_status']) + '\n'
        report += '- Evidence: ' + safe(', '.join(job['matched_skills'] + job['matched_responsibilities'] + job['matched_domains'])) + '\n'
        report += '- Gaps: ' + safe('; '.join(job['gaps']) or 'Review the full JD.') + '\n'
        report += '- Status: ' + safe(job['application_status']) + '; blockers: ' + safe('; '.join(job['submission_blockers'])) + '\n'
        report += '- [View job / apply](' + safe_url(job['application_url']) + ')\n'
        report += '- Resume version: `' + job['job_key'] + '.txt`; download from this runâ€™s artifact.\n\n'
    near = [j for j in jobs if j['status'] == 'lower_match'][:5]
    if near:
        report += '## Lower matches for optional review\n\n'
        for job in near:
            report += '- ' + safe(job['company']) + ': [' + safe(job['title']) + '](' + safe_url(job['application_url']) + ') â€” ' + str(job['score']) + '/100; ' + safe('; '.join(job['gaps'])) + '\n'
        report += '\nThese are not counted as strong matches or applications.\n\n'
    report += '## Sources\n\n'
    for source in coverage:
        report += '- ' + safe(source['source']) + ': ' + safe(source['status']) + '; ' + safe(json.dumps({k: v for k, v in source.items() if k not in ('source', 'status')})) + '\n'
    report += '\n## Requested job-board coverage\n\n'
    for board in BOARDS:
        reason = 'No cloud search/application connector configured.' if board != 'LinkedIn' else 'Direct web automation prohibited by LinkedIn; supported discovery/employer application paths needed.'
        report += '- ' + board + ': blocked. ' + reason + '\n'
    report += '\n## Blockers and review instructions\n\n' + '\n'.join('- ' + safe(item) for item in pending)
    report += '\n\nIn the review issue, the repository owner can comment `/skip JOB_KEY`, `/applied JOB_KEY`, or `/approve JOB_KEY`. Use the 16-character key above. Applied records that you completed it yourself, not agent-confirmed submission. Approval keeps it queued; it does not submit it. Unknown/third-party commands are ignored.\n'
    report += '\n[Download drafts, JDs and complete job records from this run](' + run_url + ')\n' if run_url else '\nReports and drafts saved locally.\n'
    return report


def main():
    config = json.loads(Path('candidate.json').read_text(encoding='utf-8-sig'))
    resume = Path(config['master_resume_path']).read_text(encoding='utf-8-sig')
    if not resume.strip() or config.get('minimum_salary_inr_lpa') is None:
        raise RuntimeError('Readable resume and salary floor required for matching')
    now = datetime.now(ZoneInfo('Asia/Kolkata'))
    date = now.strftime('%Y-%m-%d')
    run_url = 'https://github.com/' + os.environ['GITHUB_REPOSITORY'] + '/actions/runs/' + os.environ['GITHUB_RUN_ID'] if os.environ.get('GITHUB_RUN_ID') else ''
    output = Path('reports')
    output.mkdir(exist_ok=True)
    state, state_sha = load_state()
    for key, command in read_review(state).items():
        state['jobs'][key]['review_status'] = {'skip': 'skipped_by_user', 'applied': 'user_reported_submitted', 'approve': 'approved_pending_integration'}[command]
    raw, coverage = discover(config)
    jobs = [assess(job, resume, config, now) for job in deduplicate(raw)]
    jobs.sort(key=lambda j: (-j['score'], j['posting_age_days'] if j['posting_age_days'] is not None else 99999))
    selected = []
    for job in jobs:
        history = state['jobs'].get(job['job_key'], {})
        review = history.get('review_status', 'pending_review')
        job['review_status'] = review
        if review == 'user_reported_submitted':
            job['application_status'] = review
        if job['status'] == 'shortlisted' and review not in ('skipped_by_user', 'user_reported_submitted') and len(selected) < config['daily_application_limit']:
            job['resume_path'] = prepare_draft(resume, job, output)
            selected.append(job)
        state['jobs'][job['job_key']] = dict(first_seen=history.get('first_seen', date), last_seen=date, company=job['company'], title=job['title'], url=job['job_url'], review_status=review, application_status=job['application_status'], last_score=job['score'])
    export_run(output, jobs, selected, state, now.isoformat())
    (output / 'jobs.json').write_text(json.dumps(jobs, indent=2, ensure_ascii=False), encoding='utf-8')
    report = build_report(now, config, jobs, selected, coverage, blockers(config, os.environ), run_url)
    # Write output before external actions, so a transport failure still leaves a report.
    report_path = output / (date + '.md')
    report_path.write_text(report, encoding='utf-8')
    issue_url = None
    if issue_url:
        state['review_issue_number'] = int(issue_url.rsplit('/', 1)[-1])
        report += '\nReview queue: ' + issue_url + '\n'
    state['last_run'] = dict(date=date, run_url=run_url, evaluated=len(jobs), strong_matches=len(selected), agent_submitted=0)
    state_sha = save_state(state, state_sha)
    email = state['emails'].get(date, {})
    email_status = email.get('status', 'Not sent: email credentials missing')
    errors = []
    if email.get('status') in ('attempting', 'accepted_by_smtp', 'sent_via_connector', 'submission_unknown'):
        email_status += '; no automatic repeat â€” reconcile transport before retrying'
    elif email_connected(os.environ):
        state['emails'][date] = dict(status='attempting', run_url=run_url)
        state_sha = save_state(state, state_sha)
        try:
            email_status = send_report(config['report_email'], report, date)
            state['emails'][date]['status'] = 'accepted_by_smtp'
        except Exception as error:
            email_status = 'Failed or uncertain: ' + type(error).__name__ + '; reconcile before retrying'
            state['emails'][date]['status'] = 'submission_unknown'
            errors.append('Email transport')
        state_sha = save_state(state, state_sha)
    report += '\nEmail: ' + email_status + '\n'
    report_path.write_text(report, encoding='utf-8')
    print('Evaluated %s descriptions; prepared %s drafts; agent submissions: 0.' % (len(jobs), len(selected)))
    if errors:
        raise SystemExit('; '.join(errors))


if __name__ == '__main__':
    main()


