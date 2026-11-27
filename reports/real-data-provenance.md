# Data Provenance & Third-Party License Audit

Updated: 2026-11-26 | Branch: `phase-9-hardening`

## 1. Default Dev Data Policy

- **Default development database (`python -m scripts.seed --reset`):** Generates deterministic synthetic demo data (`SEED_END_DATE=2026-11-23`, `random.seed(42)`) across all 6 tables (`health_daily`, `github_commits`, `reading_log`, `screen_time`, `notes`, `note_chunks`). Served with `DATA_LABEL="Synthetic demo data"` (default).
- **Opt-in composite demo (`python -m scripts.ingest_real_data --composite-demo --reset`):** Disabled by default and gated behind explicit `--composite-demo`. Combines unrelated third-party public datasets alongside the owner's public GitHub commit history. Cross-source correlations (for example, sleep vs. commits) are **not** meaningful in `--composite-demo` mode, and unmeasured fields (`hrv_ms`, missing `sleep_score`, `reading_log.minutes`, missing `resting_hr`, and Fitbit `deep_sleep_min`) are left as SQL `NULL` (`None`) rather than fabricated. When serving a composite database, set:
  ```dotenv
  DATA_LABEL="Composite public datasets + my GitHub commits (not personal health data)"
  ```

---

## 2. Third-Party License Audit (Verbatim Findings)

Each source fetched by `app/ingestion/real_data.py` was queried via upstream repository/API metadata and README files on 2026-11-26:

| Source | Dataset / URL | Verbatim License Finding | Restrictions & Handling in `--composite-demo` |
|---|---|---|---|
| Owner GitHub commits | `https://github.com/Mr-Vicky-06` + local `.git` | Owner public GitHub repositories + local git history | Native 2026 commit timestamps & SHAs; diffs collected locally via `git log --numstat` (remote shallow clones report `additions=0, deletions=0` when tree blobs are omitted). |
| Zenodo `15171250` (`GroupHealth_SleepScreen.csv`) | `https://zenodo.org/api/records/15171250` | API `metadata.license = {"id": "cc-by-4.0"}` (`CC-BY 4.0`) | Subset (`UID 4`, `UID 2`, `UID 1`) mapped chronologically into the demo date window; unmeasured `hrv_ms`, missing `sleep_rating`, and missing `resting_heart_rate` stored as `NULL`; `screentime` stored as `"Total (unclassified)"` without synthetic category splits. |
| Fitbit Fitabase (`health-hacks/datasets`) | `https://github.com/health-hacks/datasets` (`fitbit-mturk/...`) | **no license found** (GitHub `/license` returned 404; repo `license: null`; no LICENSE file in root or dataset READMEs) | Included only when `--composite-demo` is passed; only `sleep_hours` and `steps` are stored (`sleep_score`, `deep_sleep_min`, `hrv_ms`, `resting_hr` are all `NULL`). |
| `emadnahed/ScreenTimeAnalyzer` (`Screentime-App-Details.csv`) | `https://github.com/emadnahed/ScreenTimeAnalyzer` | **MIT License** (README.md ends with `## License` / `This project is licensed under the MIT License.`) | Used only for `"Social"` screen-time rows on days without GroupHealth totals; no synthetic `Productivity`/`Entertainment` weights. |
| `JB3NNETT/Goodreads-TBR` (`goodreads_library_export.csv`) | `https://github.com/JB3NNETT/Goodreads-TBR` | **no license found** (GitHub `/license` returned 404; repo `license: null`; root has no LICENSE file) | Included only when `--composite-demo` is passed; `reading_log.minutes` stored as `NULL` because Goodreads exports contain page counts only. |
| `mmarkusmalone/journal-entries-emotion-detection-vad` (`vad_data.csv`) | `https://huggingface.co/datasets/mmarkusmalone/journal-entries-emotion-detection-vad` | **`CC-BY-NC-4.0`** (Hugging Face `README.md` YAML frontmatter `license: cc-by-nc-4.0`) | Non-commercial attribution required; filtered diary excerpts placed on alternating dates without valence/sleep matching or `[Sleep: ...]` metric prefixes. |

### Required CC-BY 4.0 Attribution (Zenodo Record 15171250)

> This project's optional `--composite-demo` dataset uses portions of **Group Health Dataset (Sleep and Screen Time)** by **Gogate** (Eindhoven University of Technology), DOI [10.5281/zenodo.15171250](https://doi.org/10.5281/zenodo.15171250) ([https://zenodo.org/records/15171250](https://zenodo.org/records/15171250)), licensed under the [Creative Commons Attribution 4.0 International License (CC-BY 4.0)](https://creativecommons.org/licenses/by/4.0/).
>
> **Changes made:** Filtered to participant UIDs `1`, `2`, and `4`, aggregated by UTC calendar date, monotonically shifted into the configured showcase window, and left unmeasured fields (`hrv_ms`, absent `sleep_rating`, and absent `resting_heart_rate`) as `NULL`.

---

## 3. Repository Tracking Audit

- `git ls-files` audit on `phase-9-hardening` confirmed **0** raw third-party CSVs, JSONs, or downloaded datasets are tracked in Git.
- `.gitignore` excludes `.cache/` and `data/raw/` so cached third-party downloads stay out of version control.
