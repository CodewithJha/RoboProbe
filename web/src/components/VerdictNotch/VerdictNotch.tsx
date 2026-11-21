import styles from './VerdictNotch.module.css';

export type Verdict = 'PASS' | 'FAIL' | 'INVALID';
export interface VerdictNotchProps {
  readonly verdict: Verdict;
  readonly className?: string;
}

/** Colour-independent verdict shape, with the verdict word available to assistive technology. */
export function VerdictNotch({ verdict, className = '' }: VerdictNotchProps) {
  return (
    <span
      className={`${styles.notch} ${styles[verdict === 'PASS' ? 'pass' : verdict === 'FAIL' ? 'fail' : 'invalid']} ${className}`}
    >
      <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
        {verdict === 'PASS' ? <circle cx="8" cy="8" r="5" /> : null}
        {verdict === 'FAIL' ? <path d="M3 3 13 13M13 3 3 13" /> : null}
        {verdict === 'INVALID' ? <path d="m8 1 7 7-7 7-7-7Z" className={styles.diamond} /> : null}
      </svg>
      <span className={styles['sr-only']}>{verdict}</span>
    </span>
  );
}
