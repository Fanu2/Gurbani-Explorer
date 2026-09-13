# JASS Gurbani Corpus Builder

## Latest Release: v4.6

**Application:** `JASS_Gurbani_Corpus_Importer_v4.6.py`\
**Purpose:** Build a verified, normalized JASS Gurbani SQLite database
from the inspected Shabad OS `master.sqlite`.

> **v4.6 is the current verified Builder release.**

------------------------------------------------------------------------

## 1. Purpose

JASS Gurbani Corpus Builder is the **data-foundation application** for
the JASS Gurbani ecosystem.

It takes the original Shabad OS SQLite database, investigates its real
schema and text relationships, verifies the authoritative Gurmukhi text
path, and creates a separate canonical database:

``` text
JASS_Gurbani.db
```

The Builder is deliberately conservative. It does not silently assume
that every source row belongs to Sri Guru Granth Sahib.

------------------------------------------------------------------------

## 2. Core Principle

### The source database is never modified

``` text
master.sqlite
     │
     │  READ ONLY
     ▼
JASS Gurbani Corpus Builder
     │
     │  verified transformation
     ▼
JASS_Gurbani.db
```

The original `master.sqlite` remains untouched.

The generated database contains its own metadata, provenance, and import
manifest.

------------------------------------------------------------------------

## 3. Verified Source Database

The inspected `master.sqlite` contains **9 tables**:

  Table                Rows
  --------------- ---------
  `lines`           141,264
  `line_groups`      12,730
  `asset_lines`     670,006
  `sections`            127
  `sources`              10
  `authors`              40
  `banis`                29
  `bani_lines`        9,424
  `assets`               23

### Authoritative Gurmukhi text

The verified primary text path is:

``` text
asset_lines.line_id → lines.id
asset_lines.data    → primary Gurmukhi text
asset_lines.type    = 'primary'
```

The verified investigation established:

``` text
141,264 / 141,264 lines
```

with a corresponding non-empty primary text record.

The primary asset also exposes page/line metadata through its additional
metadata where available.

------------------------------------------------------------------------

## 4. Sri Guru Granth Sahib Scope

SGGS membership is established through the actual relational structure
rather than by guessing from JSON:

``` text
lines.line_group_id
        ↓
line_groups.id
        ↓
line_groups.section_id
        ↓
sections.id
        ↓
sections.source_id = 'SGGS'
```

The verified build produced:

-   **5,549 SGGS shabads/groups**
-   **60,555 SGGS lines**
-   **60,555 / 60,555 lines with primary Gurmukhi text**
-   **60,555 / 60,555 primary records with page + line metadata**

The scope selector remains conservative and reports limitations rather
than silently treating unrelated material as SGGS.

------------------------------------------------------------------------

# 5. v4.6 Features

## 🔎 Schema Analysis

The Builder examines the actual SQLite schema and detects:

-   tables
-   columns
-   relationships
-   line identifiers
-   shabad/group relationships
-   ordering fields
-   source metadata
-   author metadata
-   raag metadata
-   section metadata
-   text-bearing tables

The **Analyze Schema** operation is read-only.

------------------------------------------------------------------------

## 🧪 Deep Text Investigation

v4.6 performs a dedicated text investigation before building the corpus.

It identifies candidate text sources and verifies their relationship to
real `lines.id` values.

The verified path is:

``` text
asset_lines.line_id
        ↓
lines.id
```

and:

``` text
asset_lines.data
```

is used as the primary Gurmukhi text.

This prevents the Builder from creating a structurally valid but empty
database.

------------------------------------------------------------------------

## 🔗 Asset Link Verification

The Builder explicitly verifies the relationship between source lines
and primary text assets.

This is especially important because `master.sqlite` contains many asset
records, while only the appropriate primary asset should become the
canonical Gurbani text.

------------------------------------------------------------------------

## 🗺️ Mapping Inspector

The Mapping view shows how source fields map into the normalized JASS
structure.

Examples include:

``` text
line.id
line.shabad_id
line.order_id
group.author_id
group.raga_id
group.section_id
line_content.gurmukhi
```

Unavailable source fields are reported rather than fabricated.

------------------------------------------------------------------------

## 📚 Passage Reconstruction

Passages are reconstructed from the verified shabad/group relationship
and source ordering:

``` text
line_group_id
+
line_group_order
```

This creates cohesive passage records for downstream search and reading.

The Builder therefore does more than simply copy individual text rows.

------------------------------------------------------------------------

## 🧱 Normalized JASS Database

The Builder creates a canonical database containing the structured JASS
corpus layer.

The current validated output includes:

``` text
corpus
sources
authors
ragas
sections
shabads
lines
line_content
passages
passage_lines
provenance
import_manifest
```

This structure is designed for the JASS Explorer and future
search/research tools.

------------------------------------------------------------------------

## 🧾 Provenance

Source identity and import information are retained.

The generated database records information such as:

-   Builder version
-   source database
-   source SHA-256
-   scope
-   creation time
-   source table information
-   source IDs

This makes the corpus traceable and reproducible.

------------------------------------------------------------------------

## ✅ Database Validation

The Builder validates the generated SQLite database.

Validation includes:

-   SQLite integrity
-   required tables
-   expected corpus structures
-   record counts
-   required relationships
-   generated database availability

A successful build is therefore followed by an explicit validation step.

------------------------------------------------------------------------

## 📋 Build Log

The Build Log provides a visible record of:

-   build progress
-   imported records
-   skipped records
-   passage creation
-   target database
-   validation results
-   source read-only status
-   errors or limitations

------------------------------------------------------------------------

## 🧭 Application Views

The current Builder interface provides:

-   **Overview**
-   **Mapping**
-   **Sources**
-   **Structure**
-   **Asset Link**
-   **Investigation**
-   **Build Log**

------------------------------------------------------------------------

# 6. Recommended Workflow

Use the Builder in this order:

### Step 1 --- Open source

Open:

``` text
master.sqlite
```

### Step 2 --- Analyze

Click:

``` text
Analyze Schema
```

### Step 3 --- Investigate

Run the deep text investigation.

Confirm the verified path:

``` text
asset_lines.line_id → lines.id
asset_lines.data → primary Gurmukhi
```

### Step 4 --- Review structure

Check:

-   Mapping
-   Sources
-   Structure
-   Asset Link
-   Investigation

### Step 5 --- Build

Click:

``` text
Build JASS_Gurbani.db
```

### Step 6 --- Validate

Click:

``` text
Validate Built DB
```

### Step 7 --- Explore

Open the resulting database with:

``` text
JASS Gurbani Explorer
```

------------------------------------------------------------------------

# 7. Output Database

Default output:

``` text
JASS_Gurbani.db
```

The Builder preserves original source IDs wherever appropriate.

The source database is not overwritten.

------------------------------------------------------------------------

# 8. Current Verified Build

The currently validated database produced during development contains:

  Object                  Count
  -------------------- --------
  Corpus                      1
  Shabads                 5,549
  Lines                  60,555
  Line content           60,555
  Passages                5,549
  Passage lines          60,555
  Provenance records     66,104
  Tables                     13

SQLite integrity:

``` text
OK
```

These figures describe the current validated SGGS build shown during
development.

------------------------------------------------------------------------

# 9. Technology

The application is a local desktop application using:

-   Python
-   PySide6
-   SQLite
-   JSON

No cloud service is required for the core workflow.

------------------------------------------------------------------------

# 10. Running on Windows

Typical location:

``` text
C:\Users\singh\Downloads\JASS_Gurbani_Corpus_Importer_v4.6
```

Run:

``` powershell
py .\JASS_Gurbani_Corpus_Importer_v4.6.py
```

Optional syntax check:

``` powershell
py -m py_compile .\JASS_Gurbani_Corpus_Importer_v4.6.py
```

------------------------------------------------------------------------

# 11. Architecture

The intended JASS data flow is:

``` text
Shabad OS master.sqlite
          │
          ▼
Schema investigation
          │
          ▼
Verified primary text
          │
          ▼
Scope verification
          │
          ▼
Normalized JASS corpus
          │
          ▼
JASS_Gurbani.db
          │
          ├── Search
          ├── Passage reading
          ├── Favorites
          ├── Card Studio
          └── Future research / RAG
```

The canonical database should remain the authoritative structured corpus
layer.

Search indexes, chunks, embeddings, and RAG systems are downstream
consumers.

------------------------------------------------------------------------

# 12. Design Philosophy

The Builder follows these principles:

1.  **Source data is sacred and read-only.**
2.  **Never invent missing information.**
3.  **Verify relationships before importing text.**
4.  **Prefer traceability over convenience.**
5.  **Build cohesive passages, not isolated search fragments.**
6.  **Validate before handing the database to downstream applications.**
7.  **Keep the canonical corpus independent from search and AI layers.**

------------------------------------------------------------------------

# 13. Relationship to JASS Gurbani Explorer

The two applications have separate responsibilities.

``` text
JASS Gurbani Corpus Builder
        │
        │ creates
        ▼
JASS_Gurbani.db
        │
        │ consumed by
        ▼
JASS Gurbani Explorer
```

### Builder

**Builds and validates the corpus.**

### Explorer

**Searches, reads, organizes, and presents the corpus.**

Keeping these responsibilities separate makes the JASS ecosystem easier
to maintain and extend.

------------------------------------------------------------------------

# 14. Current Status

**Latest version: v4.6**

**Status: Verified / functional corpus-building foundation**

v4.6 is the current release to use for generating the canonical
`JASS_Gurbani.db` from the inspected `master.sqlite`.

------------------------------------------------------------------------

## Vision

> **Build once. Verify carefully. Preserve faithfully.**

JASS Gurbani Corpus Builder is the trusted data-foundation layer of the
JASS Gurbani ecosystem.
