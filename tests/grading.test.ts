import { describe, expect, it } from 'vitest';
import { scoreQuestion, scoreAttempt, letter, summarizeStudio, drawBalanced, shuffle, projectScore, type StudioStructure } from '../src/lib/grading';
import { emptyState } from '../src/lib/progress';

const mcq = { id: 'q1', type: 'mcq', options: [{ id: 'a', correct: false }, { id: 'b', correct: true }] };
const multi = { id: 'q2', type: 'multi', options: [{ id: 'a', correct: true }, { id: 'b', correct: true }, { id: 'c', correct: false }, { id: 'd', correct: false }] };

describe('scoreQuestion', () => {
  it('scores single-answer questions all or nothing', () => {
    expect(scoreQuestion(mcq, ['b'])).toBe(1);
    expect(scoreQuestion(mcq, ['a'])).toBe(0);
    expect(scoreQuestion(mcq, [])).toBe(0);
    expect(scoreQuestion(mcq, ['a', 'b'])).toBe(0); // can't hedge on single-answer
  });
  it('gives partial credit on multi-select, penalizing wrong picks', () => {
    expect(scoreQuestion(multi, ['a', 'b'])).toBe(1);
    expect(scoreQuestion(multi, ['a'])).toBe(0.5);
    expect(scoreQuestion(multi, ['a', 'c'])).toBe(0);
    expect(scoreQuestion(multi, ['a', 'b', 'c', 'd'])).toBe(0); // selecting everything earns nothing
  });
});

describe('scoreAttempt and letter', () => {
  it('averages question scores', () => {
    expect(scoreAttempt([mcq, multi], { q1: ['b'], q2: ['a'] })).toBe(0.75);
  });
  it('maps scores to letters at the boundaries', () => {
    expect(letter(0.93)).toBe('A');
    expect(letter(0.929)).toBe('A-');
    expect(letter(0.8)).toBe('B-');
    expect(letter(0.59)).toBe('F');
  });
});

describe('summarizeStudio', () => {
  const s: StudioStructure = {
    id: 's1', title: 'Test', number: 1, kind: 'studio', status: 'available', accent: '',
    lessonIds: ['l1', 'l2'], quizIds: ['q1', 'q2'], examId: 'e1', projectId: 'p1',
    requiredReqIds: ['r1'], rubricIds: ['c1', 'c2'],
  };
  const attempt = (score: number) => ({ at: '2026-01-01', score, answers: [], durationSec: 60 });

  it('is provisional and renormalizes weights with partial work', () => {
    const p = emptyState();
    p.quizzes.q1 = [attempt(0.8), attempt(0.9)];
    const sum = summarizeStudio(s, p);
    expect(sum.quizScore).toBe(0.9); // best attempt
    expect(sum.grade).toBeCloseTo(0.9); // only quizzes attempted, so weight renormalized
    expect(sum.complete).toBe(false);
  });

  it('is complete only when every requirement is met', () => {
    const p = emptyState();
    p.lessons.l1 = { completedAt: 'x', secondsActive: 0, checks: {}, exercises: {} };
    p.lessons.l2 = { completedAt: 'x', secondsActive: 0, checks: {}, exercises: {} };
    p.quizzes.q1 = [attempt(1)];
    p.quizzes.q2 = [attempt(0.8)];
    p.exams.e1 = [attempt(0.85)];
    p.projects.p1 = { checklist: { r1: true }, rubric: { c1: 4, c2: 3 }, milestones: {}, defense: {}, submittedAt: 'x' };
    const sum = summarizeStudio(s, p);
    expect(sum.complete).toBe(true);
    // 0.3 * 0.9 + 0.3 * 0.85 + 0.4 * ((1 + 0.85) / 2)
    expect(sum.grade).toBeCloseTo(0.3 * 0.9 + 0.3 * 0.85 + 0.4 * 0.925);

    p.exams.e1 = [attempt(0.79)];
    expect(summarizeStudio(s, p).complete).toBe(false); // failed exam blocks completion
  });

  it('projectScore maps rubric levels', () => {
    expect(projectScore({ c1: 4, c2: 2 }, ['c1', 'c2'])).toBeCloseTo((1 + 0.7) / 2);
    expect(projectScore({}, ['c1'])).toBeNull();
  });
});

describe('exam drawing', () => {
  const pool = Array.from({ length: 40 }, (_, i) => ({ id: `q${i}`, week: (i % 4) + 1 }));
  it('draws the requested number of unique questions, balanced by week', () => {
    const paper = drawBalanced(pool, 20, 123);
    expect(paper).toHaveLength(20);
    expect(new Set(paper.map((q) => q.id)).size).toBe(20);
    for (const w of [1, 2, 3, 4]) expect(paper.filter((q) => q.week === w).length).toBe(5);
  });
  it('shuffle is deterministic for a seed and preserves elements', () => {
    expect(shuffle([1, 2, 3, 4, 5], 7)).toEqual(shuffle([1, 2, 3, 4, 5], 7));
    expect(shuffle([1, 2, 3, 4, 5], 7).sort()).toEqual([1, 2, 3, 4, 5]);
  });
});
