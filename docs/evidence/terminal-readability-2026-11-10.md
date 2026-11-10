# Terminal readability and deploy step times, 10 November 2026

A participant walk on a Workshop Studio test event (source `2dc073e2`) found the command
output hard to read. This records what changed and the measurement behind the one new
number.

## What changed

- A command's parts are separated by one blank line, and every participant command ends
  with a blank line and a `Next:` line naming the step that follows.
- On a terminal, more than the verdict words are coloured: green for good, red for bad,
  yellow for needs attention. Piped output is unchanged plain text.
- `hnsw_exercise.py grade` and `check_builder_tool` show their steps with the time waited.
  Neither had a measured usual time, so none is shown.
- A step whose measured times differ shows the shortest and longest, as
  `usually 0:13 to 0:27`. A step whose times did not differ keeps one figure.
- Session & Memory scrolls its answer into view and shows the time waited.

## Deploy step times

Eight deploys on that event, as the participant: the walk's first deploy, six repeats with
the code unchanged, and one more after the scripts changed.

| Step | First deploy | Six repeats | After a change | Shown as usual |
|---|---|---|---|---|
| 1/5 Build and push the image | 0:02 | 0:00 each | 0:04 | about 0:05 |
| 2/5 Update the tools runtime | 0:16 | 0:16 each | 0:16 | about 0:16 |
| 3/5 Update the Retrieval agent runtime | 0:16 | 0:16 each | 0:16 | about 0:16 |
| 4/5 Synchronize the Gateway tools | 0:20 | 0:20 each | 0:20 | about 0:21 |
| 5/5 Verify the deployment | 0:13 | 0:26 or 0:27 | 0:27 | 0:13 to 0:27 |
| Whole deploy | 1:09 | 1:20 each | 1:24 | 1:11 to 1:25 |

Verification is the only step that varied. Why it doubled after the first deploy is not
established; twenty agent runs separated the first deploy from the others. The whole
deploy's range is the sum of the steps' shown times, which is why it differs by a second or
two from the measured totals.

## Not measured

The `finish` and `skip-to` step times were not measured again; they keep the single figures
from 25 October 2026.
