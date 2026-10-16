import json
import tempfile
import unittest
from pathlib import Path
from exports import export_run
from preflight import check
from test_agent import example, CONFIG, RESUME, NOW
from matching import assess


class PackageTests(unittest.TestCase):
    def test_junior_role_is_not_promoted_by_keyword_score(self):
        job = assess(example(qualifications='0-2 years of experience in reporting and analytics.'), RESUME, CONFIG, NOW)
        self.assertEqual(job['status'], 'rejected')

    def test_export_journal_is_idempotent_and_preserves_prior_events(self):
        job = assess(example(), RESUME, CONFIG, NOW)
        job['resume_path'] = 'resumes/example.txt'
        state = {'application_events': [{'event_id': 'old', 'status': 'submission_unknown'}]}
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            export_run(output, [job], [job], state, NOW.isoformat())
            export_run(output, [job], [job], state, NOW.isoformat())
            self.assertEqual(len(state['application_events']), 2)
            self.assertEqual(state['application_events'][0]['status'], 'submission_unknown')
            self.assertIsNone(state['application_events'][1]['confirmation'])
            self.assertTrue((output / 'jobs.csv').is_file())

    def test_readiness_never_displays_secret_values(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'resume.txt').write_text('Verified resume')
            (root / 'candidate.json').write_text(json.dumps(dict(master_resume_path='resume.txt', minimum_salary_inr_lpa=15, report_email='a@example.com')))
            result = check(root, {'SMTP_HOST':'host', 'SMTP_USERNAME':'user', 'SMTP_PASSWORD':'secret-value'})
            self.assertTrue(result['email_ready'])
            self.assertNotIn('secret-value', json.dumps(result))
            self.assertFalse(result['application_submission_ready'])

