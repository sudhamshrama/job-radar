# ADR 0004 — Job source selection

**Status:** Accepted
**Date:** 2026-08-12

## Context

The pipeline ingests DevOps and SRE job postings. Sources had to be documented
public JSON APIs — no HTML scraping, which would be brittle and would raise
terms-of-service questions.

Candidate source types: Greenhouse public job boards, Lever postings, RemoteOK,
and Hacker News "Who Is Hiring" threads via the Algolia API.

## Method

Every candidate endpoint was called before being written into the config.
Greenhouse board tokens in particular are **not** derivable from a company name —
several obvious guesses returned 404 (`hashicorp`, `confluent`, `snowflake`,
`doordash`), while equally obvious ones worked.

## Decision

Three sources, twelve Greenhouse boards:

| Source | Status | Result |
|---|---|---|
| **Greenhouse** | accepted | 12 of 16 tested boards live: datadog, cloudflare, gitlab, databricks, stripe, elastic, mongodb, grafanalabs, circleci, pagerduty, fastly, reddit |
| **RemoteOK** | accepted | 101 items, requires a `User-Agent` header |
| **HN Who Is Hiring** (Algolia) | accepted | responds; free-text comments |
| **Lever** | **rejected** | 6 of 7 companies 404; `plaid` returned an empty array |

Lever was dropped on evidence, not preference. A source that returns nothing
adds a code path, a failure mode, and a test to maintain, in exchange for zero
postings. It can be reinstated if a company with a live board is identified.

## Why three sources with different shapes

This is deliberate, and it is where the interesting work in this project lives:

- **Greenhouse** returns an object with a `jobs` array of clean structured
  fields.
- **RemoteOK** returns a bare array whose **first element is a legal notice, not
  a job** — a real-world quirk that will silently corrupt the dataset if the
  parser assumes every element is a posting.
- **Hacker News** returns comments. The posting is unstructured prose with no
  fields at all.

Normalizing three genuinely different shapes into one record schema is the
substance of the ingest stage. A single well-behaved source would have made the
pipeline a data transfer exercise.

## Validation of the premise

Filtering live board data for DevOps-relevant titles (`devops`, `site
reliability`, `sre`, `platform engineer`, `infrastructure engineer`, `cloud
engineer`, `kubernetes`, `observability`):

```
grafanalabs   20 / 146      mongodb       22 / 416
elastic       14 / 252      datadog        9 / 441
databricks     6 / 807      reddit         5 / 154
gitlab         3 / 197      fastly         3 /  53
stripe         1 / 565

83 matching roles across live boards
```

83 relevant roles at a single point in time confirms the pipeline has real data
to work with.

## Consequences

- Board tokens are configuration (`config/sources.json`), not code. A dead board
  is a config edit.
- Sources will break without warning — companies change ATS vendors. Ingest must
  treat a failing source as a partial failure that is logged and alarmed, never
  as a reason to fail the whole run. This drives the SQS + DLQ design in the
  next stage.
- The RemoteOK first-element quirk is recorded in `config/sources.json` and must
  have a regression test.
