/**
 * Drag-to-order activity (Preact island).
 *
 *   <DragOrder client:visible prompt="Order the tool-use loop"
 *     items={["Send request with tools", "Model returns tool_use", ...]}
 *     explanation="..." />
 *
 * `items` are given in the CORRECT order; they are shuffled for display with
 * a seed derived from the items, so server and browser render the same order.
 * Accessible: every item also has Move up / Move down buttons, and changes
 * are announced to screen readers.
 */
import { useMemo, useRef, useState } from 'preact/hooks';
import { shuffle } from '../../lib/grading';

interface Props {
  prompt: string;
  items: string[];
  explanation?: string;
}

const seedOf = (xs: string[]) => [...xs.join('|')].reduce((h, c) => (Math.imul(h, 31) + c.charCodeAt(0)) | 0, 7);

export default function DragOrder({ prompt, items, explanation }: Props) {
  const initial = useMemo(() => {
    let s = shuffle(items.map((_, i) => i), seedOf(items));
    // Never start already solved.
    if (s.every((v, i) => v === i)) s = [...s.slice(1), s[0]];
    return s;
  }, [items]);
  const [order, setOrder] = useState<number[]>(initial);
  const [checked, setChecked] = useState(false);
  const [announce, setAnnounce] = useState('');
  const dragFrom = useRef<number | null>(null);

  const move = (from: number, to: number) => {
    if (to < 0 || to >= order.length || from === to) return;
    const next = order.slice();
    const [x] = next.splice(from, 1);
    next.splice(to, 0, x);
    setOrder(next);
    setChecked(false);
    setAnnounce(`Moved "${items[x]}" to position ${to + 1} of ${order.length}.`);
  };

  const allRight = order.every((v, i) => v === i);

  return (
    <div class="activity">
      <div class="activity-label">Put in order</div>
      <h3 style="margin-top:0">{prompt}</h3>
      <p class="small muted">Drag items, or use the arrow buttons. Then check your order.</p>
      <ol class="order-list">
        {order.map((itemIdx, pos) => (
          <li
            key={itemIdx}
            class={`order-item ${checked ? (itemIdx === pos ? 'correct' : 'incorrect') : ''}`}
            draggable
            onDragStart={(e) => {
              dragFrom.current = pos;
              (e.currentTarget as HTMLElement).classList.add('dragging');
            }}
            onDragEnd={(e) => (e.currentTarget as HTMLElement).classList.remove('dragging')}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              if (dragFrom.current !== null) move(dragFrom.current, pos);
              dragFrom.current = null;
            }}
          >
            <span class="handle" aria-hidden="true">⋮⋮</span>
            <span class="text">
              <strong>{pos + 1}.</strong> {items[itemIdx]}
            </span>
            <span class="moves">
              <button type="button" class="btn btn-small" aria-label={`Move "${items[itemIdx]}" up`} disabled={pos === 0} onClick={() => move(pos, pos - 1)}>
                ↑
              </button>
              <button type="button" class="btn btn-small" aria-label={`Move "${items[itemIdx]}" down`} disabled={pos === order.length - 1} onClick={() => move(pos, pos + 1)}>
                ↓
              </button>
            </span>
          </li>
        ))}
      </ol>
      <div class="row">
        <button type="button" class="btn btn-primary" onClick={() => setChecked(true)}>
          Check order
        </button>
        {checked && !allRight && (
          <button type="button" class="btn" onClick={() => { setOrder(items.map((_, i) => i)); setChecked(true); }}>
            Show answer
          </button>
        )}
      </div>
      <p class="visually-hidden" aria-live="polite">{announce}</p>
      {checked && (
        <div class={`q-feedback ${allRight ? 'right' : 'wrong'}`} aria-live="polite">
          <p>
            <strong>{allRight ? 'Correct order.' : `${order.filter((v, i) => v === i).length} of ${items.length} in the right place.`}</strong>
          </p>
          {allRight && explanation && <p>{explanation}</p>}
        </div>
      )}
    </div>
  );
}
