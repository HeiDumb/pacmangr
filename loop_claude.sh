#!/bin/bash
# Script to run Claude in a loop, updating a progress markdown file each iteration.
# Press Ctrl+C to stop.

# Ensure progress.md exists
PROGRESS_FILE="/home/hei/pacmangr/progress.md"
if [ ! -f "$PROGRESS_FILE" ]; then
  echo "# Progress Tracker" > "$PROGRESS_FILE"
  echo "" >> "$PROGRESS_FILE"
  echo "## Implemented" >> "$PROGRESS_FILE"
  echo "" >> "$PROGRESS_FILE"
  echo "## Missing" >> "$PROGRESS_FILE"
  echo "" >> "$PROGRESS_FILE"
fi

while true; do
  echo "Running Claude iteration..."
  # Call Claude Code (cli) with a prompt to update the progress file.
  # The prompt instructs Claude to read the file, summarise, and write back.
  claude -p "Read the file $PROGRESS_FILE. Summarise what has been implemented and what is still missing based on the current state of the codebase. Then rewrite $PROGRESS_FILE with two sections: ## Implemented and ## Missing, using bullet points. Keep the file in markdown format."
  echo "Iteration complete. Waiting for next loop..."
  # Optional: add a small sleep to avoid rapid spinning
  sleep 2
done