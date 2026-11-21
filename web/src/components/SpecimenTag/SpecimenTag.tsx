import { Link } from 'react-router-dom';
import type { ReactNode } from 'react';
import { VerdictNotch, type Verdict } from '../VerdictNotch/VerdictNotch';
import styles from './SpecimenTag.module.css';

export interface SpecimenTagProps {
  readonly kind: 'run' | 'mode';
  readonly id: string;
  readonly verdict: Verdict;
  readonly label: string;
  readonly strip?: ReactNode;
  /** A mode's campaign-scoped detail route can be supplied by its feature. */
  readonly to?: string;
}

/** Focusable specimen identity; the optional scenario glyph remains outside the link. */
export function SpecimenTag({ kind, id, verdict, label, strip, to }: SpecimenTagProps) {
  return (
    <span className={styles.tag}>
      <Link
        className={styles.link}
        to={
          to ??
          (kind === 'run' ? `/runs/${encodeURIComponent(id)}` : `/modes/${encodeURIComponent(id)}`)
        }
        aria-label={`${id} ${label}, ${kind === 'run' ? 'Run' : 'Mode'}, ${verdict}`}
      >
        <VerdictNotch verdict={verdict} />
        <span className={styles.id}>{id}</span>
        <span className={styles.label}>{label}</span>
      </Link>
      {strip !== undefined ? <span className={styles.strip}>{strip}</span> : null}
    </span>
  );
}
