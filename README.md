# Contact Sorter

Merge and deduplicate Samsung VCF contact lists with interactive review.

## The Problem

Two Google accounts on your Samsung phone have the same people saved with different names and numbers. Your father's contact list has the same person listed 3 times under different names. You need to clean this up without manually going through hundreds of contacts.

## What It Does

1. **Loads** one or more `.vcf` files exported from Samsung Contacts or Google Contacts
2. **Finds duplicates** using multiple signals: phone numbers, fuzzy name matching, email addresses, and organization info
3. **Shows you** each potential duplicate cluster with side-by-side comparison
4. **Lets you decide** — merge, skip, rename, or keep separate
5. **Exports** a clean `.vcf` file ready to import back into your phone

## Quick Start

```bash
# Install
cd contact-sorter
uv sync

# Interactive mode (review each cluster)
uv run python main.py mine.vcf father.vcf

# Auto-merge high-confidence matches (≥95% confidence)
uv run python main.py mine.vcf father.vcf --auto

# Preview without writing
uv run python main.py mine.vcf father.vcf --dry-run

# Custom output file
uv run python main.py mine.vcf father.vcf -o clean_contacts.vcf
```

## How to Export VCF from Samsung Phone

1. Open **Contacts** app
2. Tap **⋮** (menu) → **Manage contacts** → **Import/Export**
3. Select **Export** → choose **Internal storage** or **Email**
4. The `.vcf` file will be saved

For Google Contacts:
1. Go to [contacts.google.com](https://contacts.google.com)
2. Click **Export** in the left sidebar
3. Select **Google CSV** or **vCard**

## Matching Signals

| Signal | What it means | Confidence |
|--------|---------------|------------|
| Same phone number | Identical normalized phone | 99% |
| Same last 10 digits | Matches despite country code format | 90% |
| Same email address | Identical normalized email | 99% |
| Similar name | Jaro-Winkler ≥ 0.92 | 92-99% |
| Same org + similar name | Works at same company, name is close | 80% |

Union-find clusters transitive matches: if A matches B and B matches C, all three become one cluster.

## CLI Options

| Flag | Description |
|------|-------------|
| `--auto` | Auto-accept merges ≥ threshold, only show ambiguous ones |
| `--threshold N` | Set auto-accept threshold (default 0.95) |
| `--dry-run` | Show what would merge without writing output |
| `-o, --output FILE` | Output file path (default: `merged_contacts.vcf`) |
| `-v, --verbose` | Show all matching details |

## Phone Number Normalization

Handles common Indian phone formats:
- `+91 98765 43210` → `+919876543210`
- `09876543210` → `+919876543210`
- `9876543210` → `+919876543210`
- `00919876543210` → `+919876543210`

Also handles US/international numbers by stripping formatting and preserving the `+` prefix.

## Project Structure

```
contact-sorter/
  main.py              # Entry point
  src/
    vcards.py          # VCF parsing (vCard 2.1/3.0/4.0)
    normalize.py       # Phone & name normalization
    matcher.py         # Duplicate detection engine
    merger.py          # Contact merging
    exporter.py        # VCF export
    cli.py             # Rich interactive CLI
  test_data/           # Sample VCF files for testing
  out/                 # Output directory
```
