"""Writes Markdown to the GitHub Actions job summary when running in CI."""
import os


def write_step_summary(markdown: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(markdown.rstrip() + "\n\n")
