# India job-search agent

Discover India Business Analyst roles from public employer feeds, rank against a verified resume, and prepare factual resume drafts and CSV/Markdown reports.

## Local setup

Python 3.12+, standard library only. Copy `candidate.example.json` to `candidate.json`, fill in your own confirmed preferences, and save your resume as `resume/master-resume.txt`. Then run `python preflight.py` and `python agent.py`. Tests: `python -m unittest discover -v`.

Candidate data, resumes, reports and deduplication state stay local and are ignored by Git. The public workflow runs tests only. Optional email uses SMTP_HOST, SMTP_USERNAME and SMTP_PASSWORD from the environment. Review the recipient before running with email credentials. Never upload private reports to public issues or Actions artifacts.

No automatic applications are implemented. LinkedIn and other authenticated job boards are not connected. Scores are keyword ranking aids, not ATS scores. The separate Naukri project handles user-supplied Naukri job exports. Your original private runtime retains its schedules, history and personal configuration; this public edition does not migrate credentials or enable a duplicate schedule.
