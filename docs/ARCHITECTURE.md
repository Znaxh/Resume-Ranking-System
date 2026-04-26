# Architecture Overview

## System Design

The Resume Ranking System follows a client-server architecture with a React frontend and Flask backend. The backend orchestrates multiple ranking algorithms in parallel and combines their scores using a weighted ensemble approach.

## Algorithm Pipeline

```
Resume Files + Job Description
        │
        ▼
┌─────────────────┐
│  File Processor  │  Extract text from PDF/DOCX/DOC/TXT
└────────┬────────┘
         │
         ▼
┌─────────────────────┐
│  Algorithm Manager   │  Parallel execution via ThreadPoolExecutor
│                     │
│  ┌───────────────┐  │
│  │ Deep Learning  │  │  BERT, DistilBERT, SBERT
│  ├───────────────┤  │
│  │ Similarity     │  │  TF-IDF Cosine, BM25
│  ├───────────────┤  │
│  │ NLP            │  │  spaCy NER + skill patterns
│  ├───────────────┤  │
│  │ Traditional ML │  │  XGBoost, Random Forest, SVM, MLP
│  └───────────────┘  │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Score Combination   │  Weighted average with normalized weights
│                     │  Optional must-have penalty from NER
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Explainer (opt.)    │  LLM-generated or template-based explanations
│  Fairness Monitor    │  Score variance and bias detection
└────────┬────────────┘
         │
         ▼
   Ranked JSON Response
```

## Algorithm Details

### Scoring Approach
Each algorithm produces a score in [0, 1]. The `AlgorithmManager` combines scores using a weighted average. Default weights are:

| Algorithm | Default Weight |
|-----------|---------------|
| BERT | 0.25 |
| SBERT | 0.25 |
| Cosine | 0.20 |
| DistilBERT | 0.10 |
| BM25 | 0.10 |
| NER | 0.10 |
| ML Models | 0.0 (auto-enabled when loaded) |

Weights normalize to sum to 1.0 across active algorithms.

### BM25 (formerly "Jaccard")
The algorithm registered as `bm25` (aliased as `jaccard` for backward compatibility) implements BM25 probabilistic ranking with:
- Term frequency saturation (k1=1.5)
- Document length normalization (b=0.75)
- Technical skill boosting (1.5x for recognized tech terms)
- Bigram phrase matching bonus

### NER Must-Have Penalty
When NER is active, the algorithm manager checks if required skills from the job description are missing from the resume. If `must_have_ok` is false, the combined score is halved as a penalty.

## API Versioning

- **Legacy (`/api/*`)**: Full-featured endpoints including LLM expansion, fairness monitoring, and academic workflows
- **V2 (`/v2/api/*`)**: Enhanced endpoints with Redis caching, richer health checks, and benchmarks

## Caching Strategy

- **In-memory**: JD expansion results cached by SHA-256 hash of JD text
- **Redis (optional)**: V2 API caches processing results; cache keys incorporate file signatures, JD content, position, and algorithm selection

## Security Model

- CORS restricted to configured origins (env: `CORS_ALLOWED_ORIGINS`)
- Rate limiting via Flask-Limiter (configurable)
- No internal error details exposed to API clients
- Redis cache uses JSON serialization (not pickle)
- File uploads validated for type, size, and content
