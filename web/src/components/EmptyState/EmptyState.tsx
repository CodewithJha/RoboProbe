import { Link } from 'react-router-dom';
import type { ReactNode } from 'react';
import styles from './EmptyState.module.css';

type EmptyAction = { readonly label: string } & (
  | { readonly to: string; readonly onClick?: never }
  | { readonly onClick: () => void; readonly to?: never }
);
export interface EmptyStateProps {
  readonly title: string;
  readonly body: string;
  readonly action?: EmptyAction;
  readonly illustration?: ReactNode;
}

/** Empty content explains the next useful action; copy belongs to the calling feature. */
export function EmptyState({ title, body, action, illustration }: EmptyStateProps) {
  return (
    <section className={styles.root}>
      {illustration !== undefined ? <div aria-hidden="true">{illustration}</div> : null}
      <h2>{title}</h2>
      <p>{body}</p>
      {action === undefined ? null : action.to !== undefined ? (
        <Link className={styles.action} to={action.to}>
          {action.label}
        </Link>
      ) : (
        <button className={styles.action} type="button" onClick={action.onClick}>
          {action.label}
        </button>
      )}
    </section>
  );
}
