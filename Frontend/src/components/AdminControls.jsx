/**
 * The organiser's controls: a small "Remove" beside each player at the
 * table or in the queue, shown only to an admin. It asks before doing
 * anything - a slip of the finger mustn't throw someone off the table -
 * and says what will happen to the game and the line.
 *
 * Hiding these from everyone else is only a courtesy: the server refuses
 * anyone who isn't an admin.
 */
import React, { useEffect, useRef } from 'react';
import { UserX } from 'lucide-react';

/** The quiet trigger beside a player's name. */
export function RemoveButton({ id, name, place, expanded, controls, onClick }) {
  const label = `Remove ${name} from ${place}`;
  return (
    <button
      type="button"
      id={id}
      className="admin-remove"
      onClick={onClick}
      aria-expanded={expanded}
      aria-controls={expanded ? controls : undefined}
      aria-label={label}
      title={label}
    >
      <UserX size={14} aria-hidden="true" />
      <span>Remove</span>
    </button>
  );
}

/**
 * "Remove them?" with what it means. Opens with the safe answer focused;
 * Escape or "Keep them" closes it and puts focus back on the trigger.
 */
export function RemoveConfirm({ id, question, consequence, onConfirm, onCancel, busy, triggerId }) {
  const keepRef = useRef(null);
  useEffect(() => {
    keepRef.current?.focus();
  }, []);

  const close = () => {
    onCancel();
    document.getElementById(triggerId)?.focus();
  };

  return (
    <div
      className="admin-confirm"
      id={id}
      role="group"
      aria-label={question}
      onKeyDown={(e) => {
        if (e.key === 'Escape') close();
      }}
    >
      <p className="admin-confirm-question">{question}</p>
      <p className="small admin-confirm-text">{consequence}</p>
      <div className="admin-confirm-actions">
        <button type="button" className="btn btn-danger btn-small" onClick={onConfirm} disabled={busy}>
          <UserX size={15} aria-hidden="true" />
          Remove
        </button>
        <button type="button" ref={keepRef} className="btn btn-quiet btn-small" onClick={close}>
          Keep them
        </button>
      </div>
    </div>
  );
}
