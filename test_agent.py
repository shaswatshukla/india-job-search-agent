import copy
import json
import tempfile
import unittest
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from agent import blockers, parse_review_commands, prepare_draft
from discovery import smartrecruiters, remotive, greenhouse, lever, relevant_title, plain_html, india_eligible_location
from matching import assess, deduplicate, minimum_experience, salary_assessment, tailored_text

CONFIG = dict(minimum_salary_inr_lpa=15, minimum_match_score=75, experience_years=6, max_posting_age_days=90,
              expected_salary_inr_lpa=None, work_eligible_india=True, willing_to_relocate=True, paid_ai_enabled=False)
RESUME = 'EXAMPLE CANDIDATE\nBusiness Analyst\nPROFESSIONAL SUMMARY\nBusiness analysis, retail and supply chain analytics.\nTECHNICAL SKILLS\nDomain: Retail, inventory, supply chain\nData: SQL, Power BI, Python, Excel\nBA: Requirements gathering, user stories, acceptance criteria, stakeholder management, UAT, Agile, gap analysis\nPROFESSIONAL EXPERIENCE\nBusiness Analyst, Example Retailer\'s, May 2024 - Feb 2026\nCut overdue value from Â£1.93M to Â£0.25M.\nEDUCATION\nMSc Data Analytics\n'
NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)


def example(**changes):
    job = dict(company='Example Employer', title='Business Analyst', location='Pune, India', country='in',
               source='SmartRecruiters/example', source_id='123', posted_at='2026-10-01T00:00:00Z',
               description='Gather business requirements, write user stories and acceptance criteria, manage stakeholders, perform UAT in Agile. SQL and Power BI dashboards for retail inventory.',
               qualifications='4-6 years of relevant experience.', additional='', compensation={},
               job_url='https://jobs.smartrecruiters.com/example/123', application_url='https://jobs.smartrecruiters.com/example/123?oga=true')
    job.update(changes)
    return job


class RankingTests(unittest.TestCase):
    def test_supported_role_has_evidence_but_unknown_pay_is_held(self):
        job = assess(example(), RESUME, CONFIG, NOW)
        self.assertEqual(job['status'], 'shortlisted')
        self.assertIn('Power BI', job['matched_skills'])
        self.assertEqual(job['application_status'], 'not_submitted')
        self.assertIn('Salary floor not verified', job['submission_blockers'])

    def test_published_pay_below_floor_rejected(self):
        job = assess(example(compensation=dict(currency='INR', period='YEARLY', min=800000, max=1400000)), RESUME, CONFIG, NOW)
        self.assertEqual(job['status'], 'rejected')

    def test_zero_placeholder_salary_is_unknown(self):
        self.assertEqual(salary_assessment(example(compensation=dict(currency='INR', period='YEARLY', min=0, max=0)), CONFIG), 'undisclosed_or_unverified')

    def test_salary_range_crossing_floor_needs_confirmation(self):
        self.assertEqual(salary_assessment(example(compensation=dict(currency='INR', period='YEARLY', min=1200000, max=1800000)), CONFIG), 'range_overlaps_minimum')

    def test_no_currency_conversion_is_assumed(self):
        self.assertEqual(salary_assessment(example(compensation=dict(currency='USD', period='YEARLY', min=50000, max=90000)), CONFIG), 'undisclosed_or_unverified')

    def test_experience_gap_rejected(self):
        self.assertEqual(assess(example(qualifications='8-10 years of experience'), RESUME, CONFIG, NOW)['status'], 'rejected')

    def test_experience_range_uses_lower_bound(self):
        self.assertEqual(minimum_experience('8-10 years of experience'), 8)
        self.assertEqual(minimum_experience('Total Experience Expected: 06-08 years'), 6)
        self.assertEqual(minimum_experience('Experience: 7yrs to 10yrs'), 7)
        self.assertEqual(minimum_experience('5+ years as a Business Analyst'), 5)

    def test_mandatory_unsupported_skill_not_added(self):
        job = assess(example(qualifications='4 years of experience. Hands-on ARIS administration is required.'), RESUME, CONFIG, NOW)
        self.assertLess(job['score'], 75)
        self.assertTrue(any('ARIS' in gap for gap in job['gaps']))

    def test_preferred_skill_does_not_trigger_mandatory_cap(self):
        job = assess(example(qualifications='4 years of experience. ARIS is preferred.'), RESUME, CONFIG, NOW)
        self.assertTrue(any('ARIS' in gap for gap in job['gaps']))
        self.assertFalse(any('Explicit required' in gap for gap in job['gaps']))

    def test_required_financial_domain_is_not_inferred_from_retail(self):
        job = assess(example(qualifications='6-10 years of experience in payments and cards.'), RESUME, CONFIG, NOW)
        self.assertLess(job['score'], 75)
        self.assertTrue(any('Required domain' in gap for gap in job['gaps']))

    def test_known_skill_satisfies_explicit_or_alternative(self):
        job = assess(example(qualifications='4 years of experience. Experience with Power BI or Salesforce is required.'), RESUME, CONFIG, NOW)
        self.assertFalse(any('Explicit required' in gap for gap in job['gaps']))

    def test_stale_job_rejected(self):
        self.assertEqual(assess(example(posted_at='2025-01-01'), RESUME, CONFIG, NOW)['status'], 'rejected')

    def test_missing_posted_date_flagged(self):
        self.assertIn('Posting freshness is unverified.', assess(example(posted_at=None), RESUME, CONFIG, NOW)['gaps'])

    def test_duplicates_removed_even_with_tracking_links(self):
        self.assertEqual(len(deduplicate([example(), example(job_url=example()['job_url'] + '?source=linkedin')])), 1)

    def test_draft_preserves_all_claims_and_does_not_add_jd_skills(self):
        job = example(description='SQL required; ARIS mandatory')
        text, changes = tailored_text(RESUME, job)
        self.assertEqual(Counter(RESUME.splitlines()), Counter(text.splitlines()))
        self.assertNotIn('ARIS', text)
        self.assertIn('Â£1.93M', text)

    def test_output_html_escapes_source_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = assess(example(), RESUME, CONFIG, NOW)
            path = Path(prepare_draft(RESUME + '<script>bad()</script>', job, Path(tmp)))
            content = path.with_suffix('.html').read_text(encoding='utf-8')
            self.assertNotIn('<script>', content)
            self.assertIn('&lt;script&gt;', content)


class DiscoveryTests(unittest.TestCase):
    def test_city_does_not_override_explicit_foreign_country(self):
        self.assertFalse(india_eligible_location('Delhi, United States'))
        self.assertTrue(india_eligible_location('Pune, MH'))
        self.assertFalse(india_eligible_location('Remote - EMEA only'))

    def test_greenhouse_reads_full_description_not_search_snippet(self):
        listing = dict(jobs=[dict(id=123, title='Business Analyst', location=dict(name='Chennai, India'), absolute_url='https://job-boards.greenhouse.io/example/jobs/123')])
        detail = dict(title='Business Analyst', content='&lt;p&gt;SQL required&lt;/p&gt;', absolute_url='https://job-boards.greenhouse.io/example/jobs/123', company_name='Example', first_published='2026-10-01')
        with patch('discovery.get_json', side_effect=[listing, detail]):
            jobs, status = greenhouse('example')
        self.assertEqual(jobs[0]['description'], 'SQL required')
        self.assertEqual(jobs[0]['posted_at'], '2026-10-01')

    def test_lever_non_india_remote_is_not_included(self):
        listing = [dict(text='Business Analyst', categories=dict(location='Remote - USA only'))]
        with patch('discovery.get_json', return_value=listing):
            jobs, status = lever('example')
        self.assertEqual(jobs, [])
    def test_remote_us_only_not_india_eligible(self):
        feed = dict(jobs=[dict(id=1, title='Business Analyst', candidate_required_location='USA only'),
                          dict(id=2, title='Business Analyst', candidate_required_location='Worldwide', company_name='Example', url='https://remotive.com/remote-jobs/example', description='<p>SQL</p>')])
        with patch('discovery.get_json', return_value=feed):
            jobs, status = remotive()
        self.assertEqual([j['source_id'] for j in jobs], ['2'])
        self.assertEqual(status['examined'], 2)

    def test_internships_excluded(self):
        self.assertFalse(relevant_title('Business Analyst Intern'))
        self.assertTrue(relevant_title('Senior Business Analyst'))

    def test_only_public_active_india_postings_selected(self):
        listing = dict(totalFound=2, content=[dict(id='1', name='Business Analyst'), dict(id='2', name='Business Analyst')])
        active = dict(id='1', active=True, name='Business Analyst', location=dict(country='in', city='Pune'), jobAd=dict(sections=dict(jobDescription=dict(text='<p>SQL</p>'))), postingUrl='https://jobs.smartrecruiters.com/example/1')
        inactive = dict(active=False)
        with patch('discovery.get_json', side_effect=[listing, active, inactive]) as fetch:
            jobs, status = smartrecruiters('example')
        self.assertEqual(len(jobs), 1)
        self.assertIn('destination=PUBLIC', fetch.call_args_list[0].args[0])
        self.assertEqual(status['status'], 'searched')

    def test_detail_failure_does_not_hide_other_results(self):
        listing = dict(totalFound=1, content=[dict(id='1', name='Business Analyst')])
        with patch('discovery.get_json', side_effect=[listing, TimeoutError()]):
            jobs, status = smartrecruiters('example')
        self.assertEqual(jobs, [])
        self.assertEqual(status['status'], 'partially searched')


class ReviewTests(unittest.TestCase):
    def test_only_owner_can_record_known_job_commands(self):
        key = '0123456789abcdef'
        comments = [dict(user=dict(login='attacker'), body='/applied ' + key),
                    dict(user=dict(login='shaswatshukla'), body='/approve ' + key + '\n/applied ffffffffffffffff')]
        self.assertEqual(parse_review_commands(comments, 'shaswatshukla', {key}), {key: 'approve'})

    def test_latest_owner_command_wins(self):
        key = '0123456789abcdef'
        comments = [dict(user=dict(login='owner'), body='/approve ' + key), dict(user=dict(login='owner'), body='/skip ' + key)]
        self.assertEqual(parse_review_commands(comments, 'owner', {key}), {key: 'skip'})

    def test_unknown_budget_and_expected_salary_do_not_stop_free_discovery(self):
        pending = blockers(CONFIG, {})
        self.assertTrue(any('Free keyword' in item for item in pending))
        self.assertTrue(any('only applications' in item for item in pending))
        self.assertFalse(any('OPENAI_API_KEY' in item for item in pending))


if __name__ == '__main__':
    unittest.main()

