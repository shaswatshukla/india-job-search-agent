"""Transparent, conservative keyword ranking; never a hiring probability."""
import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit


SKILLS = {
    'SQL': r'\bsql\b', 'Power BI': r'\bpower\s*bi\b', 'Python': r'\bpython\b',
    'Excel': r'\bexcel\b', 'Tableau': r'\btableau\b', 'Qlik': r'\bqlik\b',
    'Jira': r'\bjira\b', 'Confluence': r'\bconfluence\b', 'Azure DevOps': r'azure\s+devops|\bado\b',
    'Lucidchart': r'lucid\s*chart', 'ETL': r'\betl\b',
    'Salesforce': r'\bsalesforce\b', 'SAP Commerce': r'sap\s+commerce|\bhybris\b',
    'ARIS': r'\baris\b', 'IBM DOORS': r'\bdoors\b', 'Power Apps': r'power\s*apps',
    'Power Automate': r'power\s*automate', 'DAX': r'\bdax\b', 'Snowflake': r'\bsnowflake\b',
    'Alteryx': r'\balteryx\b', 'SAS': r'\bsas\b', 'R': r'\br\s+(?:programming|language)\b',
    'PeopleSoft': r'\bpeoplesoft\b', 'SAP': r'\bsap\b', 'ServiceNow': r'\bservicenow\b',
    'ERP': r'\berp\b', 'CRM': r'\bcrm\b', 'Figma': r'\bfigma\b', 'Coupa': r'\bcoupa\b',
    'Collibra': r'\bcollibra\b', 'Profisee': r'\bprofisee\b', 'Databricks': r'\bdatabricks\b',
}
RESPONSIBILITIES = {
    'Requirements': r'requirements?\s+(?:gather|elicit|analys|document)|business\s+requirements?|functional\s+(?:specifications?|requirements?)',
    'User stories': r'user\s+stories', 'Acceptance criteria': r'acceptance\s+criteria',
    'UAT': r'\buat\b|user\s+acceptance\s+test', 'Stakeholders': r'stakeholder',
    'Agile': r'\bagile\b|\bscrum\b', 'Process analysis': r'process\s+(?:mapping|improvement|analysis)|gap\s+analysis',
    'Reporting': r'\breporting\b|dashboards?', 'Data analysis': r'data\s+analy(?:sis|tics)|\banalytics\b',
    'Prioritisation': r'prioriti[sz]|\bbacklog\b',
}
DOMAINS = {'Retail': r'\bretail\b', 'Supply chain': r'supply[ -]chain|\blogistics\b|\binventory\b',
           'Marketing analytics': r'marketing\s+analytics|campaign\s+(?:analysis|optimisation|optimization)'}


def present(text, dictionary):
    return {name for name, pattern in dictionary.items() if re.search(pattern, text, re.I)}


def canonical_url(url):
    p = urlsplit(url or '')
    if p.scheme != 'https' or not p.netloc:
        return ''
    return urlunsplit((p.scheme, p.netloc.lower(), p.path.rstrip('/'), '', ''))


def job_key(job):
    value = canonical_url(job.get('job_url')) or '|'.join(str(job.get(k, '')).lower() for k in ('company', 'title', 'location'))
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def minimum_experience(text):
    results = []
    covered = []
    # Parse explicit years-of-experience phrases only; do not mistake education or tenure for a requirement.
    ranges = [r'\b(\d{1,2})\s*(?:[-–]|to)\s*\d{1,2}\s*\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:relevant\s+)?(?:work\s+)?experience',
              r'(?:total\s+)?experience\s*(?:expected)?\s*[:\-]?\s*(\d{1,2})\s*(?:years?|yrs?)?\s*(?:[-–]|to)\s*\d{1,2}']
    for pattern in ranges:
        for match in re.finditer(pattern, text, re.I):
            results.append(int(match.group(1)))
            covered.append(match.span())
    singles = [r'\b(\d{1,2})(?:\s+or\s+more)?\s*\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:(?:relevant|professional|work)\s+)?experience',
               r'\b(\d{1,2})\s*\+?\s*(?:years?|yrs?)\s+as\s+(?:a\s+)?(?:business|data|systems?)\s+analyst']
    for pattern in singles:
        for match in re.finditer(pattern, text, re.I):
            if not any(start <= match.start() < end for start, end in covered):
                results.append(int(match.group(1)))
    return max(results) if results else None


def salary_assessment(job, config):
    comp = job.get('compensation', {})
    if comp.get('currency') == 'INR' and comp.get('period', '').upper() in ('YEARLY', 'ANNUAL'):
        floor = float(config['minimum_salary_inr_lpa']) * 100000
        maximum, minimum = float(comp.get('max') or 0), float(comp.get('min') or 0)
        if maximum > 0 and maximum < floor:
            return 'below_minimum'
        if minimum >= floor:
            return 'meets_minimum'
        if maximum >= floor:
            return 'range_overlaps_minimum'
    return 'undisclosed_or_unverified'


def assess(job, resume, config, now=None):
    now = now or datetime.now(timezone.utc)
    job = dict(job)
    job['job_key'] = job_key(job)
    text = '\n'.join(job.get(k, '') for k in ('description', 'qualifications', 'additional'))
    candidate_skills = present(resume, SKILLS)
    mentioned = present(text, SKILLS)
    matched = sorted(mentioned & candidate_skills)
    missing = sorted(mentioned - candidate_skills)
    required_resp = present(text, RESPONSIBILITIES)
    supported_resp = required_resp & present(resume, RESPONSIBILITIES)
    minimum = minimum_experience(job.get('qualifications', '') + '\n' + job.get('description', ''))
    gaps, reject = [], []
    junior = re.search(r'\b([0-2])\s*[-–]\s*([1-2])\s*years?\s+of\s+experience', text, re.I)
    if junior and config['experience_years'] > int(junior.group(2)):
        reject.append('Role targets at most 2 years; candidate has 6+ years across roles.')
    if re.search(r'years?\s+(?:as\s+(?:a\s+)?|of\s+(?:experience\s+(?:as|in)\s+)?)(?:business|data)\s+analyst', text, re.I):
        gaps.append('Role-specific years must be verified separately; 6+ total years is not 6+ years holding a Business Analyst title.')
    if minimum is not None and minimum > config['experience_years']:
        reject.append('JD states at least ' + str(minimum) + ' years; confirmed profile has 6+ years across roles.')
    # Optional skills remain gaps, not automatic disqualifiers. Explicit required technology stays held.
    mandatory_missing = []
    for line in text.splitlines():
        if re.search(r'\b(required|mandatory|must|hands[- ]on|proven|strong expertise|experience with)\b', line, re.I) and not re.search(r'\b(preferred|plus|bonus|desirable)\b', line, re.I):
            line_skills = present(line, SKILLS)
            if not (re.search(r'\bor\b|such as|e\.g\.', line, re.I) and line_skills & candidate_skills):
                mandatory_missing.extend(line_skills - candidate_skills)
    mandatory_domains = []
    specialised = {'Payments/cards': r'\bpayments?\b|card\s+(?:scheme|processing)|issuing|acquiring',
                   'Banking/financial services': r'\bbanking\b|financial(?:\s+and\s+corporate)?\s+services', 'Insurance': r'\binsurance\b|\bactuarial\b',
                   'Healthcare/pharma': r'\bhealthcare\b|\bpharma\b|\bpbm\b'}
    for line in text.splitlines():
        if re.search(r'years?\s+(?:of\s+)?experience\s+in|proven experience|strong expertise|deep understanding|mandatory|having worked', line, re.I) and not re.search(r'\b(preferred|plus|bonus|desirable)\b', line, re.I):
            for label, pattern in specialised.items():
                if re.search(pattern, line, re.I) and not re.search(pattern, resume, re.I):
                    mandatory_domains.append(label)
    gaps.extend('Not evidenced in resume: ' + value for value in missing)
    if mandatory_missing:
        gaps.append('Explicit required skills need review: ' + ', '.join(sorted(set(mandatory_missing))))
    if mandatory_domains:
        gaps.append('Required domain experience not evidenced: ' + ', '.join(sorted(set(mandatory_domains))))
    if re.search(r'\b(?:chartered accountant|CMA final|CA final|MBA\s*\(?finance)\b', job.get('qualifications', ''), re.I):
        reject.append('Finance/accountancy qualification is not evidenced in the resume.')
    if not mentioned:
        gaps.append('No recognised technical requirements extracted; review the full JD.')
    if minimum is None:
        gaps.append('Experience requirement not confidently extracted.')
    domain_matches = sorted(present(text, DOMAINS) & present(resume, DOMAINS))
    breakdown = dict(skills=round(40 * len(matched) / len(mentioned), 1) if mentioned else 20,
                     responsibilities=round(30 * len(supported_resp) / len(required_resp), 1) if required_resp else 0,
                     experience=20 if minimum is not None and minimum <= config['experience_years'] else 10,
                     domain=10 if domain_matches else 5)
    score = round(sum(breakdown.values()))
    if mandatory_missing or mandatory_domains:
        score = min(score, 60)
    salary = salary_assessment(job, config)
    if salary == 'below_minimum':
        reject.append('Published annual pay is below ₹15 LPA.')
    age = None
    if job.get('posted_at'):
        try:
            posted = datetime.fromisoformat(job['posted_at'].replace('Z', '+00:00'))
            if posted.tzinfo is None:
                posted = posted.replace(tzinfo=timezone.utc)
            age = (now - posted).days
            if age < -1:
                reject.append('Posting date is in the future; source needs review.')
            elif age > config.get('max_posting_age_days', 90):
                reject.append('Posting is older than the configured freshness window.')
        except ValueError:
            gaps.append('Posting date could not be parsed.')
    if age is None:
        gaps.append('Posting freshness is unverified.')
    if job.get('application_deadline'):
        try:
            deadline = datetime.fromisoformat(job['application_deadline'].replace('Z', '+00:00'))
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            if deadline < now:
                reject.append('Application deadline has passed.')
        except ValueError:
            gaps.append('Application deadline could not be parsed.')
    status = 'rejected' if reject else ('shortlisted' if score >= config['minimum_match_score'] else 'lower_match')
    if status == 'shortlisted' and salary != 'meets_minimum':
        gaps.append('Salary must be confirmed at ₹15 LPA or above before submission.')
    job.update(score=score, score_breakdown=breakdown, matched_skills=matched,
               matched_responsibilities=sorted(supported_resp), matched_domains=domain_matches,
               gaps=gaps, rejection_reasons=reject, salary_status=salary, minimum_experience_years=minimum,
               posting_age_days=age, status=status, application_status='not_submitted',
               submission_blockers=['No authenticated application integration'] +
                 ([] if salary == 'meets_minimum' else ['Salary floor not verified']),
               evidence_method='Keyword ranking (40 skills, 30 responsibilities, 20 experience, 10 domain); not an ATS score or interview probability. Mandatory gaps may cap score.')
    return job


def deduplicate(jobs):
    output, urls, fingerprints, requisitions = [], set(), set(), set()
    for job in jobs:
        url = canonical_url(job.get('job_url'))
        fingerprint = tuple(' '.join(str(job.get(k, '')).lower().split()) for k in ('company', 'title', 'location'))
        requisition = (str(job.get('company', '')).lower(), str(job.get('requisition_id') or ''))
        if (url and url in urls) or fingerprint in fingerprints or (requisition[1] and requisition in requisitions):
            continue
        urls.add(url)
        fingerprints.add(fingerprint)
        if requisition[1]:
            requisitions.add(requisition)
        output.append(job)
    return output


def tailored_text(resume, job):
    """Reorder verified skills only; preserve all identity, history and claims."""
    lines = resume.splitlines()
    try:
        start = lines.index('TECHNICAL SKILLS') + 1
        end = lines.index('PROFESSIONAL EXPERIENCE')
    except ValueError:
        return resume, ['No safe skill section found; original resume retained.']
    skill_lines = lines[start:end]
    jd = job['description'] + '\n' + job.get('qualifications', '')
    wanted = present(jd, SKILLS) | present(jd, RESPONSIBILITIES) | present(jd, DOMAINS)
    def relevance(line):
        return len(wanted & (present(line, SKILLS) | present(line, RESPONSIBILITIES) | present(line, DOMAINS)))
    ordered = sorted(skill_lines, key=relevance, reverse=True)
    # No new words are inserted into the resume; no factual claims are removed.
    return '\n'.join(lines[:start] + ordered + lines[end:]) + '\n', [
        'Reordered existing skill groups to emphasise JD relevance; all other resume facts and wording preserved.',
        'Draft for review; missing skills are documented separately and have not been added to the resume.']

