/**
 * Renders one prepared question (see src/lib/questions.ts).
 *
 * Used in three modes:
 *  - practice (knowledge checks): answer, press Check, see feedback at once
 *  - test (quizzes, exams): pick answers; feedback only after submitting
 *  - review: read-only, with correct answers and rationales shown
 */
import type { PreparedQuestion } from '../../lib/questions';
import { scoreQuestion } from '../../lib/grading';

export type Mode = 'practice' | 'test' | 'review';

interface Props {
  q: PreparedQuestion;
  index: number;
  total: number;
  selected: string[];
  onChange?: (selected: string[]) => void;
  mode: Mode;
  /** In practice mode: whether the learner has pressed Check. */
  revealed?: boolean;
  onCheck?: () => void;
}

const TYPE_LABEL: Record<string, string> = {
  mcq: 'Multiple choice',
  multi: 'Select all that apply',
  'code-reading': 'Code reading',
  'predict-output': 'Predict the output',
  scenario: 'What would you do?',
};

export default function QuestionCard({ q, index, total, selected, onChange, mode, revealed, onCheck }: Props) {
  const multi = q.type === 'multi';
  const show = mode === 'review' || (mode === 'practice' && revealed);
  const score = show ? scoreQuestion(q, selected) : 0;
  const name = `q-${q.id}`;

  const toggle = (id: string) => {
    if (show || !onChange) return;
    if (multi) onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
    else onChange([id]);
  };

  return (
    <fieldset class="q" style="border:0;margin:0;padding-left:0;padding-right:0">
      <div class="q-type row">
        <span class="pill">{TYPE_LABEL[q.type] ?? q.type}</span>
        <span class="small muted">Question {index + 1} of {total}</span>
      </div>
      <legend class="visually-hidden">Question {index + 1}</legend>
      <div class="q-prompt" dangerouslySetInnerHTML={{ __html: q.promptHtml }} />
      {q.codeHtml && <div dangerouslySetInnerHTML={{ __html: q.codeHtml }} />}
      <ul class="q-options">
        {q.options.map((o) => {
          const picked = selected.includes(o.id);
          let cls = 'q-option';
          if (show && o.correct) cls += ' correct';
          else if (show && picked && !o.correct) cls += ' incorrect';
          return (
            <li class={cls} key={o.id}>
              <label>
                <input
                  type={multi ? 'checkbox' : 'radio'}
                  name={name}
                  checked={picked}
                  disabled={show}
                  onChange={() => toggle(o.id)}
                />
                <span>
                  <span dangerouslySetInnerHTML={{ __html: o.html }} />
                  {show && (o.correct || picked) && o.rationaleHtml && (
                    <div class="q-rationale" dangerouslySetInnerHTML={{ __html: o.rationaleHtml }} />
                  )}
                  {show && o.correct && <span class="visually-hidden"> (correct answer)</span>}
                </span>
              </label>
            </li>
          );
        })}
      </ul>
      {mode === 'practice' && !revealed && (
        <div class="row" style="margin-top:12px">
          <button type="button" class="btn btn-primary btn-small" disabled={selected.length === 0} onClick={onCheck}>
            Check
          </button>
        </div>
      )}
      {show && (
        <div class={`q-feedback ${score === 1 ? 'right' : 'wrong'}`} aria-live="polite">
          <p>
            <strong>{score === 1 ? 'Correct.' : score > 0 ? `Partly right (${Math.round(score * 100)}%).` : 'Not quite.'}</strong>
          </p>
          <div dangerouslySetInnerHTML={{ __html: q.explanationHtml }} />
        </div>
      )}
    </fieldset>
  );
}
