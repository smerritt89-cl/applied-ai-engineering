import { describe, expect, it } from 'vitest';
import { notesMarkdown, orderedNotes } from '../src/lib/notes-markdown';

const index = [
  { id: 'a', title: 'First', week: 1, studio: 'Studio 1: X', href: '/l/a/' },
  { id: 'b', title: 'Second', week: 2, studio: 'Studio 1: X', href: '/l/b/' },
];
const note = (text: string) => ({ text, updatedAt: '2026-11-12T00:00:00Z' });

describe('notes markdown', () => {
  it('orders notes by course order and keeps orphaned notes last', () => {
    const rows = orderedNotes({ gone: note('old'), b: note('two'), a: note('one') }, index);
    expect(rows.map((r) => r.id)).toEqual(['a', 'b', 'gone']);
  });
  it('groups by studio and links titles when given a site url', () => {
    const md = notesMarkdown({ a: note('one\n') }, index, 'https://x.io');
    expect(md).toContain('## Studio 1: X');
    expect(md).toContain('### [Week 1 · First](https://x.io/l/a/)\n\none\n');
  });
});
