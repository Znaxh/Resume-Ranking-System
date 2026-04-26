# Contributing to Resume Ranking System

Thank you for your interest in contributing! This guide will help you get started.

## Development Setup

### Prerequisites
- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (Python package manager)
- Node.js 20+
- Docker (optional, for containerized development)

### Backend Setup
```bash
cd backend
uv sync --all-groups
uv run python -m spacy download en_core_web_sm
uv run python app.py
```

### Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

### Running Tests
```bash
cd backend
uv run pytest --cov=. --cov-report=term-missing
```

## Project Structure

```
├── backend/
│   ├── app.py                 # Flask app factory and legacy routes
│   ├── app_config.py          # Feature flags and limits
│   ├── api/                   # v2 blueprint, middleware, error handlers
│   ├── algorithms/            # All ranking algorithms
│   │   ├── similarity/        # Cosine, BM25, NER
│   │   ├── deep_learning/     # BERT, DistilBERT, SBERT
│   │   └── traditional_ml/    # XGBoost, RF, SVM, NN
│   ├── core/                  # Algorithm manager, scoring, explainer
│   ├── config/                # Settings, logging
│   ├── data/                  # Dataset management, sample data
│   ├── models/                # Model definitions
│   ├── utils/                 # File processing, validation, caching
│   └── tests/                 # Test suite
├── frontend/
│   ├── app/                   # Next.js App Router pages
│   ├── components/            # React components
│   └── lib/                   # API client, utilities
└── docker-compose.yml
```

## Coding Standards

### Python (Backend)
- Follow PEP 8 style guidelines
- Use type hints for function signatures
- Write docstrings for public methods
- Handle exceptions explicitly — never expose internal errors to API clients
- Use structlog for logging, not print statements
- Add new dependencies via `uv add <package>`

### JavaScript/React (Frontend)
- Use functional components with hooks
- Follow the existing Tailwind CSS patterns
- Keep API calls in `lib/api.js`
- Use `react-hot-toast` for user notifications

## Making Changes

1. **Fork the repo** and create a feature branch from `main`
2. **Write tests** for new backend functionality
3. **Run the test suite** before submitting
4. **Keep commits focused** — one logical change per commit
5. **Write clear commit messages** describing the "why"

## Pull Request Process

1. Ensure all tests pass and no new linter warnings are introduced
2. Update documentation if you've changed APIs or configuration
3. Describe your changes clearly in the PR description
4. Link any related issues

## Algorithm Development

When adding a new ranking algorithm:

1. Create a new file in the appropriate `algorithms/` subdirectory
2. Extend `BaseAlgorithm` and implement `process_single(resume_text, job_description, position)`
3. Return a dict with `algorithm`, `score` (0-1 float), and `details`
4. Register it in `AlgorithmManager.__init__`
5. Add the algorithm name to `validators.py` valid_algorithms
6. Add a frontend entry in `MethodSelector.jsx`
7. Write tests in `tests/`

## Reporting Issues

- Use GitHub Issues with a clear title
- Include steps to reproduce, expected vs actual behavior
- Attach relevant logs (redact any sensitive data)
