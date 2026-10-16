"""Read public postings only. No account access, scraping, or paid services."""
import json
import re
import urllib.parse
import urllib.request
from html import unescape
from html.parser import HTMLParser


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_endtag(self, tag):
        if tag in ('p', 'li', 'div', 'br', 'h1', 'h2', 'h3'):
            self.parts.append('\n')


def plain_html(value):
    parser = TextParser()
    parser.feed(value or '')
    return '\n'.join(' '.join(line.split()) for line in ''.join(parser.parts).splitlines() if line.strip())


def get_json(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in ('api.smartrecruiters.com', 'remotive.com', 'boards-api.greenhouse.io', 'api.lever.co'):
        raise ValueError('Unapproved feed host')
    request = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'PersonalJobSearch/1.0'})
    with urllib.request.urlopen(request, timeout=25) as response:
        data = response.read(5_000_001)
    if len(data) > 5_000_000:
        raise ValueError('Feed exceeds size limit')
    return json.loads(data)


ROLE = re.compile(r'business\s+(?:systems\s+)?analyst|business\s+analysis|business\s+intelligence\s+analyst|supply[ -]chain\s+analyst|data\s+analyst', re.I)


def relevant_title(title):
    return bool(ROLE.search(title)) and not re.search(r'\b(intern|internship|trainee|fresher|graduate programme)\b', title, re.I)


def india_eligible_location(location):
    if re.search(r'\b(united states|usa|canada|united kingdom|uk only|emea only|europe only)\b', location, re.I):
        return False
    return bool(re.search(r'\b(india|worldwide|global|bengaluru|bangalore|mumbai|pune|hyderabad|chennai|gurugram|gurgaon|noida|new delhi|delhi|kolkata|lucknow|ahmedabad)\b', location, re.I))


def greenhouse(board):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', board):
        raise ValueError('Invalid board token')
    base = 'https://boards-api.greenhouse.io/v1/boards/' + board + '/jobs'
    entries = get_json(base).get('jobs', [])
    jobs, failures = [], []
    for entry in entries:
        location = entry.get('location', {}).get('name', '')
        if not relevant_title(entry.get('title', '')) or not india_eligible_location(location):
            continue
        try:
            detail = get_json(base + '/' + str(int(entry['id'])))
            # Greenhouse sometimes entity-encodes its HTML before embedding it in JSON.
            description = plain_html(unescape(detail.get('content', '')))
            if not description:
                continue
            deadline = detail.get('application_deadline')
            jobs.append(dict(source='Greenhouse/' + board, source_id=str(entry['id']), company=detail.get('company_name', board),
                title=detail['title'], location=location, country='in-eligible', remote='remote' in location.lower(),
                posted_at=detail.get('first_published'), description=description, qualifications='', additional='',
                compensation={}, job_url=detail.get('absolute_url') or entry['absolute_url'],
                application_url=detail.get('absolute_url') or entry['absolute_url'], requisition_id=detail.get('requisition_id') or detail.get('internal_job_id'),
                application_deadline=deadline, live_evidence='Present in public Greenhouse job board and detail endpoint'))
        except Exception as error:
            failures.append(str(entry['id']) + ': ' + type(error).__name__)
    return jobs, dict(source='Greenhouse/' + board, status='partially searched' if failures else 'searched',
                     examined=len(entries), relevant=len(jobs), failures=failures)


def lever(company):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', company):
        raise ValueError('Invalid company identifier')
    base = 'https://api.lever.co/v0/postings/' + company
    jobs, examined, complete = [], 0, False
    for offset in range(0, 1000, 100):
        entries = get_json(base + '?mode=json&limit=100&skip=' + str(offset))
        if not isinstance(entries, list):
            raise ValueError('Unexpected Lever feed format')
        examined += len(entries)
        for entry in entries:
            location = entry.get('categories', {}).get('location', '')
            if not relevant_title(entry.get('text', '')) or not india_eligible_location(location):
                continue
            description = entry.get('descriptionPlain', '') + '\n' + '\n'.join(
                section.get('text', '') + '\n' + plain_html(section.get('content', '')) for section in entry.get('lists', []))
            description += '\n' + entry.get('additionalPlain', '')
            jobs.append(dict(source='Lever/' + company, source_id=entry['id'], company=company, title=entry['text'],
                location=location, country='in-eligible', remote=entry.get('workplaceType') == 'remote', posted_at=None,
                description=description, qualifications='', additional='', compensation={},
                job_url=entry['hostedUrl'], application_url=entry['applyUrl'], requisition_id=None,
                live_evidence='Present in public Lever postings feed; posting date unavailable'))
        if len(entries) < 100:
            complete = True
            break
    return jobs, dict(source='Lever/' + company, status='searched' if complete else 'partially searched',
                     examined=examined, relevant=len(jobs), pagination_complete=complete, failures=[])


def smartrecruiters(company):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', company):
        raise ValueError('Invalid company identifier')
    base = 'https://api.smartrecruiters.com/v1/companies/' + company + '/postings'
    jobs = []
    failures = []
    examined = 0
    complete = False
    for offset in range(0, 300, 100):
        query = urllib.parse.urlencode(dict(country='in', q='analyst', limit=100, offset=offset, destination='PUBLIC'))
        listing = get_json(base + '?' + query)
        entries = listing.get('content', [])
        examined += len(entries)
        for entry in entries:
            if not relevant_title(entry.get('name', '')):
                continue
            posting_id = str(entry['id'])
            if not re.fullmatch(r'[A-Za-z0-9-]+', posting_id):
                continue
            try:
                detail = get_json(base + '/' + posting_id)
                if detail.get('active') is not True:
                    continue
                location = detail.get('location', {})
                if location.get('country', '').lower() != 'in':
                    continue
                sections = detail.get('jobAd', {}).get('sections', {})
                job = dict(
                    source='SmartRecruiters/' + company, source_id=posting_id,
                    company=detail.get('company', {}).get('name', company), title=detail['name'],
                    location=location.get('fullLocation') or ', '.join(filter(None, [location.get('city'), 'India'])),
                    country='in', remote=bool(location.get('remote')), posted_at=detail.get('releasedDate'),
                    description=plain_html(sections.get('jobDescription', {}).get('text', '')),
                    qualifications=plain_html(sections.get('qualifications', {}).get('text', '')),
                    additional=plain_html(sections.get('additionalInformation', {}).get('text', '')),
                    compensation=detail.get('compensation') or {},
                    application_url=detail.get('applyUrl') or detail.get('postingUrl'),
                    job_url=detail.get('postingUrl'), requisition_id=detail.get('refNumber'),
                    live_evidence='Listed by public API; active=true',
                )
                if job['description'] and job['application_url']:
                    jobs.append(job)
            except Exception as error:
                failures.append(posting_id + ': ' + type(error).__name__)
        if offset + len(entries) >= listing.get('totalFound', 0) or not entries:
            complete = True
            break
    return jobs, dict(source='SmartRecruiters/' + company, status='searched' if complete and not failures else 'partially searched',
                     examined=examined, relevant=len(jobs), failures=failures, pagination_complete=complete)


def remotive():
    feed = get_json('https://remotive.com/api/remote-jobs?search=analyst')
    entries = feed.get('jobs', [])
    jobs = []
    for job in entries:
        if not relevant_title(job.get('title', '')):
            continue
        location = job.get('candidate_required_location', '')
        # Remote alone is not evidence that a candidate in India is eligible.
        if not re.search(r'\b(india|worldwide|anywhere|global)\b', location, re.I):
            continue
        jobs.append(dict(source='Remotive', source_id=str(job['id']), company=job['company_name'],
                         title=job['title'], location=location, country='in-eligible', remote=True,
                         posted_at=job.get('publication_date'), description=plain_html(job.get('description', '')),
                         qualifications='', additional='', compensation={}, salary_text=job.get('salary', ''),
                         job_url=job['url'], application_url=job['url'], requisition_id=None,
                         live_evidence='Present in Remotive public feed (24-hour delay); eligibility/location needs review'))
    return jobs, dict(source='Remotive', status='searched', examined=len(entries), relevant=len(jobs), failures=[])


def discover(config):
    jobs, coverage = [], []
    for key, adapter, label in [('greenhouse_boards', greenhouse, 'Greenhouse/'), ('lever_companies', lever, 'Lever/')]:
        for company in config.get(key, []):
            try:
                found, status = adapter(company)
                jobs.extend(found)
                coverage.append(status)
            except Exception as error:
                coverage.append(dict(source=label + company, status='blocked', reason=type(error).__name__))
    for company in config.get('smartrecruiters_companies', []):
        try:
            found, status = smartrecruiters(company)
            jobs.extend(found)
            coverage.append(status)
        except Exception as error:
            coverage.append(dict(source='SmartRecruiters/' + company, status='blocked', reason=type(error).__name__))
    if config.get('include_remotive', True):
        try:
            found, status = remotive()
            jobs.extend(found)
            coverage.append(status)
        except Exception as error:
            coverage.append(dict(source='Remotive', status='blocked', reason=type(error).__name__))
    return jobs, coverage

