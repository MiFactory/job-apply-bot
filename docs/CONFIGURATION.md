# Configuration reference

All files are per profile: `data/profiles/<name>/`. Examples with fictive data: [`examples/`](../examples).

## profile.json

| Key | Meaning |
|---|---|
| `first_name`, `last_name`, `email` | Used for name / email fields |
| `phone`, `phone_country_code`, `phone_national` | Full number, `+32`, and the number without country code |
| `city`, `postal_code`, `country`, `address` | Address fields |
| `linkedin_url`, `website`, `headline` | Profile links / headline |
| `google_email` | Gmail used for *Continue with Google* |
| `years_experience_total` | Default answer to "how many years of experience…" |
| `years_by_skill` | `{"salesforce": 3}` — answer when the question mentions the skill |
| `salary_year_eur`, `salary_month_eur` | Expected salary |
| `notice_period`, `available_from` | Availability / notice questions |
| `authorized_to_work`, `needs_sponsorship`, `willing_relocate`, `driving_licence` | Yes/No questions |
| `languages` | `{"english": "Professional", ...}` — answer to language level questions |
| `education` | Education questions |
| `cv_files` | `{"en": path, "fr": path, "nl": path}` — CV used per ad language |
| `default_cv_lang` | CV used when the ad language has no CV |

## criteria.json

| Key | Meaning |
|---|---|
| `sites` | `["linkedin", "indeed"]` |
| `titles` | Job titles searched (one search each) |
| `locations` | Search locations |
| `exclude` | Words that reject an offer when found in the **title** |
| `exclude_companies` | Companies to skip |
| `must_have_any` | At least one keyword must appear in title/description (empty = off) |
| `title_must_match_any` | At least one word must appear in the title (empty = off) |
| `posted_within_days` | Freshness window |
| `easy_apply_only` | Only Easy Apply / Indeed Apply offers |
| `min_score` | Minimum score (1 = accept all that pass the filters) |
| `max_applications_per_day` | Daily cap across runs |
| `skip_languages` | Skip ads written in these languages (e.g. `["nl"]`) |
| `location_must_contain` | The offer location must contain one of these lowercase fragments (keeps results in your country) |
| `ask_user_when_unknown` | Ask for unknown questions (otherwise skip the job and log it) |

## motivation.json

`{"en": "…", "fr": "…"}` — placeholders `{title}`, `{company}`, `{full_name}`. Chosen by the language of the ad.

## answers.json

`{"normalised question": "answer"}` — filled by the GUI/CLI when you answer unknown questions. Keys are lower-case, punctuation removed. Edit or delete rows in the GUI right panel.

## applications.csv

`date;site;job_id;title;company;location;url;status;note` — `;`-separated for Excel (FR).
