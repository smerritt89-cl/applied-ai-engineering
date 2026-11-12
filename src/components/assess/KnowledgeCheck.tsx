/**
 * End-of-lesson knowledge check: 2 to 4 ungraded questions with instant
 * feedback. The first try on each question is recorded (so the dashboard can
 * show which ideas need review), but nothing here affects your grade.
 */
import { useState } from 'preact/hooks';
import type { PreparedQuestion } from '../../lib/questions';
import { recordCheck } from '../../lib/progress';
import { scoreQuestion } from '../../lib/grading';
import QuestionCard from './QuestionCard';

interface Props {
  lessonId: string;
  questions: PreparedQuestion[];
}

export default function KnowledgeCheck({ lessonId, questions }: Props) {
  const [answers, setAnswers] = useState<Record<string, string[]>>({});
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const done = questions.filter((q) => revealed[q.id]).length;
  const right = questions.filter((q) => revealed[q.id] && scoreQuestion(q, answers[q.id] ?? []) === 1).length;

  return (
    <section class="activity" aria-labelledby="kc-title">
      <div class="activity-label">Knowledge check · ungraded</div>
      <h2 id="kc-title" style="margin-top:0">Check your understanding</h2>
      {questions.map((q, i) => (
        <QuestionCard
          key={q.id}
          q={q}
          index={i}
          total={questions.length}
          mode="practice"
          selected={answers[q.id] ?? []}
          revealed={revealed[q.id]}
          onChange={(sel) => setAnswers({ ...answers, [q.id]: sel })}
          onCheck={() => {
            setRevealed({ ...revealed, [q.id]: true });
            recordCheck(lessonId, q.id, scoreQuestion(q, answers[q.id] ?? []) === 1);
          }}
        />
      ))}
      {done === questions.length && (
        <p class="q-feedback right" aria-live="polite">
          <strong>
            {right} of {questions.length} correct on the first try.
          </strong>{' '}
          {right === questions.length ? 'Nicely done. Mark the lesson complete below.' : 'Reread the sections behind the ones you missed, then mark the lesson complete.'}
        </p>
      )}
    </section>
  );
}
