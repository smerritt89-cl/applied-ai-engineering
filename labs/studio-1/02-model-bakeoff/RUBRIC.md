# Bake-off rubric

Score each output from 0 to 1 by adding the points below (maximum 1.0). Decide the rubric
before you read any outputs, and score blind to the model name if you can.

| Criterion | Points | Full credit when |
|---|---|---|
| Correct | 0.4 | Every fact, number, and label is right. Any factual or arithmetic error scores 0 here. |
| Follows the instructions | 0.3 | Respects the requested format, length limit, and audience (for example: exactly three bullets, JSON only, under 40 words). |
| Complete | 0.2 | Covers what the prompt asked for, with nothing important missing. |
| Usable as is | 0.1 | You would send or merge it without editing. |

Two rules:

1. **A wrong answer that looks polished still scores at most 0.6.** Fluency is not evidence
   of correctness.
2. **Do not reward length.** Human raters tend to prefer longer, more formatted answers;
   Arena's style-control analysis found length was the strongest style effect in votes. A
   short answer that does the job gets full credit.

Write one sentence in a notes column for every score below 0.7. Those notes are the start
of your error analysis.
