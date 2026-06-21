# Contact Sorter — Spec

## Problem

Two Samsung contact lists (your Google account + father's Google account) have:
1. **Cross-list conflicts**: Same person exists in both lists with different names
2. **Within-list duplicates**: Father's list has the same person under multiple names/entries
3. Goal: merge into one clean contact list with correct names

## Input

- One or more `.vcf` (vCard) files exported from Samsung Contacts or Google Contacts
- Multiple source files can be loaded simultaneously (e.g., `mine.vcf` + `father.vcf`)

## Output

- A clean, merged `.vcf` file ready for import back into the phone
- An interactive review session before export

## Architecture

### 1. VCF Parser (`vcards.py`)
- Parse vCard 2.1/3.0/4.0 (Samsung uses 2.1 and 3.0)
- Extract: FN, N, TEL (all types), EMAIL (all types), ORG, TITLE, NOTE, PHOTO, ADR, BDAY, URL, X-* custom fields
- Handle folded lines (RFC 6350 §3.1)
- Handle Samsung-specific quirks: X-GOOGLE-*, X-ANDROID custom fields, group prefixes on phone/email

### 2. Normalizer (`normalize.py`)
- **Phone normalization**: Strip all non-digit chars, normalize to E.164-ish form (keep leading +), handle Indian numbers (+91 0xxx → +91xxxxx), collapse duplicate country codes
- **Name normalization**: lowercase, strip common prefixes (Mr./Mrs./Dr./Smt./Shri), strip trailing punctuation, collapse whitespace
- **Email normalization**: lowercase, strip whitespace

### 3. Matching Engine (`matcher.py`)
Multiple signals, union-find clustering:

| Signal | Strength | Method |
|--------|----------|--------|
| Exact phone match | Strong | Normalized phone equality |
| Phone suffix match (last 10 digits) | Strong | Handles +91 vs 0 vs bare |
| Exact email match | Strong | Normalized email equality |
| High fuzzy name match | Medium | Jaro-Winkler ≥ 0.90 |
| Same org + similar name | Medium | Org exact + name fuzzy ≥ 0.80 |

- Union-find to cluster: if contact A matches B, and B matches C, all three are one cluster
- Each cluster = "these are likely the same person"
- Within each cluster, pick best name (longest non-empty name, or user override)

### 4. Merge Engine (`merger.py`)
- For each cluster, merge all non-empty fields (prefer more-complete values)
- Phone numbers: union of all unique normalized phones from all entries
- Emails: union of all unique emails
- Keep all original raw phone entries (for display)
- Preserve org/title/note from whichever entry has them

### 5. CLI (`cli.py`)
Rich-powered terminal interface:

```
$ python main.py mine.vcf father.vcf
```

Workflow:
1. Parse both files, show stats (total contacts, per-file counts)
2. Run matching, show duplicate clusters found
3. For each cluster:
   - Show all entries side-by-side (name, phones, emails, org)
   - Show match confidence and which signals triggered
   - User chooses: Accept merge / Skip / Override name / Split (keep separate)
4. Batch mode: auto-accept clusters above confidence threshold, review only ambiguous ones
5. Summary: N contacts → M contacts (saved K duplicates)
6. Export merged VCF

### 6. Export (`exporter.py`)
- Write RFC 6350-compliant vCard 3.0 output
- Include all merged data per contact

## CLI Flags

| Flag | Description |
|------|-------------|
| `--auto` | Auto-accept high-confidence merges (≥ 0.95), only show ambiguous |
| `--threshold N` | Set auto-accept threshold (default 0.95) |
| `--dry-run` | Show what would merge without writing output |
| `--output FILE` | Output file path (default: `merged_contacts.vcf`) |
| `--verbose` | Show all matching details |

## Dependencies

- `vobject` — VCF parsing (handles vCard 2.1 quirks)
- `rapidfuzz` — Fast fuzzy string matching (Jaro-Winkler, Levenshtein)
- `rich` — Terminal UI (tables, panels, prompts, progress)
- `click` — CLI argument parsing

## What This Is NOT

- NOT a phone app — it's a desktop CLI tool
- NOT cloud-based — everything runs locally on your machine
- NOT automatic — you review and approve every merge
- NOT trying to sync contacts — just clean and export
