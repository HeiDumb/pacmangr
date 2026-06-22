#!/bin/bash
# Loop that repeatedly asks fcc-claude to update a progress markdown file.
# Press Ctrl+C to stop.

PROGRESS_FILE="/home/hei/pacmangr/progress.md"

# Make sure the progress file exists with the expected sections
if [ ! -f "$PROGRESS_FILE" ]; then
  echo "# Progress Tracker" > "$PROGRESS_FILE"
  echo "" >> "$PROGRESS_FILE"
  echo "## Implemented" >> "$PROGRESS_FILE"
  echo "" >> "$PROGRESS_FILE"
  echo "## Missing" >> "$PROGRESS_FILE"
  echo "" >> "$PROGRESS_FILE"
fi

while true; do
  echo "Running fcc-claude iteration..."
  # Ask fcc-claude to read the current progress file, summarise the state,
  # and rewrite it with updated ## Implemented and ## Missing sections.
  fcc-claude -p "Read the file $PROGRESS_FILE. Summarise what has been implemented and what is still missing based on the current state of the codebase. Then rewrite $PROGRESS_FILE with two sections: ## Implemented and ## Missing, using bullet points. Keep the file in markdown format."
  echo "Iteration complete. Waiting for next loop..."
  # Small pause to avoid a tight spin; adjust as needed.
  sleep 2
done