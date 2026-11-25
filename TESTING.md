# Testing

## Local checks

Install development dependencies:

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

Run the full automated test suite:

```bash
pytest -q
```

Run tests with statement and branch coverage:

```bash
pytest -q --cov=transfer --cov-report=term-missing
```

Run property-based fuzz tests for untrusted inputs and provider responses:

```bash
pytest -q transfer/test_fuzzing.py
```

The Hypothesis cases use a deterministic example database and bounded input sizes so failures are reproducible in CI. They exercise VK URL parsing, provider candidate URL validation, Unicode track normalization, library-search JSON validation, and malformed Spotify search results. All provider calls are mocked; fuzz tests never contact live services.

Run the checks used by CI:

```bash
ruff check .
python manage.py check
python manage.py makemigrations --check --dry-run
pytest -q --cov=transfer --cov-report=term-missing --cov-fail-under=60
```

## Coverage policy

CI enforces at least **60% combined statement and branch coverage** for the `transfer` application. Migrations and test modules are excluded from the measured application coverage. The report is informational at the individual-file level; when changing a low-coverage module, add tests for the affected behavior rather than relying only on the global percentage.

The threshold is an initial floor, not a target. Critical business paths should receive direct unit and integration coverage even when the global threshold is already satisfied.

## Test boundaries

- Provider API and OAuth tests must use mocked HTTP responses. The suite must not require real VK, Spotify, or SoundCloud credentials.
- Tests should assert externally observable contracts: URL names, HTTP methods, response status and payload, session ownership, database effects, and provider request parameters.
- Security-sensitive cases should include invalid input, unauthorized ownership, redirects, untrusted URLs, missing provider data, and partial upstream failures.
- For Celery-backed workflows, test job claiming, duplicate delivery, progress persistence, successful completion, and failure handling.
- For playback, test stream discovery separately from CDN proxy behavior, including Range requests and resource cleanup.
- Keep DAST/container checks in CI as complementary checks; they do not replace application-level tests.
