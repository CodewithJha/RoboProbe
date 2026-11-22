import styles from './RobustnessBar.module.css';

export interface RobustnessBarProps {
  readonly value: number;
  readonly label?: string;
}

/** Centred −1…1 meter; invalid data is exposed as unavailable rather than a fabricated zero. */
export function RobustnessBar({ value, label = 'Robustness' }: RobustnessBarProps) {
  if (!Number.isFinite(value))
    return (
      <span className={styles.unavailable} aria-label={`${label}: unavailable`}>
        —
      </span>
    );
  const bounded = Math.min(1, Math.max(-1, value));
  const text = new Intl.NumberFormat(undefined, {
    maximumFractionDigits: 2,
    signDisplay: 'exceptZero',
  }).format(bounded);
  return (
    <span
      className={styles.root}
      role="meter"
      aria-label={label}
      aria-valuemin={-1}
      aria-valuemax={1}
      aria-valuenow={bounded}
      aria-valuetext={text}
    >
      <span className={styles.track} aria-hidden="true">
        <span
          className={`${styles.fill} ${bounded < 0 ? styles.failure : styles.safe}`}
          style={{
            left: `${String(bounded < 0 ? (1 + bounded) * 50 : 50)}%`,
            width: `${String(Math.abs(bounded) * 50)}%`,
          }}
        />
        <span className={styles.zero} />
      </span>
      <span className={styles.value} aria-hidden="true">
        {text}
      </span>
    </span>
  );
}
