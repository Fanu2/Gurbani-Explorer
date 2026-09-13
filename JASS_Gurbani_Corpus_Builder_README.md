# JASS Gurbani Corpus Builder

**Version:** 3.0  
**Project:** JASS Gurbani Tools  
**Purpose:** Build a clean, searchable, structured Gurbani corpus and generate `gurbani.db`.

---

## Overview

**JASS Gurbani Corpus Builder** is a PySide6 desktop application for turning a raw Gurbani text file into a structured corpus suitable for search, reading, context-aware retrieval, and the JASS Gurbani Explorer.

The application is designed around a simple principle:

> **Clean the source once, validate it carefully, then build a reliable local database.**

It provides an interactive workflow for inspecting the source text, cleaning unwanted material, reviewing references, examining structure, validating records, and exporting the resulting corpus.

---

## Current Workflow

```text
Raw Gurbani TXT
       │
       ▼
   Open TXT
       │
       ▼
 Import / Rebuild
       │
       ├── Cleaning
       ├── Reference Review
       ├── Record Inspection
       ├── Search + Context
       ├── Structure Inspection
       └── Validation
       │
       ▼
 Clean Gurbani Corpus
       │
       ├── JSON
       ├── CSV
       └── gurbani.db
       │
       ▼
JASS Gurbani Explorer
```

---

## Main Features

### 1. Open TXT

Load a complete Gurbani text file directly into the application.

The builder reports basic corpus information such as:

- Source file
- Encoding
- Total records
- Included records
- Gurbani records
- Reference records
- Other records
- Duplicate records
- Replacement/cleaning information

---

### 2. Import / Rebuild

Processes the selected source text and rebuilds the internal corpus representation.

The rebuild operation is intended to be repeatable. This makes it possible to improve cleaning or parsing rules and regenerate the corpus from the original source rather than manually editing the database.

---

### 3. Cleaning

The cleaning stage separates useful Gurbani text from unwanted material.

Typical unwanted material can include:

- Website navigation
- HTML fragments
- English interface text
- URLs
- Internet Archive/web-page material
- Conversion artefacts
- Empty or meaningless records
- Duplicate records
- Other non-Gurbani text

The objective is **not** to blindly delete everything that looks unusual.

The corpus builder should preserve genuine Gurbani while removing demonstrably unrelated material.

---

### 4. Reference Review

The application identifies records that may represent:

- Source references
- Page/Ang references
- Metadata
- Attribution
- Website/source information
- Other non-Gurbani annotations

References can be reviewed before the final database is generated.

This is important because source references should not accidentally become searchable Gurbani content.

---

### 5. Records Inspector

The Records view provides a closer look at the imported material.

This makes it easier to detect:

- Bad parsing
- Broken lines
- Unexpected English
- Duplicate passages
- Encoding problems
- Stray characters
- Incorrectly classified records

---

### 6. Search + Context

Search is intended to help inspect the corpus before database generation.

The important design goal is **context-aware inspection**, rather than treating every physical text line as an independent quotation.

This is particularly important for Gurbani because a useful passage may span several lines.

---

### 7. Structure Inspector

The Structure Inspector is used to understand how the imported text is organized.

It helps identify:

- Record boundaries
- Groups
- Sections
- Potential passage boundaries
- Structural anomalies
- Relationships between neighbouring records

This provides a foundation for producing cohesive search results later in JASS Gurbani Explorer.

---

### 8. Validation

Validation checks the corpus before it is exported.

The purpose is to catch problems before they reach `gurbani.db`.

Examples include:

- Empty records
- Suspicious records
- Duplicate content
- Missing fields
- Unexpected characters
- Invalid classifications
- Potential non-Gurbani contamination

A database should ideally be generated **only after validation has been reviewed**.

---

### 9. Export JSON

Exports the structured corpus as JSON.

JSON is useful for:

- Inspection
- Backup
- Data interchange
- Future processing
- Debugging
- Developing additional Gurbani tools

---

### 10. Export CSV

Exports corpus records as CSV for inspection in spreadsheet applications and other data-processing tools.

CSV is particularly useful when manually auditing a large number of records.

---

### 11. Build `gurbani.db`

The final step creates the SQLite database used by the JASS Gurbani applications.

The database provides the foundation for:

- Fast searching
- Context retrieval
- Passage display
- Favorites
- Random Gurbani
- Card generation
- Future research tools
- Offline use

A test database was generated during development as:

```text
gurbani_v3.1_test.db
```

The database currently used with the Explorer contains approximately **24,500 searchable lines/records**, depending on the exact build and cleaning rules used.

---

# Source Cleaning Philosophy

## Should source references be removed?

**Not automatically.**

There are two different things:

### Source metadata

Information such as:

- Original source
- Website
- Archive URL
- Copyright/attribution
- Import information

should normally be retained as **metadata**, not mixed into searchable Gurbani text.

### Text embedded inside the source

English website navigation, URLs, page descriptions, HTML text, and unrelated interface material should normally be removed from the Gurbani corpus when it is clearly not part of Gurbani.

The goal is:

```text
Gurbani text
    +
useful structured metadata
    +
traceability to the source
```

rather than:

```text
Gurbani + website garbage + navigation + URLs
```

This distinction is important for search quality.

---

# Database Design Direction

The corpus builder should produce a database that is optimized for the JASS Gurbani Explorer rather than simply storing the original text line-by-line.

A future-oriented record can contain fields such as:

```text
id
text
normalized_text
section
source
page/ang
writer
raag
record_type
sequence
group_id
passage_id
```

Not every field has to be populated by the importer immediately.

The important objective is to create a stable foundation that future tools can understand.

---

# Why Cohesive Passages Matter

A major design requirement for JASS Gurbani Explorer is that search results should **not begin in the middle of a passage or end abruptly** merely because the matching word occurred on one physical line.

For example:

```text
Raw source:

Line 101
Line 102  ← search match
Line 103
Line 104
```

The user should ideally receive:

```text
Line 101
Line 102
Line 103
Line 104
```

as one meaningful context block when those lines belong to the same passage.

Therefore the Corpus Builder is not merely a text cleaner.

It is the foundation for **context-aware Gurbani retrieval**.

---

# Relationship with JASS Gurbani Explorer

The intended ecosystem is:

```text
                 ┌──────────────────────┐
                 │  Original Gurbani    │
                 │       TXT source     │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ JASS Gurbani Corpus  │
                 │       Builder        │
                 └──────────┬───────────┘
                            │
                     gurbani.db
                            │
                            ▼
                 ┌──────────────────────┐
                 │ JASS Gurbani         │
                 │ Explorer             │
                 └──────────┬───────────┘
                            │
          ┌─────────────────┼─────────────────┐
          ▼                 ▼                 ▼
       Search            Reader           Card Studio
          │                 │                 │
          └─────────────────┼─────────────────┘
                            ▼
                   Future Gurbani Tools
```

The Corpus Builder is therefore a **data preparation tool**, while Explorer is the **user-facing Gurbani application**.

---

# Current Version 3.0 UI

The current application includes the following major areas:

- Overview
- Records
- Search + Context
- Structure Inspector
- Validation

And primary actions:

- Open TXT
- Import / Rebuild
- Validate
- Review References
- Build `gurbani.db`
- JSON
- CSV

The interface is intentionally focused on corpus preparation rather than general-purpose text editing.

---

# Proposed Enhancements

## Phase 1 — Corpus Quality

### Better Gurbani classification

Improve detection of:

- Gurbani
- headings
- references
- metadata
- English contamination
- URLs
- conversion artefacts

### Duplicate analysis

Provide:

- exact duplicate detection
- normalized duplicate detection
- duplicate groups
- duplicate preview
- safe duplicate removal

### Unicode diagnostics

Detect:

- malformed Unicode
- unusual combining marks
- replacement characters
- mixed encodings
- suspicious Gurmukhi characters

---

# Phase 2 — Gurbani Structure

### Passage Builder

Automatically group related lines into cohesive passages.

Possible structure:

```text
Passage
 ├── line
 ├── line
 ├── line
 └── line
```

### Ang/Page awareness

Where source information allows it, preserve:

- Ang number
- section
- sequence
- source location

### Raag / Writer metadata

Where reliably available, preserve structured metadata for:

- Raag
- Writer
- Ang
- composition/group

---

# Phase 3 — Search Foundation

### Search normalization

Support searching despite differences in:

- whitespace
- punctuation
- Unicode normalization
- common formatting differences

### Search context preview

Show:

```text
Previous line
MATCHING LINE
Next line
```

and allow larger context windows.

### Exact / phrase / word search

Provide:

- exact phrase
- all words
- any word
- prefix
- normalized search
- context search

---

# Phase 4 — Database Engineering

### SQLite indexes

Create optimized indexes for:

- Gurbani text
- normalized text
- Ang
- Raag
- Writer
- passage ID
- record type

### SQLite FTS

A future version should consider SQLite Full-Text Search for substantially faster searching over the corpus.

### Database integrity checks

Before export:

```text
✓ schema valid
✓ required fields present
✓ no invalid records
✓ indexes created
✓ record counts verified
✓ duplicate report generated
```

---

# Phase 5 — Review Tools

### Side-by-side source review

Allow:

```text
Original source          Clean corpus
────────────────         ─────────────
raw record               cleaned record
raw metadata             structured metadata
raw reference            classified reference
```

### Approve / reject records

Allow the user to manually mark suspicious records:

- Keep
- Remove
- Reference
- Review later

### Change log

Record what the builder changed during cleaning.

This improves reproducibility and makes the corpus easier to audit.

---

# Phase 6 — Card Studio Integration

The clean database can directly feed the JASS Gurbani Card Studio.

A search result could become:

```text
Search
   ↓
Cohesive Passage
   ↓
Create Card
   ↓
Choose Design
   ↓
Live Preview
   ↓
Export PNG
```

Potential card features:

- Multiple designs
- 1:1 square
- 4:5 portrait
- 16:9 landscape
- Gurmukhi typography
- Optional English translation
- Ang / Raag / Writer footer
- Watermark
- Background selection
- Font selection
- Text alignment
- Decorative borders
- Export PNG

---

# Phase 7 — Gurbani Research Tools

Future versions could support:

- Gurbani occurrence analysis
- Word frequency
- phrase frequency
- repeated lines
- Raag distribution
- Writer distribution
- Ang navigation
- cross-reference exploration
- passage comparison
- concordance-style search

This would turn the corpus from a simple database into a useful **offline Gurbani research corpus**.

---

# Phase 8 — Corpus Profiles

The builder could eventually support multiple corpus profiles:

```text
Sri Guru Granth Sahib
Sri Dasam Granth
Selected Gurbani
Custom Corpus
Research Corpus
```

Each corpus could have its own:

- database
- metadata
- validation rules
- cleaning profile
- search configuration

---

# Recommended Long-Term Architecture

The project should remain modular:

```text
JASS Gurbani Corpus Builder
│
├── Source Loader
├── Encoding Detector
├── Cleaner
├── Reference Classifier
├── Record Parser
├── Passage Builder
├── Metadata Extractor
├── Validator
├── Search Inspector
├── Structure Inspector
├── Exporter
│   ├── JSON
│   ├── CSV
│   └── SQLite
└── Database Builder
```

This keeps the importer independent from the Explorer.

---

# Technology

The application is designed as a local desktop application using:

- Python
- PySide6
- SQLite
- JSON
- CSV

No separate virtual environment is required if the required Python packages are already installed globally.

Typical launch:

```powershell
py .\JASS_Gurbani_Corpus_Builder_v3.0.py
```

---

# Offline First

The corpus builder is intended to work locally.

The core workflow should not require:

- cloud services
- an online API
- an internet connection
- external databases

This makes it suitable for building and maintaining a personal Gurbani corpus.

---

# Data Ownership

The generated corpus and database remain local files controlled by the user.

The application should not silently upload corpus data anywhere.

---

# Recommended Build Procedure

For a new corpus:

### 1. Open the original TXT

```text
Open TXT
```

### 2. Import

```text
Import / Rebuild
```

### 3. Inspect

Review:

```text
Overview
Records
Search + Context
Structure Inspector
```

### 4. Review references

Use:

```text
Review References
```

### 5. Validate

Use:

```text
Validate
```

### 6. Export backup formats

Generate:

```text
JSON
CSV
```

### 7. Build database

Generate:

```text
gurbani.db
```

### 8. Test in Explorer

Open the resulting database in:

```text
JASS Gurbani Explorer
```

and verify:

- search
- context
- navigation
- passage display
- card creation

---

# Important Principle

**Do not treat the first successful database build as the final corpus.**

A good corpus should be:

- clean
- searchable
- structured
- traceable
- reproducible
- validated
- context-aware

The Corpus Builder exists to make that quality visible and controllable.

---

# Project Status

**Current status:** Functional foundation / active development.

The v3.0 application is considered a strong foundation for building the local Gurbani corpus and `gurbani.db`.

Future work should prioritize:

1. Search/context quality
2. Passage grouping
3. Metadata accuracy
4. Validation
5. Database indexing
6. Card Studio integration
7. Research capabilities

Avoid adding complexity that does not materially improve corpus quality or the user experience.

---

## Vision

> **Build once. Validate carefully. Search naturally. Preserve Gurbani faithfully.**

JASS Gurbani Corpus Builder is intended to become the reliable data foundation behind the JASS Gurbani ecosystem.
