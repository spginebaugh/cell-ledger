"""Discovery evals: does the specialist find the right GEO series, ask when it should, and
never invent an accession, and how does plain Claude with web search do on the same cases?

Only the discover step is evaluated. The design step (sample labelling, contrast choice) is
covered by the pipeline tests, not by these evals.

    python -m evals.run validate                 # check the case files
    python -m evals.run run --system both        # run every case through both systems
    python -m evals.run score data/evals/runs/<id>
    python -m evals.run queue                    # candidates waiting for a human verdict

See evals/README.md.
"""
