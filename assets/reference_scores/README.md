# Reference Scores

Place licensed `score.json` reference files in this directory for high-similarity generation/evaluation.

For Senbonzakura acceptance:

- expected default file: `assets/reference_scores/senbonzakura.score.json`
- optional midi reference: `assets/reference_scores/senbonzakura.mid`
- schema: same as generated `projects/<project_id>/<version>/score.json`
- use with CLI:
  - `compose --target-song senbonzakura --reference-score-path assets/reference_scores/senbonzakura.score.json`
  - `compose --target-song senbonzakura --reference-midi-path assets/reference_scores/senbonzakura.mid`
  - `evaluate-similarity --target-song senbonzakura --threshold 95`

Note: do not commit copyrighted score files without permission.
