"""Portable daily exports and append-only held-application journal."""
import csv
import hashlib
import json


def export_run(output, jobs, selected, state, timestamp):
    fields = ['company', 'title', 'location', 'source', 'job_url', 'application_url',
              'posted_at', 'score', 'salary_status', 'status', 'application_status',
              'gaps', 'rejection_reasons', 'resume_path']
    with (output / 'jobs.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for job in jobs:
            row = {k: job.get(k, '') for k in fields}
            row = {k: '; '.join(v) if isinstance(v, list) else v for k, v in row.items()}
            # Spreadsheet formula injection protection for externally supplied fields.
            row = {k: "'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@')) else v for k, v in row.items()}
            writer.writerow(row)
    events = state.setdefault('application_events', [])
    known = {event['event_id'] for event in events}
    for job in selected:
        identity = timestamp[:10] + ':' + job['job_key'] + ':held'
        event_id = hashlib.sha256(identity.encode()).hexdigest()
        if event_id in known:
            continue
        events.append(dict(event_id=event_id, run_id=timestamp[:10], job_key=job['job_key'],
            company=job['company'], title=job['title'], location=job['location'], board=job['source'],
            job_url=job['job_url'], application_url=job['application_url'],
            requisition_id=job.get('requisition_id'), score=job['score'],
            match_evidence=job['matched_skills'] + job['matched_responsibilities'],
            gaps=job['gaps'], resume_path=job.get('resume_path'),
            jd_path=job['job_key'] + '.jd.txt', answers={}, status='held', timestamp_ist=timestamp,
            confirmation=None, reason='; '.join(job['submission_blockers']),
            next_action='Resolve listed requirements and supported authenticated application access'))
        known.add(event_id)
    (output / 'applications.jsonl').write_text(''.join(json.dumps(event, ensure_ascii=False) + '\n' for event in events), encoding='utf-8')

