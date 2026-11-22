/**
 * Keyboard shortcuts (doc 13 §4): single keys (`/`, `j`, `?`) and two-key chords (`g b`).
 *
 * Shortcuts are ignored while the user types in form fields or editable content, and while Ctrl, Alt or
 * Meta is held (browser and OS shortcuts win). The registry doubles as the data source for the `?`
 * shortcuts dialog via {@link KeyboardManager.list}.
 */

/** Typed tunables (not inline). */
export interface KeyboardConfig {
  /** How long the first key of a chord waits for the second key. */
  readonly chordTimeoutMs: number;
}

export const keyboardConfig: KeyboardConfig = { chordTimeoutMs: 1000 };

/** `global` shortcuts live for the app; `feature` ones are registered by a mounted screen. */
export type ShortcutScope = 'global' | 'feature';

export interface Shortcut {
  /** One key (`j`, `/`, `?`) or a space-separated chord (`g b`), matched against `KeyboardEvent.key`. */
  readonly keys: string;
  readonly handler: (event: KeyboardEvent) => void;
  readonly scope?: ShortcutScope;
  readonly when?: (event: KeyboardEvent) => boolean;
  /** Human-readable action shown in the `?` dialog. */
  readonly description: string;
}

/** What the `?` dialog renders for one shortcut. */
export interface ShortcutInfo {
  readonly keys: string;
  readonly scope: ShortcutScope;
  readonly description: string;
}

/** Elements whose keystrokes are text input, never shortcuts. */
const EDITABLE_SELECTOR =
  'input, textarea, select, [contenteditable]:not([contenteditable="false"])';
const CHORD_SEPARATOR = ' ';
const MAX_CHORD_LENGTH = 2;

function normaliseKeys(keys: string): string {
  const parts = keys.trim().split(/\s+/);
  if (parts[0] === '' || parts.length > MAX_CHORD_LENGTH) {
    throw new Error(`Shortcut keys must be one key or a two-key chord, got '${keys}'`);
  }
  return parts.join(CHORD_SEPARATOR);
}

function isEditable(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest(EDITABLE_SELECTOR) !== null;
}

/** Dispatches keydown events on `target` to registered shortcuts. */
export class KeyboardManager {
  private readonly shortcuts = new Map<string, Shortcut>();
  private pending: string | null = null;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private readonly onKeyDown = (event: Event): void => {
    if (event instanceof KeyboardEvent) {
      this.handle(event);
    }
  };

  constructor(
    private readonly target: EventTarget,
    private readonly config: KeyboardConfig = keyboardConfig,
  ) {
    target.addEventListener('keydown', this.onKeyDown);
  }

  /** Registers a shortcut and returns a function that unregisters it. Duplicate keys throw. */
  register(shortcut: Shortcut): () => void {
    const keys = normaliseKeys(shortcut.keys);
    const [first] = keys.split(CHORD_SEPARATOR);
    const conflicts = [...this.shortcuts.keys()].filter(
      (existing) =>
        existing === keys ||
        existing === first ||
        existing.startsWith(`${keys}${CHORD_SEPARATOR}`) ||
        keys.startsWith(`${existing}${CHORD_SEPARATOR}`),
    );
    if (conflicts.length > 0) {
      throw new Error(`Shortcut '${keys}' conflicts with '${conflicts.join("', '")}'`);
    }
    const entry = { ...shortcut, keys };
    this.shortcuts.set(keys, entry);
    this.bump();
    return () => {
      if (this.shortcuts.get(keys) === entry) {
        this.shortcuts.delete(keys);
        this.bump();
      }
    };
  }

  /** Registered shortcuts in registration order, for the `?` dialog. */
  list(): ShortcutInfo[] {
    return [...this.shortcuts.values()].map(({ keys, scope = 'global', description }) => ({
      keys,
      scope,
      description,
    }));
  }

  /** Subscribe to registry changes (for the shortcuts dialog). */
  subscribeList(listener: () => void): () => void {
    this.revisionListeners.add(listener);
    return () => this.revisionListeners.delete(listener);
  }

  /** Monotonic revision for {@link subscribeList}. */
  listRevision(): number {
    return this._listRevision;
  }

  /** Removes the listener and any pending chord. */
  dispose(): void {
    this.target.removeEventListener('keydown', this.onKeyDown);
    this.reset();
    this.shortcuts.clear();
    this.bump();
  }

  private _listRevision = 0;
  private readonly revisionListeners = new Set<() => void>();

  private bump(): void {
    this._listRevision += 1;
    this.revisionListeners.forEach((listener) => {
      listener();
    });
  }

  private reset(): void {
    this.pending = null;
    clearTimeout(this.timer);
    this.timer = undefined;
  }

  private handle(event: KeyboardEvent): void {
    if (event.ctrlKey || event.metaKey || event.altKey || event.isComposing) {
      return;
    }
    if (isEditable(event.target)) {
      this.reset();
      return;
    }
    const candidates =
      this.pending === null
        ? [event.key]
        : [`${this.pending}${CHORD_SEPARATOR}${event.key}`, event.key];
    this.reset();
    for (const keys of candidates) {
      const shortcut = this.shortcuts.get(keys);
      if (shortcut !== undefined && (shortcut.when?.(event) ?? true)) {
        event.preventDefault();
        shortcut.handler(event);
        return;
      }
      if (this.isChordPrefix(keys)) {
        this.pending = keys;
        this.timer = setTimeout(() => {
          this.reset();
        }, this.config.chordTimeoutMs);
        return;
      }
    }
  }

  private isChordPrefix(keys: string): boolean {
    const prefix = `${keys}${CHORD_SEPARATOR}`;
    return [...this.shortcuts.keys()].some((existing) => existing.startsWith(prefix));
  }
}

let defaultManager: KeyboardManager | undefined;

/** The app-wide manager bound to `document`, created on first use. */
export function getKeyboardManager(): KeyboardManager {
  defaultManager ??= new KeyboardManager(document);
  return defaultManager;
}

/** Registers a shortcut on the app-wide manager; returns the unregister function. */
export function registerShortcut(shortcut: Shortcut): () => void {
  return getKeyboardManager().register(shortcut);
}

/** Test helper: drop the singleton manager between suites. */
export function resetKeyboardManager(): void {
  defaultManager?.dispose();
  defaultManager = undefined;
}
